#!/usr/bin/env python3
"""Transcribe remaining videos with Whisper (for GitHub Actions)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

TRANSCRIPTS_DIR = Path("transcripts")
REMAINING_FILE = Path("remaining_videos.json")
WHISPER_CLI = "./whisper-cli"
MODEL_PATH = "./ggml-small.bin"
LANGUAGE = "bg"

# Optional cookie file for yt-dlp (needed on datacenter IPs like GitHub Actions,
# where YouTube blocks anonymous downloads). Set YTDLP_COOKIES to a Netscape
# cookies.txt path; ignored when unset (e.g. local runs from a residential IP).
COOKIES_FILE = os.environ.get("YTDLP_COOKIES", "")


def _ytdlp_args():
    """Common yt-dlp args: cookies (when provided) + the EJS challenge solver.

    YouTube now gates audio formats behind a JS ("nsig") challenge. yt-dlp
    solves it with a JS runtime (node/deno, preinstalled on GitHub runners)
    via the downloadable EJS solver; without this, only image formats are
    offered and audio extraction fails with "Requested format is not available".
    """
    args = ["--remote-components", "ejs:github"]
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        args += ["--cookies", COOKIES_FILE]
    return args


def get_upload_date(video_id):
    """Fetch the YouTube upload date (YYYY-MM-DD) via a metadata-only yt-dlp
    call. Without this, Whisper-transcribed episodes have no date and sink to
    the bottom of the homepage's 'Последни беседи' list. Returns "" on failure
    (the site tolerates a missing date and falls back to episode_number)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        out = subprocess.run(
            ["yt-dlp", *_ytdlp_args(), "--no-playlist", "--skip-download",
             "--print", "%(upload_date)s", url],
            check=True, capture_output=True, text=True, timeout=120,
        ).stdout.strip()
        # yt-dlp prints upload_date as YYYYMMDD; convert to YYYY-MM-DD.
        if len(out) == 8 and out.isdigit():
            return f"{out[:4]}-{out[4:6]}-{out[6:]}"
    except Exception as e:  # noqa: BLE001
        print(f"  upload_date lookup failed: {type(e).__name__}")
    return ""


def download_audio(video_id, output_path):
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        subprocess.run(
            [
                "yt-dlp", "-x", "--audio-format", "wav",
                *_ytdlp_args(),
                "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
                "-o", str(output_path),
                "--no-playlist", "--quiet", url,
            ],
            check=True, capture_output=True, text=True, timeout=600,
        )
        return Path(output_path).exists()
    except subprocess.CalledProcessError as e:
        # Surface the real reason instead of silently skipping. yt-dlp writes
        # the useful diagnostics (bot-check, 403, format errors) to stderr.
        err = (e.stderr or e.stdout or "").strip()
        print(f"  yt-dlp error: {err[-400:]}" if err else "  yt-dlp failed with no output")
        return False
    except subprocess.TimeoutExpired:
        print("  yt-dlp timed out after 600s")
        return False
    except Exception as e:
        print(f"  download error: {type(e).__name__}: {e}")
        return False


def transcribe_audio(wav_path):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        json_prefix = tmp.name.replace(".json", "")

    try:
        subprocess.run(
            [
                WHISPER_CLI, "-m", MODEL_PATH,
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


def main():
    if not REMAINING_FILE.exists():
        print("No remaining_videos.json — nothing to transcribe")
        return

    videos = json.loads(REMAINING_FILE.read_text(encoding="utf-8"))
    if not videos:
        print("No remaining videos")
        return

    # CPU Whisper is slow (~real-time), so transcribing many full talks in one
    # run blows past GitHub's job timeout. Cap each run to WHISPER_MAX_PER_RUN
    # episodes; the workflow re-triggers itself until the backlog is empty.
    max_per_run = int(os.environ.get("WHISPER_MAX_PER_RUN", "0") or "0")
    total = len(videos)
    if max_per_run > 0 and total > max_per_run:
        videos = videos[:max_per_run]
        print(f"Capping this run to {max_per_run} of {total} videos "
              f"({total - max_per_run} will be picked up by the next run).")

    # Check whisper is available
    if not Path(WHISPER_CLI).exists():
        print(f"Whisper CLI not found at {WHISPER_CLI}, skipping transcription")
        return

    if not Path(MODEL_PATH).exists():
        print(f"Model not found at {MODEL_PATH}, skipping transcription")
        return

    print(f"Transcribing {len(videos)} videos with Whisper...")
    succeeded = 0
    failed = 0

    for i, video in enumerate(videos):
        vid = video["id"]
        title = video["title"]
        print(f"\n[{i+1}/{len(videos)}] {title} ({vid})")

        # Download audio
        wav_path = Path(f"/tmp/{vid}.wav")
        if not wav_path.exists():
            print(f"  Downloading audio...")
            if not download_audio(vid, wav_path):
                print(f"  FAILED: audio download")
                failed += 1
                continue

        # Transcribe
        print(f"  Transcribing...")
        result = transcribe_audio(wav_path)

        if result is None:
            print(f"  FAILED: whisper error")
            failed += 1
            wav_path.unlink(missing_ok=True)
            continue

        # Parse and save
        parsed = parse_whisper_result(result)
        data = {
            "video_id": vid,
            "title": title,
            "upload_date": get_upload_date(vid),
            "source": "whisper-small",
            "segment_count": parsed["segment_count"],
            "snippets": parsed["snippets"],
            "full_text": parsed["full_text"],
        }

        outfile = TRANSCRIPTS_DIR / f"{vid}.json"
        outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  OK: {parsed['segment_count']} segments")
        succeeded += 1

        # Cleanup
        wav_path.unlink(missing_ok=True)

    print(f"\nWhisper: {succeeded} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
