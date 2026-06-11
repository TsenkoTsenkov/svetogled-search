#!/usr/bin/env python3
"""One-off: transcribe the backlog of new episodes locally with whisper.cpp.

Uses the locally-installed whisper-cli and the high-quality large-v3-turbo
model (better than the 'small' model the CI workflow builds). Reads the
episode list from new_videos.json (produced by check_new_episodes.py) and
writes transcripts/<id>.json for each, skipping any already present.

yt-dlp uses cookies + the EJS challenge solver via YTDLP_COOKIES, mirroring
the workflow. Run from the repo root with YTDLP_COOKIES set to a cookies.txt.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
TRANSCRIPTS_DIR = REPO / "transcripts"
NEW_VIDEOS_FILE = REPO / "new_videos.json"
WHISPER_CLI = os.environ.get("WHISPER_CLI", "whisper-cli")
MODEL_PATH = os.environ.get(
    "WHISPER_MODEL", str(REPO / "models" / "ggml-large-v3-turbo.bin")
)
LANGUAGE = "bg"


def _ytdlp_args():
    args = ["--remote-components", "ejs:github"]
    cookies = os.environ.get("YTDLP_COOKIES", "")
    if cookies and Path(cookies).exists():
        args += ["--cookies", cookies]
    return args


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
            check=True, capture_output=True, text=True, timeout=900,
        )
        return Path(output_path).exists()
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        print(f"  yt-dlp error: {err[-400:]}" if err else "  yt-dlp failed")
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
                "-oj", "-of", json_prefix, "--no-prints",
            ],
            capture_output=True, text=True, timeout=7200,
        )
        json_file = Path(json_prefix + ".json")
        if json_file.exists():
            data = json.loads(json_file.read_text(encoding="utf-8"))
            json_file.unlink()
            return data
        return None
    except Exception as e:
        print(f"  whisper error: {type(e).__name__}: {e}")
        return None


def parse_whisper_result(whisper_data):
    snippets = []
    for segment in whisper_data.get("transcription", []):
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
    return {
        "snippets": snippets,
        "full_text": " ".join(s["text"] for s in snippets),
        "segment_count": len(snippets),
    }


def main():
    videos = json.loads(NEW_VIDEOS_FILE.read_text(encoding="utf-8"))
    print(f"Backlog: {len(videos)} episode(s). Model: {MODEL_PATH}")
    succeeded, skipped, failed = 0, 0, 0

    for i, video in enumerate(videos):
        vid, title = video["id"], video["title"]
        outfile = TRANSCRIPTS_DIR / f"{vid}.json"
        print(f"\n[{i+1}/{len(videos)}] {title} ({vid})")

        if outfile.exists():
            print("  already exists, skipping")
            skipped += 1
            continue

        wav_path = Path(tempfile.gettempdir()) / f"{vid}.wav"
        if not wav_path.exists():
            print("  downloading audio...")
            if not download_audio(vid, wav_path):
                print("  FAILED: audio download")
                failed += 1
                continue

        print("  transcribing (large-v3-turbo)...")
        result = transcribe_audio(wav_path)
        wav_path.unlink(missing_ok=True)
        if result is None:
            print("  FAILED: whisper error")
            failed += 1
            continue

        parsed = parse_whisper_result(result)
        outfile.write_text(json.dumps({
            "video_id": vid,
            "title": title,
            "source": "whisper-large-v3-turbo",
            "segment_count": parsed["segment_count"],
            "snippets": parsed["snippets"],
            "full_text": parsed["full_text"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  OK: {parsed['segment_count']} segments")
        succeeded += 1

    print(f"\nDone. {succeeded} transcribed, {skipped} skipped, {failed} failed.")
    return failed


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
