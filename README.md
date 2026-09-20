# Светоглед — searchable transcript archive

A full-text search engine over the **Светоглед** radio series (Радио Зорана) with
Георги Тодоров — 294 episodes, transcribed, corrected, themed and indexed, at
**<https://svetogled-arhiv.com>**.

New episodes are picked up, transcribed and published **automatically every
Wednesday**. Nobody has to do anything for the archive to stay current.

---

## What it does

- **Search** every word of every episode, with snippets that jump to the exact
  timestamp in the recording.
- **Browse by theme** (`/tema/<theme>`) — a taxonomy generated from the
  transcripts by `scripts/generate_themes.py` and committed as `themes.json`.
- **Per-episode pages** (`/episode/<id>`) with the full transcript, built for
  search engines: sitemap, structured data (`RadioSeries` / `Person` /
  `RadioStation`), Open Graph and Twitter cards.
- **Редакция mode** — an in-browser editor for correcting transcription errors
  that puts edited words back on their original timestamps. See
  [`REDACTION.md`](REDACTION.md).

## How it is built

| Piece | What |
|---|---|
| `search_app.py` | The whole server: a stdlib `ThreadingHTTPServer`, no framework. Serves the UI, the JSON API, the sitemap and a proxy to Meilisearch. |
| **Meilisearch** | The search index. Rebuilt `--fresh` on every deploy by `index_to_meili.py`. |
| `transcripts/*.json` | 294 episodes — `video_id`, `title`, `snippets` (timestamped), `full_text`, `episode_number`, `upload_date`. Committed to the repo; they *are* the database. |
| `themes.json` | The theme map, generated offline and committed. Served from memory, reloaded on mtime change. |
| `theme_scoring.py` | Scores episodes against the theme taxonomy. |

### Endpoints

```
/                     the search UI
/about
/episode/<video_id>   per-episode page (transcript, SEO markup)
/tema/<theme>         theme page
/api/episodes  /api/themes  /api/topics  /api/transcript
/meili/*              proxied to Meilisearch
/sitemap.xml  /robots.txt  /site.webmanifest  /favicon.ico
```

## The transcription pipeline

`.github/workflows/update-transcripts.yml`, Wednesdays at 06:00 UTC on
`ubuntu-latest`:

1. `scripts/check_new_episodes.py` — anything new on the channel?
2. `scripts/fetch_new_transcripts.py` — YouTube's own captions where they exist
3. `scripts/whisper_remaining.py` — Whisper for the rest (the CLI is built in the job)
4. `scripts/correct_transcripts.py` — fixes recurring mis-transcriptions
5. `scripts/normalize_titles.py` — titles + playlist order
6. `scripts/generate_themes.py` — regenerates `themes.json`
7. commit + push → which triggers **Deploy**

It needs the `YOUTUBE_COOKIES` repo secret (yt-dlp) and installs Deno for
yt-dlp's EJS solver.

> Editing the taxonomy in `scripts/generate_themes.py` would otherwise ship
> nothing, because deploy only serves the committed `themes.json`.
> `regenerate-themes.yml` exists to close that loop: it reruns the generator on
> any change to it and commits the result.

## Deploying

Push to `main` touching the app, the transcripts or `mac/` →
`.github/workflows/deploy.yml`:

1. **test** on `ubuntu-latest` — `python test_search.py` (markup contract, static
   assets; server-dependent tests self-skip when Meili is not up)
2. **deploy** on the self-hosted runner: `git reset --hard` the server checkout
   to the pushed SHA, then `bash mac/deploy-mac.sh`
3. **health** on `ubuntu-latest` — probes `https://svetogled-arhiv.com/` from
   outside

`mac/deploy-mac.sh` is idempotent and needs no sudo: venv → pinned Meilisearch
binary (1.6.2) → LaunchAgents (rewritten only when changed) → reindex → refresh
the Caddy tenant file → restart the app.

## Running it locally

```bash
pip install meilisearch
python search_app.py          # http://localhost:8080
```

Search needs Meilisearch running and indexed; everything else works without it.

## Where it runs

On an on-prem MacBook Air alongside two other stacks, behind a shared Caddy and
a Cloudflare tunnel.

**→ [`docs/operations.md`](docs/operations.md) — deployment, monitoring, alerts,
access, and what to do when it breaks.**
**→ [The box index](https://github.com/TsenkoTsenkov/box-ops)** — everything else
hosted on the same machine.
