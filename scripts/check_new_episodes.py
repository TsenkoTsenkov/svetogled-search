#!/usr/bin/env python3
"""Check playlist for episodes not yet in our transcripts folder."""

import json
import os
from pathlib import Path

import yt_dlp

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLvX0cuPYCospMRKzBKtS5xYPFpsuEQwDQ"
TRANSCRIPTS_DIR = Path("transcripts")


def get_playlist_videos():
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)
        entries = list(info.get("entries", []))
        return [
            {"id": e.get("id", ""), "title": e.get("title", "Unknown")}
            for e in entries if e is not None
        ]


def get_existing_ids():
    ids = set()
    for f in TRANSCRIPTS_DIR.glob("*.json"):
        ids.add(f.stem)
    return ids


def main():
    print("Checking playlist for new episodes...")
    videos = get_playlist_videos()
    existing = get_existing_ids()

    new_videos = [
        v for v in videos
        if v["id"] not in existing
        and v["id"]
        and v["title"] != "[Private video]"
        and v["title"] != "[Deleted video]"
    ]
    print(f"Playlist: {len(videos)} videos")
    print(f"Existing transcripts: {len(existing)}")
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
