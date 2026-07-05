#!/usr/bin/env python3
"""
Google Search Console helper — indexing-coverage report + sitemap submit.

Two subcommands:

  coverage   Inspect every URL in the live sitemap via the URL Inspection API
             and report which are indexed vs. "Discovered/Crawled – not
             indexed" vs. excluded. READ-ONLY — Google's Indexing API cannot
             force-index general content (it is limited to JobPosting /
             BroadcastEvent), so this diagnoses the gap rather than fixing it.

  submit     Submit the sitemap via sitemaps.submit. Low impact (Google
             re-reads the sitemap on its own), but harmless and automatable
             after the weekly episode update.

Auth (one-time, done by a human — the OAuth consent can't be scripted):

    gcloud config set account tseni.tsenkov@gmail.com
    gcloud auth application-default login \
        --scopes=https://www.googleapis.com/auth/webmasters.readonly,\
https://www.googleapis.com/auth/webmasters,\
https://www.googleapis.com/auth/cloud-platform

  and enable the API once:
    gcloud services enable searchconsole.googleapis.com --project svetogled-arhiv

  The Google account MUST be an owner/full user of the Search Console property.
  In CI, set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON that has
  been added as a delegated owner of the property in Search Console.

Deps (not stdlib):  pip install google-api-python-client google-auth
Usage:
    python3 scripts/gsc_seo.py coverage [--limit N] [--json out.json]
    python3 scripts/gsc_seo.py submit
"""

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from urllib.request import urlopen

# Search Console's siteUrl for a Domain property is "sc-domain:<domain>"; for a
# URL-prefix property it's the full origin. This site is verified as a Domain
# property (confirmed via sites().list() → siteOwner on sc-domain:...), so the
# API calls must use the sc-domain form or Google returns "you do not own this
# site". The sitemap and inspected URLs are still the normal https:// URLs.
SITE_URL = "sc-domain:svetogled-arhiv.com"
SITEMAP_URL = "https://svetogled-arhiv.com/sitemap.xml"

SCOPES_RO = ["https://www.googleapis.com/auth/webmasters.readonly"]
SCOPES_RW = ["https://www.googleapis.com/auth/webmasters"]


def _build_service(scopes):
    """Build the Search Console API client from Application Default Credentials."""
    try:
        import google.auth
        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit(
            "Missing deps. Run:\n"
            "  pip install google-api-python-client google-auth "
            "google-auth-httplib2"
        )
    try:
        creds, _ = google.auth.default(scopes=scopes)
    except Exception as e:  # noqa: BLE001 — surface the auth hint, not a stacktrace
        sys.exit(
            f"Could not load Google credentials: {e}\n"
            "Run the gcloud auth command in this script's docstring first."
        )
    # A 30s socket timeout keeps one hung request from blocking a pool worker
    # forever (bulk inspection occasionally stalls). searchconsole v1 exposes
    # both urlInspection and sitemaps.
    http = google_auth_httplib2.AuthorizedHttp(
        creds, http=httplib2.Http(timeout=30)
    )
    return build("searchconsole", "v1", http=http, cache_discovery=False)


def _url_kind(url):
    """Classify a sitemap URL so the report can headline episodes separately."""
    path = url.split("svetogled-arhiv.com", 1)[-1]
    if path in ("", "/"):
        return "home"
    if "/episode/" in path:
        return "episode"
    if "/tema/" in path:
        return "theme"
    if path.rstrip("/") in ("/arhiv", "/temi"):
        return "hub"
    return "other"


