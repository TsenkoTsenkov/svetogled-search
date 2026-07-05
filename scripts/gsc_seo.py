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

SITE_URL = "https://svetogled-arhiv.com/"
SITEMAP_URL = "https://svetogled-arhiv.com/sitemap.xml"

# Search Console's siteUrl for a domain property is "sc-domain:<domain>";
# for a URL-prefix property it's the full origin. This site is verified as a
# URL-prefix property, so SITE_URL above is correct. If you switch to a domain
# property, set SITE_URL = "sc-domain:svetogled-arhiv.com".

SCOPES_RO = ["https://www.googleapis.com/auth/webmasters.readonly"]
SCOPES_RW = ["https://www.googleapis.com/auth/webmasters"]


def _build_service(scopes):
    """Build the Search Console API client from Application Default Credentials."""
    try:
        import google.auth
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit(
            "Missing deps. Run:\n"
            "  pip install google-api-python-client google-auth"
        )
    try:
        creds, _ = google.auth.default(scopes=scopes)
    except Exception as e:  # noqa: BLE001 — surface the auth hint, not a stacktrace
        sys.exit(
            f"Could not load Google credentials: {e}\n"
            "Run the gcloud auth command in this script's docstring first."
        )
    # searchconsole v1 exposes both urlInspection and sitemaps.
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


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

    buckets = {}          # verdict -> count
    not_indexed = []      # urls Google knows but hasn't indexed
    rows = []             # full per-url detail for --json

    for i, url in enumerate(urls, 1):
        body = {"inspectionUrl": url, "siteUrl": SITE_URL, "languageCode": "bg"}
        try:
            resp = (
                service.urlInspection()
                .index()
                .inspect(body=body)
                .execute()
            )
        except Exception as e:  # noqa: BLE001
            # 429 = quota (2000/day, 600/min). Back off and retry once.
            if "429" in str(e):
                time.sleep(60)
                try:
                    resp = (
                        service.urlInspection().index().inspect(body=body).execute()
                    )
                except Exception as e2:  # noqa: BLE001
                    print(f"  [{i}/{len(urls)}] ERROR {url}: {e2}", file=sys.stderr)
                    continue
            else:
                print(f"  [{i}/{len(urls)}] ERROR {url}: {e}", file=sys.stderr)
                continue

        result = resp.get("inspectionResult", {})
        idx = result.get("indexStatusResult", {})
        verdict = idx.get("verdict", "UNKNOWN")            # PASS / FAIL / NEUTRAL
        coverage = idx.get("coverageState", "unknown")     # human-readable state
        buckets[coverage] = buckets.get(coverage, 0) + 1
        rows.append({
            "url": url,
            "kind": _url_kind(url),
            "verdict": verdict,
            "coverageState": coverage,
        })
        # verdict == "PASS" means the URL is on Google. Anything else = a gap.
        if verdict != "PASS":
            not_indexed.append((url, coverage))

        # Polite pacing: 600 req/min ceiling → ~10/s. Stay well under.
        time.sleep(0.15)
        if i % 25 == 0:
            print(f"  ... {i}/{len(urls)}", file=sys.stderr)

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
