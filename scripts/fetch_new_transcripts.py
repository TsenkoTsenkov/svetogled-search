#!/usr/bin/env python3
"""Fetch transcripts for new episodes using YouTube transcript API first."""

import json
import time
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

TRANSCRIPTS_DIR = Path("transcripts")
NEW_VIDEOS_FILE = Path("new_videos.json")
REMAINING_FILE = Path("remaining_videos.json")


def main():
    if not NEW_VIDEOS_FILE.exists():
        print("No new_videos.json found")
        return

    videos = json.loads(NEW_VIDEOS_FILE.read_text(encoding="utf-8"))
    print(f"Attempting YouTube transcript API for {len(videos)} videos...")

    api = YouTubeTranscriptApi()
    succeeded = 0
    remaining = []

    for i, video in enumerate(videos):
        vid = video["id"]
        title = video["title"]
        print(f"[{i+1}/{len(videos)}] {title}")

        try:
            transcript_list = api.list(vid)
            transcript = None

            # Try Bulgarian
            for t in transcript_list:
                if t.language_code.startswith("bg"):
                    transcript = t.fetch()
                    break

            if transcript is None:
                print(f"  No Bulgarian transcript available")
                remaining.append(video)
                continue

            snippets = [
                {"text": s.text, "start": s.start, "duration": s.duration}
                for s in transcript
            ]

            data = {
                "video_id": vid,
                "title": title,
                "source": "youtube-auto",
                "segment_count": len(snippets),
                "snippets": snippets,
                "full_text": " ".join(s.text for s in transcript),
            }

            outfile = TRANSCRIPTS_DIR / f"{vid}.json"
            outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  OK: {len(snippets)} segments")
            succeeded += 1

        except Exception as e:
            print(f"  Failed: {str(e)[:100]}")
            remaining.append(video)

        time.sleep(2)  # Rate limit

    # Save remaining for Whisper
    REMAINING_FILE.write_text(
        json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nYouTube API: {succeeded} succeeded, {len(remaining)} need Whisper")


if __name__ == "__main__":
    main()
