#!/usr/bin/env python3
"""
Retry fetching transcripts for videos that failed due to rate limiting.
Reads failed.json, retries only those with 'bg (auto)' available.
Uses longer delays to avoid rate limiting.
"""

import json
import time
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "transcripts"
FAILED_FILE = BASE_DIR / "failed.json"
COMBINED_JSON = BASE_DIR / "transcripts_combined.json"
FULL_TEXT_FILE = BASE_DIR / "transcripts_full_text.txt"
DELAY_SECONDS = 5.0       # Longer delay
BATCH_SIZE = 20            # Smaller batches
BATCH_PAUSE = 60           # Longer pause between batches


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    failed = json.loads(FAILED_FILE.read_text(encoding="utf-8"))
    retryable = [v for v in failed if "bg (auto)" in v.get("error", "")]
    print(f"Retryable videos (had bg auto but failed): {len(retryable)}")

    api = YouTubeTranscriptApi()
    succeeded = 0
    still_failed = []
    # Keep non-retryable failures
    permanent_failures = [v for v in failed if "bg (auto)" not in v.get("error", "")]

    for i, video in enumerate(retryable):
        vid = video["id"]
        title = video["title"]

        # Skip if already downloaded (from a previous retry)
        if (OUTPUT_DIR / f"{vid}.json").exists():
            print(f"[{i+1}/{len(retryable)}] {title} — already done, skipping")
            succeeded += 1
            continue

        print(f"[{i+1}/{len(retryable)}] {title} ({vid})")

        try:
            transcript_list = api.list(vid)
            transcript = None
            for t in transcript_list:
                if t.language_code.startswith("bg"):
                    transcript = t.fetch()
                    break

            if transcript is None:
                print(f"  FAILED: Still no Bulgarian transcript")
                still_failed.append({"id": vid, "title": title, "error": "No Bulgarian transcript on retry"})
                continue

            snippets = [
                {"text": s.text, "start": s.start, "duration": s.duration}
                for s in transcript
            ]
            full_text = " ".join(s.text for s in transcript)

            data = {
                "video_id": vid,
                "title": title,
                "source": "auto-generated",
                "segment_count": len(snippets),
                "snippets": snippets,
                "full_text": full_text,
            }

            outfile = OUTPUT_DIR / f"{vid}.json"
            outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  OK: {len(snippets)} segments")
            succeeded += 1

        except Exception as e:
            err_str = str(e)
            short_err = err_str[:200] if len(err_str) > 200 else err_str
            print(f"  FAILED: {short_err}")
            still_failed.append({"id": vid, "title": title, "error": short_err})

        # Rate limiting
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < len(retryable):
            print(f"\n  ** Batch pause ({BATCH_PAUSE}s) **\n")
            time.sleep(BATCH_PAUSE)
        else:
            time.sleep(DELAY_SECONDS)

    # Update failed.json
    all_failed = permanent_failures + still_failed
    FAILED_FILE.write_text(json.dumps(all_failed, ensure_ascii=False, indent=2), encoding="utf-8")

    # Rebuild combined outputs
    print("\nRebuilding combined files...")

    # Read playlist order from progress
    all_transcripts = []
    for f in sorted(OUTPUT_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        all_transcripts.append(data)

    COMBINED_JSON.write_text(
        json.dumps(all_transcripts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with open(FULL_TEXT_FILE, "w", encoding="utf-8") as f:
        for t in all_transcripts:
            f.write(f"{'=' * 60}\n")
            f.write(f"Video: {t['title']}\n")
            f.write(f"ID: {t['video_id']}\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(t["full_text"])
            f.write("\n\n\n")

    print(f"\nRETRY SUMMARY")
    print(f"  Retried:     {len(retryable)}")
    print(f"  Succeeded:   {succeeded}")
    print(f"  Still failed:{len(still_failed)}")
    print(f"  Total transcripts now: {len(all_transcripts)}")
    print(f"  Combined JSON: {COMBINED_JSON}")
    print(f"  Full text:     {FULL_TEXT_FILE}")


if __name__ == "__main__":
    main()
