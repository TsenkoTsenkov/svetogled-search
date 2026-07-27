#!/usr/bin/env python3
"""
Режим на редакция — a local editor for the transcripts.

    python3 redaction_app.py            # http://127.0.0.1:8090
    python3 redaction_app.py --port 9000 --no-browser

What it is for: correcting the text of a беседа without touching a single
timestamp. The editor shows the transcript as paragraphs; you edit prose,
and redaction_align.py puts the words back on their original clock, so every
deep link into YouTube keeps pointing where it did.

The flow end to end:

    edit paragraphs → save a draft (local, git-ignored)
                    → review the word-level diff
                    → publish: writes transcripts/<id>.json, commits, pushes

Publishing to main is what starts the pipeline: .github/workflows/deploy.yml
watches transcripts/**, so the push rebuilds the site and re-indexes
Meilisearch, and regenerate-themes.yml refreshes themes.json. Publishing to a
branch instead opens the usual pull-request path — the pipeline runs when it
lands on main.

Bound to 127.0.0.1: this process can commit and push to the repository, so it
is deliberately not something the network can reach. The public site cannot
edit anything; it can only *open* this editor (see the "Редакция" affordance
in index.html), which is why editing on the live site would need real
accounts and auth first.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import redaction_align as align

ROOT = Path(__file__).resolve().parent
TRANSCRIPTS_DIR = ROOT / "transcripts"
DRAFTS_DIR = ROOT / ".redaction-drafts"
EDITOR_HTML = ROOT / "redaction.html"

DEFAULT_PORT = int(os.environ.get("REDACTION_PORT", 8090))
DEFAULT_HOST = os.environ.get("REDACTION_HOST", "127.0.0.1")
# Branch a "direct" publish pushes to; the deploy pipeline watches main.
PUBLISH_BRANCH = os.environ.get("REDACTION_BRANCH", "main")

# Origins allowed to ask "is the editor running?" — the live site and any
# local instance. Only /api/ping answers cross-origin; everything that reads
# or writes is same-origin only, so a random page cannot drive the editor.
ALLOWED_ORIGINS = {
    "https://svetogled-arhiv.com",
    "https://www.svetogled-arhiv.com",
}
_LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


# ── git ──────────────────────────────────────────────────────────────────

def git(*args, check=False):
    """Run a git command in the repo; returns (code, stdout, stderr)."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} се провали:\n{proc.stderr.strip()}"
        )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_available():
    return (ROOT / ".git").exists() and git("rev-parse", "--git-dir")[0] == 0


def current_branch():
    code, out, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else ""


def remote_url():
    code, out, _ = git("remote", "get-url", "origin")
    return out if code == 0 else ""


