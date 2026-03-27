#!/usr/bin/env python3
"""
Parallel Whisper transcription for YouTube videos.
Runs multiple Whisper instances concurrently to speed up processing.

Usage:
    python transcribe_parallel.py          # Default 4 workers
    python transcribe_parallel.py -w 3     # Custom worker count
"""

import json
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "transcripts"
FAILED_FILE = BASE_DIR / "failed.json"
AUDIO_DIR = BASE_DIR / "audio_cache"
MODEL_PATH = BASE_DIR / "models" / "ggml-large-v3-turbo.bin"
WHISPER_CLI = "whisper-cli"
LANGUAGE = "bg"
NUM_WORKERS = 4


def download_audio(video_id, output_path):
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        subprocess.run(
            [
                "yt-dlp", "-x", "--audio-format", "wav",
                "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
                "-o", str(output_path),
                "--no-playlist", "--quiet", url,
            ],
            check=True, capture_output=True, text=True, timeout=300,
        )
        return Path(output_path).exists()
    except Exception:
        return False


def transcribe_audio(wav_path):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        json_prefix = tmp.name.replace(".json", "")

    try:
        subprocess.run(
            [
                WHISPER_CLI, "-m", str(MODEL_PATH),
                "-l", LANGUAGE, "-f", str(wav_path),
                "-oj", "-of", json_prefix,
                "--no-prints",
            ],
            capture_output=True, text=True, timeout=3600,
        )

        json_file = Path(json_prefix + ".json")
        if json_file.exists():
            data = json.loads(json_file.read_text(encoding="utf-8"))
            json_file.unlink()
            return data
        return None
    except Exception:
        return None


def parse_whisper_result(whisper_data):
    transcription = whisper_data.get("transcription", [])
    snippets = []
    for segment in transcription:
        text = segment.get("text", "").strip()
        if not text:
            continue
        offsets = segment.get("offsets", {})
        start_sec = offsets.get("from", 0) / 1000.0
        end_sec = offsets.get("to", 0) / 1000.0
        snippets.append({
            "text": text,
            "start": start_sec,
            "duration": round(end_sec - start_sec, 3),
        })
    full_text = " ".join(s["text"] for s in snippets)
    return {
        "snippets": snippets,
        "full_text": full_text,
        "segment_count": len(snippets),
    }


def process_single(args):
    """Process one video. Designed to be called by Pool.imap_unordered."""
    index, total, video = args
    vid = video["id"]
    title = video["title"]
    label = f"[{index}/{total}]"

    outfile = OUTPUT_DIR / f"{vid}.json"

    # Skip if already done with valid timestamps
    if outfile.exists():
        try:
            existing = json.loads(outfile.read_text(encoding="utf-8"))
            snippets = existing.get("snippets", [])
            if len(snippets) > 1 and snippets[1].get("start", 0) > 0:
                return {"status": "skipped", "id": vid}
        except Exception:
            pass

    print(f"{label} {title} ({vid})", flush=True)

    # Download
    wav_path = AUDIO_DIR / f"{vid}.wav"
    if not wav_path.exists():
        print(f"  {label} Downloading audio...", flush=True)
        if not download_audio(vid, wav_path):
            print(f"  {label} FAILED: audio download", flush=True)
            return {"status": "failed", "id": vid, "title": title, "error": "Audio download failed"}

    # Transcribe
    print(f"  {label} Transcribing...", flush=True)
    whisper_result = transcribe_audio(wav_path)

    if whisper_result is None:
        print(f"  {label} FAILED: Whisper error", flush=True)
        return {"status": "failed", "id": vid, "title": title, "error": "Whisper failed"}

    # Parse and save
    parsed = parse_whisper_result(whisper_result)
    data = {
        "video_id": vid,
        "title": title,
        "source": "whisper-large-v3-turbo",
        "segment_count": parsed["segment_count"],
        "snippets": parsed["snippets"],
        "full_text": parsed["full_text"],
    }
    outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {label} OK: {parsed['segment_count']} segments", flush=True)

    # Cleanup audio
    wav_path.unlink(missing_ok=True)

    return {"status": "ok", "id": vid, "title": title}


def rebuild_combined():
    combined_json = BASE_DIR / "transcripts_combined.json"
    full_text_file = BASE_DIR / "transcripts_full_text.txt"

    all_t = []
    for f in sorted(OUTPUT_DIR.glob("*.json")):
        all_t.append(json.loads(f.read_text(encoding="utf-8")))

    combined_json.write_text(json.dumps(all_t, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(full_text_file, "w", encoding="utf-8") as f:
        for t in all_t:
            f.write(f"{'=' * 60}\nVideo: {t['title']}\nID: {t['video_id']}\nSource: {t.get('source', '?')}\n{'=' * 60}\n\n{t['full_text']}\n\n\n")
    return len(all_t)


def main():
    num_workers = NUM_WORKERS
    if "-w" in sys.argv:
        num_workers = int(sys.argv[sys.argv.index("-w") + 1])

    OUTPUT_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)

    if not MODEL_PATH.exists():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        sys.exit(1)

    failed = json.loads(FAILED_FILE.read_text(encoding="utf-8"))
    needs_whisper = [
        v for v in failed
        if "disabled" in v.get("error", "").lower()
        or "blocking" in v.get("error", "").lower()
        or "bg (auto)" in v.get("error", "")
    ]

    total = len(needs_whisper)
    print(f"Videos needing Whisper: {total}")
    print(f"Workers: {num_workers}")
    print(f"", flush=True)

    # Build args list: (index, total, video)
    work = [(i + 1, total, v) for i, v in enumerate(needs_whisper)]

    stats = {"ok": 0, "failed": 0, "skipped": 0}
    failed_list = []

    try:
        with Pool(processes=num_workers) as pool:
            for result in pool.imap_unordered(process_single, work):
                stats[result["status"]] += 1
                if result["status"] == "failed":
                    failed_list.append(result)
                done = stats["ok"] + stats["failed"] + stats["skipped"]
                if done % 10 == 0:
                    print(f"\n--- Progress: {done}/{total} (OK: {stats['ok']}, Failed: {stats['failed']}, Skipped: {stats['skipped']}) ---\n", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted! Transcripts saved so far are safe. Run again to resume.")
        sys.exit(1)

    # Rebuild
    print("\nRebuilding combined files...")
    total_transcripts = rebuild_combined()

    print(f"\nSUMMARY")
    print(f"  Workers:     {num_workers}")
    print(f"  OK:          {stats['ok']}")
    print(f"  Failed:      {stats['failed']}")
    print(f"  Skipped:     {stats['skipped']}")
    print(f"  Total transcripts: {total_transcripts}")


if __name__ == "__main__":
    main()
