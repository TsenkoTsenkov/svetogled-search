#!/usr/bin/env python3
"""
Extract Bulgarian transcripts from a YouTube playlist.

Usage:
    python extract_transcripts.py

Outputs:
    - transcripts/          Individual JSON files per video
    - transcripts_combined.json   All transcripts in one file
    - transcripts_full_text.txt   Plain text of all transcripts (for processing)

Requires: pip install yt-dlp youtube-transcript-api
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLvX0cuPYCospMRKzBKtS5xYPFpsuEQwDQ"
OUTPUT_DIR = Path(__file__).parent / "transcripts"
COMBINED_JSON = Path(__file__).parent / "transcripts_combined.json"
FULL_TEXT_FILE = Path(__file__).parent / "transcripts_full_text.txt"
PROGRESS_FILE = Path(__file__).parent / "progress.json"
DELAY_SECONDS = 3.0  # Delay between requests to avoid rate limiting
BATCH_SIZE = 50       # Pause longer every N videos
BATCH_PAUSE = 30      # Seconds to pause between batches


def get_playlist_videos(playlist_url: str) -> list[dict]:
    """Extract all video IDs and titles from a playlist using yt-dlp."""
    import yt_dlp

    videos = []
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "force_generic_extractor": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

        if "entries" not in info:
            print("ERROR: Could not extract playlist entries.")
            sys.exit(1)

        for entry in info["entries"]:
            if entry is None:
                continue
            videos.append({
                "id": entry.get("id", ""),
                "title": entry.get("title", "Unknown"),
                "url": entry.get("url", f"https://www.youtube.com/watch?v={entry.get('id', '')}"),
            })

    return videos


def load_progress() -> set:
    """Load set of already-processed video IDs."""
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        return set(data.get("completed", []))
    return set()


def save_progress(completed: set):
    """Save progress to disk."""
    PROGRESS_FILE.write_text(
        json.dumps({"completed": sorted(completed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_transcript(video_id: str) -> dict | None:
    """Fetch Bulgarian transcript for a single video using youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)
    except Exception as e:
        return {"error": f"Could not list transcripts: {e}"}

    # Try to find Bulgarian transcript
    transcript = None
    source = None

    # 1. Try manual Bulgarian transcript
    for t in transcript_list:
        if t.language_code == "bg" and not t.is_generated:
            try:
                transcript = t.fetch()
                source = "manual"
                break
            except Exception:
                pass

    # 2. Try auto-generated Bulgarian
    if transcript is None:
        for t in transcript_list:
            if t.language_code == "bg" and t.is_generated:
                try:
                    transcript = t.fetch()
                    source = "auto-generated"
                    break
                except Exception:
                    pass

    # 3. Try any transcript that starts with 'bg'
    if transcript is None:
        for t in transcript_list:
            if t.language_code.startswith("bg"):
                try:
                    transcript = t.fetch()
                    source = f"auto ({t.language_code})"
                    break
                except Exception:
                    pass

    # 4. List available languages for debugging
    if transcript is None:
        available = [f"{t.language_code} ({'auto' if t.is_generated else 'manual'})"
                     for t in transcript_list]
        return {"error": f"No Bulgarian transcript. Available: {', '.join(available)}"}

    snippets = [
        {
            "text": snippet.text,
            "start": snippet.start,
            "duration": snippet.duration,
        }
        for snippet in transcript
    ]

    full_text = " ".join(s.text for s in transcript)

    return {
        "snippets": snippets,
        "full_text": full_text,
        "source": source,
        "segment_count": len(snippets),
    }


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ── Phase 1: Get all video IDs ──
    print("=" * 60)
    print("Phase 1: Extracting video list from playlist...")
    print("=" * 60)

    videos = get_playlist_videos(PLAYLIST_URL)
    print(f"Found {len(videos)} videos in playlist.\n")

    # ── Phase 2: Fetch transcripts ──
    print("=" * 60)
    print("Phase 2: Fetching Bulgarian transcripts...")
    print("=" * 60)

    completed = load_progress()
    skipped = 0
    succeeded = 0
    failed_list = []

    for i, video in enumerate(videos):
        vid = video["id"]
        title = video["title"]

        # Skip already processed
        if vid in completed:
            skipped += 1
            continue

        print(f"\n[{i + 1}/{len(videos)}] {title}")
        print(f"  Video ID: {vid}")

        result = fetch_transcript(vid)

        if result is None or "error" in result:
            error_msg = result.get("error", "Unknown error") if result else "Unknown error"
            print(f"  FAILED: {error_msg}")
            failed_list.append({"id": vid, "title": title, "error": error_msg})
        else:
            # Save individual transcript
            data = {
                "video_id": vid,
                "title": title,
                "source": result["source"],
                "segment_count": result["segment_count"],
                "snippets": result["snippets"],
                "full_text": result["full_text"],
            }

            outfile = OUTPUT_DIR / f"{vid}.json"
            outfile.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  OK: {result['segment_count']} segments ({result['source']})")
            succeeded += 1

        completed.add(vid)
        save_progress(completed)

        # Rate limiting
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < len(videos):
            print(f"\n  ** Batch pause ({BATCH_PAUSE}s) to avoid rate limiting **")
            time.sleep(BATCH_PAUSE)
        else:
            time.sleep(DELAY_SECONDS)

    # ── Phase 3: Combine all transcripts ──
    print("\n" + "=" * 60)
    print("Phase 3: Combining transcripts...")
    print("=" * 60)

    all_transcripts = []
    for video in videos:
        vid = video["id"]
        fpath = OUTPUT_DIR / f"{vid}.json"
        if fpath.exists():
            data = json.loads(fpath.read_text(encoding="utf-8"))
            all_transcripts.append(data)

    # Save combined JSON
    COMBINED_JSON.write_text(
        json.dumps(all_transcripts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved combined JSON: {COMBINED_JSON} ({len(all_transcripts)} videos)")

    # Save plain text version (great for further processing)
    with open(FULL_TEXT_FILE, "w", encoding="utf-8") as f:
        for t in all_transcripts:
            f.write(f"{'=' * 60}\n")
            f.write(f"Video: {t['title']}\n")
            f.write(f"ID: {t['video_id']}\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(t["full_text"])
            f.write("\n\n\n")

    print(f"Saved full text: {FULL_TEXT_FILE}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total videos:    {len(videos)}")
    print(f"  Skipped (done):  {skipped}")
    print(f"  Succeeded:       {succeeded}")
    print(f"  Failed:          {len(failed_list)}")
    print(f"  Output dir:      {OUTPUT_DIR}")
    print(f"  Combined JSON:   {COMBINED_JSON}")
    print(f"  Full text:       {FULL_TEXT_FILE}")

    if failed_list:
        failed_file = Path(__file__).parent / "failed.json"
        failed_file.write_text(
            json.dumps(failed_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Failed list:     {failed_file}")
        print("\nFailed videos:")
        for f_item in failed_list:
            print(f"  - {f_item['title']}: {f_item['error']}")


if __name__ == "__main__":
    main()