def github_slug():
    """owner/repo from the origin URL, for building commit / PR links.

    Falls back to the last two path segments, so a remote reached through a
    proxy (…/git/owner/repo) still yields usable github.com links — the
    project's origin is GitHub either way.
    """
    url = remote_url()
    if not url:
        return ""
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    parts = [p for p in re.sub(r"\.git/?$", "", url).split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else ""


# ── transcripts & drafts ─────────────────────────────────────────────────

def transcript_path(video_id):
    if not re.match(r"^[\w-]+$", video_id or ""):
        raise ValueError("Невалиден идентификатор на епизод.")
    path = TRANSCRIPTS_DIR / f"{video_id}.json"
    if path.parent != TRANSCRIPTS_DIR:
        raise ValueError("Невалиден път.")
    return path


def load_transcript(video_id):
    path = transcript_path(video_id)
    if not path.exists():
        raise ValueError(f"Няма транскрипт за {video_id}.")
    return json.loads(path.read_text(encoding="utf-8"))


def draft_path(video_id):
    return DRAFTS_DIR / f"{transcript_path(video_id).stem}.json"


def load_draft(video_id):
    path = draft_path(video_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_draft(video_id, edits):
    DRAFTS_DIR.mkdir(exist_ok=True)
    payload = {
        "video_id": video_id,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "edits": edits,
    }
    draft_path(video_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def list_episodes():
    """Every episode, newest беседа first, with draft state."""
    drafts = {p.stem for p in DRAFTS_DIR.glob("*.json")} if DRAFTS_DIR.exists() else set()
    episodes = []
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        episodes.append(
            {
                "video_id": data.get("video_id", f.stem),
                "title": data.get("title", f.stem),
                "episode_number": data.get("episode_number", 0),
                "upload_date": data.get("upload_date", ""),
                "segment_count": data.get("segment_count", len(data.get("snippets", []))),
                "source": data.get("source", ""),
                "has_draft": f.stem in drafts,
            }
        )
    episodes.sort(key=lambda e: (-(e["episode_number"] or 0), e["title"]))
    return episodes


def episode_payload(video_id):
    data = load_transcript(video_id)
    paragraphs = align.iter_paragraphs(data.get("snippets", []))
    draft = load_draft(video_id)
    return {
        "video_id": data.get("video_id", video_id),
        "title": data.get("title", video_id),
        "episode_number": data.get("episode_number", 0),
        "upload_date": data.get("upload_date", ""),
        "source": data.get("source", ""),
        "segment_count": len(data.get("snippets", [])),
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "site_url": f"https://svetogled-arhiv.com/episode/{video_id}",
        "paragraphs": paragraphs,
        "draft": draft,
    }


def _normalize_edits(payload):
    edits = payload.get("edits")
    if not isinstance(edits, list):
        raise ValueError("Липсват промени.")
    out = []
    for e in edits:
        if not isinstance(e, dict):
            raise ValueError("Невалидна промяна.")
        out.append({"index": int(e.get("index")), "text": str(e.get("text", ""))})
    return out


def preview(video_id, edits):
    """What publishing would change: per-paragraph word diff + totals."""
    data = load_transcript(video_id)
    paragraphs = {p["index"]: p for p in align.iter_paragraphs(data.get("snippets", []))}
    new_data, summary = align.apply_edits(data, edits)
    diffs = []
    for edit in sorted(edits, key=lambda e: e["index"]):
        para = paragraphs.get(edit["index"])
        if para is None:
            continue
        new_text = re.sub(r"\s+", " ", edit["text"]).strip()
        if new_text == para["text"]:
            continue
        diffs.append(
            {
                "index": para["index"],
                "start": para["start"],
                "diff": align.word_diff(para["text"], new_text),
            }
        )
    # How much of full_text moves beyond the edited paragraphs — full_text
    # carries corrections of its own, so this is worth showing.
    summary["full_text_before"] = len(data.get("full_text", "").split())
    summary["full_text_after"] = len(new_data.get("full_text", "").split())
    return {"summary": summary, "diffs": diffs}


def publish(video_id, edits, message=None, mode="direct", push=True):
    """Write the edited transcript and put it into git.

    mode "direct": commit on the current branch and push it (main → the
    deploy pipeline rebuilds and re-indexes the episode).
    mode "branch": commit on a fresh redakcia/… branch, push it, and hand
    back a link for opening the pull request.
    """
    data = load_transcript(video_id)
    new_data, summary = align.apply_edits(data, edits)
    if not summary["paragraphs_changed"]:
        raise ValueError("Няма променени абзаци.")

    path = transcript_path(video_id)
    rel = path.relative_to(ROOT).as_posix()
    serialized = json.dumps(new_data, ensure_ascii=False)
    json.loads(serialized)  # never write a file we cannot read back

    steps = []
    result = {
        "ok": True,
        "summary": summary,
        "file": rel,
        "mode": mode,
        "steps": steps,
        "committed": False,
        "pushed": False,
    }

    if not git_available():
        path.write_text(serialized, encoding="utf-8")
        steps.append({"step": "write", "ok": True, "detail": rel})
        result["warning"] = (
            "Файлът е записан, но папката не е git хранилище — няма commit."
        )
        return result

    title = new_data.get("title", video_id)
    commit_message = message or f"Редакция на текста: {title}"
    original_branch = current_branch()
    branch = original_branch

    if mode == "branch":
        # A YouTube id may start with "-", which git would read as a flag.
        safe_id = re.sub(r"[^\w-]", "-", video_id)
        branch = "redakcia/" + (safe_id if not safe_id.startswith("-") else "id" + safe_id)
        code, _, err = git("switch", "-c", branch)
        if code != 0:  # branch exists already — reuse it
            code, _, err = git("switch", branch)
            if code != 0:
                raise RuntimeError(f"Не може да се създаде клон {branch}: {err}")
        steps.append({"step": "branch", "ok": True, "detail": branch})

    try:
        path.write_text(serialized, encoding="utf-8")
        steps.append({"step": "write", "ok": True, "detail": rel})

        code, _, err = git("add", "--", rel)
        if code != 0:
            raise RuntimeError(f"git add се провали: {err}")
        code, out, err = git("commit", "-m", commit_message, "--", rel)
        if code != 0:
            raise RuntimeError(f"git commit се провали: {err or out}")
        result["committed"] = True
        code, sha, _ = git("rev-parse", "HEAD")
        result["commit"] = sha[:10] if code == 0 else ""
        result["branch"] = branch
        result["message"] = commit_message
        steps.append({"step": "commit", "ok": True, "detail": result["commit"]})

        if push:
            target = PUBLISH_BRANCH if mode == "direct" else branch
            args = (
                ["push", "-u", "origin", branch]
                if mode == "branch"
                else ["push", "origin", f"HEAD:{target}"]
            )
            code, out, err = git(*args)
            if code != 0:
                result["ok"] = False
                result["error"] = (
                    "Промяната е записана локално (commit "
                    + result.get("commit", "")
                    + "), но push се провали: "
                    + (err or out)
                )
                steps.append({"step": "push", "ok": False, "detail": err or out})
                return result
            result["pushed"] = True
            result["push_target"] = target
            steps.append({"step": "push", "ok": True, "detail": target})

            slug = github_slug()
            if slug:
                if mode == "branch":
                    result["pull_request_url"] = (
                        f"https://github.com/{slug}/compare/{PUBLISH_BRANCH}...{branch}?expand=1"
                    )
                    result["pipeline"] = (
                        "Клонът е качен. Пайплайнът ще пусне след сливане в "
                        f"{PUBLISH_BRANCH}."
                    )
                else:
                    result["commit_url"] = (
                        f"https://github.com/{slug}/commit/{result.get('commit', '')}"
                    )
                    result["actions_url"] = f"https://github.com/{slug}/actions"
                    result["pipeline"] = (
                        "Пуснато в " + target + " — deploy.yml преизгражда сайта "
                        "и преиндексира Meilisearch, а regenerate-themes.yml "
                        "обновява картата на темите."
                    )
    finally:
        if mode == "branch" and original_branch and current_branch() != original_branch:
            git("switch", original_branch)
            steps.append({"step": "restore-branch", "ok": True, "detail": original_branch})

    # The draft has become history.
    if result["committed"]:
        try:
            draft_path(video_id).unlink(missing_ok=True)
        except OSError:
            pass
    return result


# ── HTTP ─────────────────────────────────────────────────────────────────

class RedactionHandler(SimpleHTTPRequestHandler):
    server_version = "SvetogledRedaction/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- helpers --
    def _cors(self, ping_only=False):
        origin = self.headers.get("Origin")
        if not origin:
            return
        if origin in ALLOWED_ORIGINS or _LOCAL_ORIGIN.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            if not ping_only:
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _json(self, data, status=200, ping=False):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors(ping_only=ping)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > 8 * 1024 * 1024:
            raise ValueError("Невалидна заявка.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Невалиден JSON.")
        if not isinstance(payload, dict):
            raise ValueError("Невалиден JSON.")
        return payload

    def _same_origin_only(self):
        """Writes must come from the editor page itself, not another site."""
        origin = self.headers.get("Origin")
        if origin and not _LOCAL_ORIGIN.match(origin):
            self._json({"error": "Забранено от друг сайт."}, 403)
            return False
        return True

    # -- routes --
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path

        if path in ("/", "/index.html", "/redakcia"):
            if not EDITOR_HTML.exists():
                self._json({"error": "redaction.html липсва."}, 500)
                return
            body = EDITOR_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/ping":
            self._json(
                {
                    "ok": True,
                    "app": "svetogled-redaction",
                    "episodes": len(list(TRANSCRIPTS_DIR.glob("*.json"))),
                    "repo": github_slug(),
                    "branch": current_branch(),
                    "publish_branch": PUBLISH_BRANCH,
                    "git": git_available(),
                },
                ping=True,
            )
            return

        if path == "/api/episodes":
            self._json({"episodes": list_episodes()})
            return

        if path == "/api/episode":
            try:
                self._json(episode_payload(params.get("id", [""])[0]))
            except ValueError as e:
                self._json({"error": str(e)}, 404)
            return

        if path.startswith("/static/"):
            self._serve_static(path)
            return

        self._json({"error": "Няма такъв адрес."}, 404)

    def _serve_static(self, path):
        """Fonts and images, so the editor looks like the site offline."""
        safe = path.replace("..", "").lstrip("/")
        fpath = ROOT / safe
        if not fpath.is_file():
            self._json({"error": "Няма такъв файл."}, 404)
            return
        ctype = {
            ".woff2": "font/woff2",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(fpath.suffix.lower(), "application/octet-stream")
        body = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._same_origin_only():
            return
        try:
            payload = self._body()
            video_id = str(payload.get("id", ""))

            if path == "/api/draft":
                edits = _normalize_edits(payload)
                transcript_path(video_id)  # validates the id
                self._json({"ok": True, "draft": save_draft(video_id, edits)})
                return

            if path == "/api/draft/discard":
                draft_path(video_id).unlink(missing_ok=True)
                self._json({"ok": True})
                return

            if path == "/api/preview":
                self._json(preview(video_id, _normalize_edits(payload)))
                return

            if path == "/api/publish":
                if not payload.get("confirm"):
                    self._json({"error": "Липсва потвърждение."}, 400)
                    return
                mode = "branch" if payload.get("mode") == "branch" else "direct"
                self._json(
                    publish(
                        video_id,
                        _normalize_edits(payload),
                        message=(payload.get("message") or "").strip() or None,
                        mode=mode,
                        push=bool(payload.get("push", True)),
                    )
                )
                return

            self._json({"error": "Няма такъв адрес."}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except RuntimeError as e:
            self._json({"error": str(e)}, 500)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"Неочаквана грешка: {e}"}, 500)


def main():
    parser = argparse.ArgumentParser(description="Светоглед — режим на редакция")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        print(
            "ВНИМАНИЕ: редакторът е достъпен извън този компютър "
            f"({args.host}). Той може да пише в хранилището — не го оставяйте "
            "отворен в чужда мрежа."
        )

    DRAFTS_DIR.mkdir(exist_ok=True)
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer((args.host, args.port), RedactionHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Режим на редакция: {url}")
    print(f"  хранилище: {github_slug() or ROOT}  клон: {current_branch() or '—'}")
    print(f"  публикуване по подразбиране: {PUBLISH_BRANCH}")
    print("  Ctrl+C за спиране")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — a headless box has no browser
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСпряно.")


if __name__ == "__main__":
    main()
