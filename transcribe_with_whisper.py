#!/usr/bin/env python3
"""
Download audio and transcribe videos that have no YouTube subtitles.
Uses yt-dlp for audio download + whisper.cpp for transcription.

Usage:
    python transcribe_with_whisper.py

Requires:
    - yt-dlp (pip install yt-dlp)
    - whisper-cpp (brew install whisper-cpp)
    - ffmpeg (brew install ffmpeg)
    - Model file: models/ggml-large-v3-turbo.bin
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "transcripts"
FAILED_FILE = BASE_DIR / "failed.json"
AUDIO_DIR = BASE_DIR / "audio_cache"
WHISPER_PROGRESS_FILE = BASE_DIR / "whisper_progress.json"
MODEL_PATH = BASE_DIR / "models" / "ggml-large-v3-turbo.bin"
WHISPER_CLI = "whisper-cli"
LANGUAGE = "bg"


def load_whisper_progress() -> set:
    if WHISPER_PROGRESS_FILE.exists():
        data = json.loads(WHISPER_PROGRESS_FILE.read_text(encoding="utf-8"))
        return set(data.get("completed", []))
    return set()


def save_whisper_progress(completed: set):
    WHISPER_PROGRESS_FILE.write_text(
        json.dumps({"completed": sorted(completed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def download_audio(video_id: str, output_path: Path) -> bool:
    """Download audio as 16kHz mono WAV (required by whisper.cpp)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        subprocess.run(
            [
                "yt-dlp",
                "-x",                          # Extract audio
                "--audio-format", "wav",        # Convert to WAV
                "--postprocessor-args",
                "ffmpeg:-ar 16000 -ac 1",       # 16kHz mono (whisper requirement)
                "-o", str(output_path),
                "--no-playlist",
                "--quiet",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return output_path.exists()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"    Audio download failed: {e}")
        return False


def transcribe_audio(wav_path: Path) -> dict | None:
    """Transcribe WAV file using whisper-cli, return structured result."""
    # Output JSON to a temp file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        json_output = tmp.name

    try:
        result = subprocess.run(
            [
                WHISPER_CLI,
                "-m", str(MODEL_PATH),
                "-l", LANGUAGE,
                "-f", str(wav_path),
                "-oj",                          # Output JSON
                "-of", json_output.replace(".json", ""),  # Output file prefix
                "--no-prints",                  # Suppress progress to stderr
            ],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min max per video
        )

        json_file = Path(json_output)
        if not json_file.exists():
            # whisper-cli might append .json
            alt = Path(json_output.replace(".json", "") + ".json")
            if alt.exists():
                json_file = alt

        if json_file.exists():
            data = json.loads(json_file.read_text(encoding="utf-8"))
            json_file.unlink()
            return data
        else:
            print(f"    Whisper output file not found. stderr: {result.stderr[:500]}")
            return None

    except subprocess.TimeoutExpired:
        print(f"    Whisper timed out (30min limit)")
        return None
    except Exception as e:
        print(f"    Whisper error: {e}")
        return None


def parse_whisper_result(whisper_data: dict) -> dict:
    """Convert whisper.cpp JSON output to our standard format."""
    transcription = whisper_data.get("transcription", [])

    snippets = []
    for segment in transcription:
        text = segment.get("text", "").strip()
        if not text:
            continue

        # Use offsets (milliseconds) — more reliable than parsing timestamp strings
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


def timestamp_to_seconds(ts: str) -> float:
    """Convert 'HH:MM:SS.mmm' to seconds."""
    try:
        parts = ts.split(":")
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return 0.0


def rebuild_combined_outputs():
    """Rebuild the combined JSON and text files from all individual transcripts."""
    combined_json = BASE_DIR / "transcripts_combined.json"
    full_text_file = BASE_DIR / "transcripts_full_text.txt"

    all_transcripts = []
    for f in sorted(OUTPUT_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        all_transcripts.append(data)

    combined_json.write_text(
        json.dumps(all_transcripts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with open(full_text_file, "w", encoding="utf-8") as f:
        for t in all_transcripts:
            f.write(f"{'=' * 60}\n")
            f.write(f"Video: {t['title']}\n")
            f.write(f"ID: {t['video_id']}\n")
            source = t.get("source", "unknown")
            f.write(f"Source: {source}\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(t["full_text"])
            f.write("\n\n\n")

    return len(all_transcripts)


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)

    # Check prerequisites
    if not MODEL_PATH.exists():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        print("Download it with:")
        print(f'  curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin" -o "{MODEL_PATH}"')
        sys.exit(1)

    # Load failed videos that need whisper transcription
    if not FAILED_FILE.exists():
        print("No failed.json found. Run extract_transcripts.py first.")
        sys.exit(1)

    failed = json.loads(FAILED_FILE.read_text(encoding="utf-8"))

    # Videos with subtitles disabled OR rate-limited (bg auto available but blocked)
    needs_whisper = [
        v for v in failed
        if "disabled" in v.get("error", "").lower()
        or "blocking" in v.get("error", "").lower()
        or "bg (auto)" in v.get("error", "")
    ]
    print(f"Videos needing Whisper transcription: {len(needs_whisper)}")

    completed = load_whisper_progress()
    succeeded = 0
    new_failures = []
    # Keep only truly unrecoverable failures (private videos etc)
    needs_whisper_ids = {v["id"] for v in needs_whisper}
    other_failures = [v for v in failed if v["id"] not in needs_whisper_ids]

    for i, video in enumerate(needs_whisper):
        vid = video["id"]
        title = video["title"]

        if vid in completed:
            print(f"[{i+1}/{len(needs_whisper)}] {title} — already done")
            succeeded += 1
            continue

        print(f"\n[{i+1}/{len(needs_whisper)}] {title} ({vid})")

        # Step 1: Download audio
        wav_path = AUDIO_DIR / f"{vid}.wav"
        if not wav_path.exists():
            print(f"  Downloading audio...")
            if not download_audio(vid, wav_path):
                new_failures.append({"id": vid, "title": title, "error": "Audio download failed"})
                completed.add(vid)
                save_whisper_progress(completed)
                continue
        else:
            print(f"  Audio already cached")

        # Step 2: Transcribe with Whisper
        print(f"  Transcribing with Whisper (this may take a few minutes)...")
        whisper_result = transcribe_audio(wav_path)

        if whisper_result is None:
            new_failures.append({"id": vid, "title": title, "error": "Whisper transcription failed"})
            completed.add(vid)
            save_whisper_progress(completed)
            continue

        # Step 3: Parse and save
        parsed = parse_whisper_result(whisper_result)

        data = {
            "video_id": vid,
            "title": title,
            "source": "whisper-large-v3-turbo",
            "segment_count": parsed["segment_count"],
            "snippets": parsed["snippets"],
            "full_text": parsed["full_text"],
        }

        outfile = OUTPUT_DIR / f"{vid}.json"
        outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  OK: {parsed['segment_count']} segments")
        succeeded += 1

        completed.add(vid)
        save_whisper_progress(completed)

        # Delete audio to save disk space
        wav_path.unlink(missing_ok=True)

    # Update failed.json with remaining failures
    all_still_failed = other_failures + new_failures
    FAILED_FILE.write_text(
        json.dumps(all_still_failed, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Rebuild combined outputs
    print("\nRebuilding combined files...")
    total = rebuild_combined_outputs()

    print(f"\nWHISPER SUMMARY")
    print(f"  Needed Whisper:   {len(needs_whisper)}")
    print(f"  Succeeded:        {succeeded}")
    print(f"  Failed:           {len(new_failures)}")
    print(f"  Total transcripts: {total}")
    print(f"  Audio cache:      {AUDIO_DIR}")

    if new_failures:
        print("\nStill failed:")
        for f in new_failures:
            print(f"  - {f['title']}: {f['error']}")


if __name__ == "__main__":
    main()