def _fetch_sitemap_urls():
    """Return the list of <loc> URLs from the live sitemap."""
    with urlopen(SITEMAP_URL, timeout=30) as resp:
        xml = resp.read()
    root = ET.fromstring(xml)
    # Sitemap namespace-agnostic: match any element whose tag ends in 'loc'.
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def cmd_coverage(args):
    service = _build_service(SCOPES_RO)
    urls = _fetch_sitemap_urls()
    if args.limit:
        urls = urls[: args.limit]
    print(f"Inspecting {len(urls)} URLs from {SITEMAP_URL} ...\n", file=sys.stderr)

    # Each URL Inspection call takes ~6-7s of API latency, so serial over 331
    # URLs is ~35 min. Fan out across a small thread pool: googleapiclient's
    # http object isn't thread-safe, so each worker builds its OWN service.
    # Google throttles bulk inspection aggressively — at 8 workers a live run
    # returned ~30 timeouts/connection-resets, so we use 4 workers and a
    # 30s per-request socket timeout with up to 3 retries (backoff) to make
    # the report complete rather than fast.
    from concurrent.futures import ThreadPoolExecutor
    import threading

    _local = threading.local()
    RETRIABLE = ("429", "timed out", "timeout", "reset by peer",
                 "connection", "503", "500", "502", "504")

    def _svc():
        s = getattr(_local, "svc", None)
        if s is None:
            s = _build_service(SCOPES_RO)
            _local.svc = s
        return s

    done = [0]
    done_lock = threading.Lock()

    def _inspect(url):
        body = {"inspectionUrl": url, "siteUrl": SITE_URL, "languageCode": "bg"}
        row = {"url": url, "kind": _url_kind(url),
               "verdict": "ERROR", "coverageState": "no response"}
        last_err = ""
        for attempt in range(3):
            try:
                # num_retries handles transient 5xx inside the client; the
                # 30s http timeout stops a hung socket from blocking a worker.
                resp = (
                    _svc().urlInspection().index()
                    .inspect(body=body)
                    .execute(num_retries=2)
                )
                idx = resp.get("inspectionResult", {}).get("indexStatusResult", {})
                row = {
                    "url": url,
                    "kind": _url_kind(url),
                    "verdict": idx.get("verdict", "UNKNOWN"),
                    "coverageState": idx.get("coverageState", "unknown"),
                }
                last_err = ""
                break
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                if any(t in last_err.lower() for t in RETRIABLE) and attempt < 2:
                    time.sleep(5 * (attempt + 1))  # 5s, 10s backoff
                    continue
                break
        if last_err:
            row = {"url": url, "kind": _url_kind(url),
                   "verdict": "ERROR", "coverageState": last_err[:80]}
        with done_lock:
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(urls):
                print(f"  ... {done[0]}/{len(urls)}", file=sys.stderr)
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(_inspect, urls))

    # If any URL still errored after retries, say so loudly — a silent partial
    # report would read as "these pages aren't indexed" when we just failed to
    # check them.
    errored = [r for r in rows if r["verdict"] == "ERROR"]
    if errored:
        print(f"\n⚠ {len(errored)} URL(s) could not be inspected (API errors, "
              f"not indexing problems) — rerun to fill gaps.", file=sys.stderr)

    buckets = {}
    not_indexed = []
    for r in rows:
        buckets[r["coverageState"]] = buckets.get(r["coverageState"], 0) + 1
        if r["verdict"] != "PASS":
            not_indexed.append((r["url"], r["coverageState"]))

    # ── Report ──
    print("\n=== Indexing coverage ===")
    for state, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {state}")

    # Per-kind headline: episodes are what we actually care about.
    print("\n=== Indexed by page type (verdict PASS) ===")
    for kind in ("episode", "theme", "hub", "home", "other"):
        krows = [r for r in rows if r["kind"] == kind]
        if not krows:
            continue
        ok = sum(1 for r in krows if r["verdict"] == "PASS")
        print(f"  {kind:8s} {ok:3d}/{len(krows):3d} indexed")

    # The stragglers, split so you can act on the episodes first.
    missing_eps = [(u, s) for (u, s) in not_indexed if _url_kind(u) == "episode"]
    if missing_eps:
        print(f"\n=== Episodes NOT yet indexed ({len(missing_eps)}) ===")
        print("  (Request-Index these by hand in Search Console — ~10/day quota)")
        for url, state in missing_eps:
            print(f"  [{state}] {url}")

    other_missing = [(u, s) for (u, s) in not_indexed if _url_kind(u) != "episode"]
    if other_missing:
        print(f"\n=== Non-episode pages NOT indexed ({len(other_missing)}) ===")
        for url, state in other_missing:
            print(f"  [{_url_kind(url)}] [{state}] {url}")

    if args.json:
        import json
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"\nWrote {len(rows)} rows to {args.json}", file=sys.stderr)

    # Plain list of not-yet-indexed episode URLs — easy to paste one per day.
    if args.missing_out and missing_eps:
        with open(args.missing_out, "w", encoding="utf-8") as f:
            f.write("\n".join(u for u, _ in missing_eps) + "\n")
        print(f"Wrote {len(missing_eps)} missing episode URLs to {args.missing_out}",
              file=sys.stderr)


def cmd_submit(args):
    service = _build_service(SCOPES_RW)
    service.sitemaps().submit(
        siteUrl=SITE_URL, feedpath=SITEMAP_URL
    ).execute()
    print(f"Submitted sitemap {SITEMAP_URL} for {SITE_URL}")
    # Read back the status so the caller sees it was accepted.
    info = service.sitemaps().get(siteUrl=SITE_URL, feedpath=SITEMAP_URL).execute()
    print(
        f"  lastSubmitted={info.get('lastSubmitted')} "
        f"isPending={info.get('isPending')} "
        f"contents={info.get('contents')}"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("coverage", help="Report indexing coverage for sitemap URLs")
    c.add_argument("--limit", type=int, default=0,
                   help="Only inspect the first N URLs (for a quick sample)")
    c.add_argument("--json", metavar="FILE", help="Also write full results as JSON")
    c.add_argument("--missing-out", metavar="FILE",
                   help="Write not-yet-indexed episode URLs, one per line")
    c.set_defaults(func=cmd_coverage)

    s = sub.add_parser("submit", help="Submit the sitemap to Search Console")
    s.set_defaults(func=cmd_submit)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
