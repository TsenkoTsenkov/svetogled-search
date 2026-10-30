#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["yt-dlp"]
# ///
"""Refresh the YOUTUBE_COOKIES GitHub secret from this Mac's Chrome.

The weekly transcript workflow downloads audio from GitHub's datacenter IPs,
which YouTube only allows with a signed-in cookie jar. An exported jar goes
stale within weeks (the browser rotates its session), and every weekly run
then fails with "Sign in to confirm you're not a bot" — Беседи 292-297 were
missed for two months that way. Re-exporting daily from a Chrome that is
signed in to YouTube keeps the secret current.

Installed as a daily LaunchAgent by scripts/install_cookie_refresh.sh.
Run by hand with:  uv run --script scripts/refresh_youtube_cookies.py [--dry-run]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser

REPO = "TsenkoTsenkov/svetogled-search"
SECRET = "YOUTUBE_COOKIES"
# The active gh account may lack admin on the repo; setting secrets needs
# the owner's token.
GH_USER = os.environ.get("SVETOGLED_GH_USER", "TsenkoTsenkov")

# A full Chrome export (~150-500KB, every Google domain) exceeds GitHub's 48KB
# secret limit; these domains are all yt-dlp needs (~9KB).
KEEP_DOMAINS = {
    "youtube.com", "www.youtube.com",
    "google.com", "www.google.com", "accounts.google.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}
# Present only when signed in. Missing means Chrome is signed out of YouTube
# or decryption failed — uploading such a jar would break the next run.
REQUIRED = {"LOGIN_INFO", "SID", "__Secure-3PSID"}
MAX_SECRET_BYTES = 48_000


def notify(message):
    """Best-effort macOS notification so a failed background run is noticed."""
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "Svetogled: YouTube cookies"'],
        capture_output=True,
    )


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    notify(message)
    sys.exit(1)


def export_cookies(profile):
    jar = extract_cookies_from_browser("chrome", profile)
    kept = YoutubeDLCookieJar()
    for cookie in jar:
        if cookie.domain.lstrip(".") in KEEP_DOMAINS:
            kept.set_cookie(cookie)

    present = {c.name for c in kept if c.value}
    missing = REQUIRED - present
    if missing:
        fail(f"Chrome is not signed in to YouTube (missing {', '.join(sorted(missing))}). "
             "Sign in to youtube.com in Chrome.")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.txt"
        kept.save(str(path))
        body = path.read_text(encoding="utf-8")

    if len(body.encode()) > MAX_SECRET_BYTES:
        fail(f"Filtered cookie jar is {len(body.encode())} bytes, over GitHub's secret limit.")
    return body, len(kept)


def set_secret(body):
    token = subprocess.run(
        ["gh", "auth", "token", "-u", GH_USER],
        capture_output=True, text=True,
    )
    if token.returncode != 0 or not token.stdout.strip():
        fail(f"No gh token for {GH_USER} — run: gh auth login (as {GH_USER}).")

    result = subprocess.run(
        ["gh", "secret", "set", SECRET, "-R", REPO],
        input=body, capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": token.stdout.strip()},
    )
    if result.returncode != 0:
        fail(f"gh secret set failed: {(result.stderr or result.stdout).strip()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="Chrome profile name (default: Default)")
    parser.add_argument("--dry-run", action="store_true",
                        help="export and validate, but do not upload")
    args = parser.parse_args()

    try:
        body, count = export_cookies(args.profile)
    except FileNotFoundError:
        # macOS hides Chrome's profile from apps without Full Disk Access, so
        # yt-dlp reports the cookie database as missing rather than denied.
        fail("Cannot read Chrome cookies — grant SvetogledCookieRefresh.app "
             "Full Disk Access in System Settings → Privacy & Security.")
    except Exception as e:
        fail(f"Cookie export failed: {e}")
    print(f"Exported {count} YouTube/Google cookies ({len(body.encode())} bytes).")
    if args.dry_run:
        print("Dry run — secret not updated.")
        return
    set_secret(body)
    print(f"Updated {SECRET} on {REPO}.")


if __name__ == "__main__":
    main()
