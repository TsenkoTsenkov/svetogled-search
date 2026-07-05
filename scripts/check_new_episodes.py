#!/usr/bin/env python3
"""Check playlist for episodes not yet in our transcripts folder."""

import json
import os
from pathlib import Path

import yt_dlp

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLvX0cuPYCospMRKzBKtS5xYPFpsuEQwDQ"
TRANSCRIPTS_DIR = Path("transcripts")


def get_playlist_videos():
    # Optional cookies for datacenter IPs (GitHub Actions); ignored locally.
    cookies = os.environ.get("YTDLP_COOKIES", "")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "cookiefile": cookies if cookies and Path(cookies).exists() else None,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)
        entries = list(info.get("entries", []))
        videos = [
            {"id": e.get("id", ""), "title": e.get("title", "Unknown")}
            for e in entries if e is not None
        ]

    # Guard against a degraded/blocked fetch masquerading as "no new episodes".
    # From a datacenter IP YouTube can return a truncated or empty playlist
    # without raising; that used to silently yield new_count=0, so the weekly
    # job reported success while committing nothing. The playlist has ~300
    # videos, so anything far below that means the fetch failed — raise instead
    # of quietly under-reporting.
    MIN_EXPECTED = 250
    if len(videos) < MIN_EXPECTED:
        raise RuntimeError(
            f"Playlist fetch returned only {len(videos)} videos (expected "
            f">= {MIN_EXPECTED}). YouTube likely blocked or throttled this IP — "
            f"refusing to under-report new episodes. Check the YOUTUBE_COOKIES "
            f"secret (it may be expired)."
        )
    return videos


def get_existing_ids():
    ids = set()
    for f in TRANSCRIPTS_DIR.glob("*.json"):
        ids.add(f.stem)
    return ids


def get_removed_ids():
    """Video IDs deliberately removed from the archive (e.g. non-existent /
    duplicate uploads). These live in removed_episodes.json — the same file
    search_app.py uses — so a removed video is never re-detected as "new"
    and re-fetched on the next weekly run."""
    fpath = Path(__file__).resolve().parent.parent / "removed_episodes.json"
    try:
        return set(json.loads(fpath.read_text(encoding="utf-8")).keys())
    except (OSError, json.JSONDecodeError):
        return {"gGhf8HSSGwI"}  # Пророк Илия — fallback if file missing


def main():
    print("Checking playlist for new episodes...")
    videos = get_playlist_videos()
    existing = get_existing_ids()
    removed = get_removed_ids()

    new_videos = [
        v for v in videos
        if v["id"] not in existing
        and v["id"] not in removed          # never re-fetch deliberately-removed videos
        and v["id"]
        and v["title"] != "[Private video]"
        and v["title"] != "[Deleted video]"
    ]
    print(f"Playlist: {len(videos)} videos")
    print(f"Existing transcripts: {len(existing)}")
    print(f"Removed (excluded): {len(removed)}")
    print(f"New episodes: {len(new_videos)}")

    # Save new video list for next steps
    Path("new_videos.json").write_text(
        json.dumps(new_videos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Set GitHub Actions output
    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"new_count={len(new_videos)}\n")

    if new_videos:
        print("\nNew episodes:")
        for v in new_videos:
            print(f"  {v['id']} — {v['title']}")


if __name__ == "__main__":
    main()
