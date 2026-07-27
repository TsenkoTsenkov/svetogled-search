#!/usr/bin/env python3
"""
Shared scoring math for the theme map ("Карта на темите").

Two callers need identical numbers:

  * scripts/generate_themes.py — builds the curated themes.json offline
  * search_app.py              — scores ONE user-defined theme on demand
    (POST /api/themes/custom), so a theme added from the site lands on the
    constellation with the same weights, thresholds and edge rules as the
    45 curated ones instead of being a chip that links nowhere.

Keeping the math here means the two can never drift apart. Deterministic,
stdlib-only, no network access.
"""

import math
import re
import unicodedata
from pathlib import Path

# ── Scoring defaults (curated taxonomy) ──────────────────────────────────
DEFAULT_MIN_HITS = 5       # minimum raw pattern hits in an episode
DEFAULT_MIN_PER10K = 4.5   # minimum hits per 10 000 words
TITLE_WEIGHT = 0.9         # weight floor when the title names the theme
MAX_THEMES_PER_EPISODE = 6

# Edges: keep pairs sharing enough episodes, then prune to the strongest
EDGE_MIN_SHARED = 4
EDGE_MIN_OVERLAP = 0.3
EDGE_TOP_PER_NODE = 4

# ── Custom themes (added from the site) ──────────────────────────────────
# A user's theme is usually a narrow phrase ("Достоевски", "старчество"),
# not a 20-alternative curated pattern, so it clears a lower bar — otherwise
# most hand-typed themes would score zero episodes and never reach the map.
CUSTOM_MIN_HITS = 3
CUSTOM_MIN_PER10K = 3.0
CUSTOM_MAX_EPISODES = 90   # keep one node from swallowing the whole archive

# Its edges are also cut with a lower bar: a single new node judged by the
# curated rules (≥4 shared, ≥0.3 overlap) would often float unconnected,
# which is precisely the "no relations" behaviour we are fixing.
CUSTOM_EDGE_MIN_SHARED = 2
CUSTOM_EDGE_MIN_OVERLAP = 0.12
CUSTOM_EDGE_TOP = 6

# Group id used for every custom theme, so the legend can show them together.
CUSTOM_GROUP = "moi"
CUSTOM_GROUP_LABEL = "Мои теми"

# Distinct hues for custom nodes — deliberately outside the five curated
# group colours (gold / rose / blue / olive / slate) so a personal theme
# reads as personal at a glance.
CUSTOM_COLORS = [
    "#7fc7b8",  # teal
    "#b98cc9",  # amethyst
    "#e0955f",  # amber
    "#8fb3e0",  # ice
    "#c98ca4",  # mauve
    "#a9c47f",  # moss
]


# ── Corpus ───────────────────────────────────────────────────────────────

def _get_duration(data):
    snippets = data.get("snippets") or data.get("segments", [])
    return snippets[-1].get("start", 0) if snippets else 0


def _is_reupload(dur_a, dur_b):
    if dur_a == 0 or dur_b == 0:
        return False
    return abs(dur_a - dur_b) / max(dur_a, dur_b) < 0.05


def load_episodes(transcripts_dir):
    """Load transcripts, deduplicating re-uploads (same number, ~same length).

    Prefers the version whose title carries the (Беседа N) label — the same
    rule /api/episodes and the sitemap use, so every surface counts the same
    archive.
    """
    import json

    episodes = []
    for f in sorted(Path(transcripts_dir).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        episodes.append(
            {
                "video_id": data["video_id"],
                "title": data.get("title", ""),
                "episode_number": data.get("episode_number", 0),
                "text": data.get("full_text", ""),
                "_duration": _get_duration(data),
            }
        )

    seen = {}
    unique = []
    for ep in episodes:
        n = ep["episode_number"]
        if n in seen and _is_reupload(seen[n]["_duration"], ep["_duration"]):
            prev = seen[n]
            has_label = f"(Беседа {n})" in ep["title"]
            prev_has = f"(Беседа {n})" in prev["title"]
            if has_label and not prev_has:
                unique[unique.index(prev)] = ep
                seen[n] = ep
            continue
        unique.append(ep)
        seen[n] = ep
    return unique


def prepare_corpus(episodes):
    """Pre-lowercase every transcript once.

    Scoring a theme then costs a single regex sweep (~0.2s over the whole
    archive) instead of re-lowercasing 11 MB of Bulgarian per request.
    """
    corpus = []
    for ep in episodes:
        text_lc = ep["text"].lower()
        corpus.append(
            {
                "video_id": ep["video_id"],
                "n": ep.get("episode_number", 0),
                "title": ep.get("title", ""),
                "text_lc": text_lc,
                "title_lc": ep.get("title", "").lower(),
                "words": max(1, len(text_lc.split())),
            }
        )
    return corpus


# ── Patterns ─────────────────────────────────────────────────────────────

# Bulgarian inflection is suffixal, so a bare term matches its own forms if
# we allow a few trailing letters: "манастир" → манастира/манастирът/
# манастири(те). Three letters covers the article + plural endings without
# letting "икон" reach "икономика". A trailing "*" opts into full stemming.
_INFLECTION = r"[а-яa-z]{0,3}"

_TERM_OK = re.compile(r"^[\w \-'’*]+$", re.UNICODE)


def terms_to_pattern(terms):
    """Build a morphology-aware regex source from plain user keywords.

    Users type words, never regex — the site must not hand arbitrary patterns
    to re.compile (a nested-quantifier pattern would pin the server's CPU for
    minutes). Each term is escaped, then given Bulgarian inflection room:

        монах        → монах[а-яa-z]{0,3}\\b
        монаш*       → монаш\\w*              (explicit stem wildcard)
        света гора   → света\\s+гора[а-яa-z]{0,3}\\b

    Raises ValueError on anything unusable.
    """
    parts = []
    for raw in terms:
        term = (raw or "").strip().lower()
        if not term:
            continue
        if len(term) > 60:
            raise ValueError(f"Терминът е твърде дълъг: {raw!r}")
        if not _TERM_OK.match(term):
            raise ValueError(f"Недопустими знаци в термина: {raw!r}")
        stem = term.endswith("*")
        term = term.rstrip("*").strip()
        if len(term) < 3:
            raise ValueError(f"Терминът е твърде кратък: {raw!r}")
        words = [re.escape(w) for w in term.split() if w]
        if not words:
            raise ValueError(f"Празен термин: {raw!r}")
        tail = r"\w*" if stem else _INFLECTION + r"\b"
        parts.append(r"\s+".join(words[:-1] + [words[-1] + tail]))
    if not parts:
        raise ValueError("Няма зададени думи за темата.")
    return "|".join(parts)


def compile_pattern(pattern):
    """Compile a theme pattern the way the generator does."""
    return re.compile(r"\b(?:" + pattern + r")", re.IGNORECASE)


_SLUG_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}


def slugify(label):
    """Cyrillic-aware slug — node ids feed the layout seed and the URL hash."""
    out = []
    for ch in unicodedata.normalize("NFKC", label).lower():
        if ch in _SLUG_MAP:
            out.append(_SLUG_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in " -_/":
            out.append("_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug[:40] or "tema"


# ── Scoring ──────────────────────────────────────────────────────────────

def score_theme(regex, corpus, min_hits=DEFAULT_MIN_HITS,
                min_per10k=DEFAULT_MIN_PER10K):
    """Score one theme over a prepared corpus.

    Returns [(video_id, per10k, title_hit)] for the episodes that clear the
    density threshold, plus every episode whose *title* names the theme.
    """
    rows = []
    for ep in corpus:
        hits = sum(1 for _ in regex.finditer(ep["text_lc"]))
        per10k = hits * 10000.0 / ep["words"]
        title_hit = bool(regex.search(ep["title_lc"]))
        if title_hit or (hits >= min_hits and per10k >= min_per10k):
            rows.append((ep["video_id"], per10k, title_hit))
    return rows


def normalize_weights(rows):
    """[(vid, per10k, title_hit)] → [[vid, weight]] sorted strongest first.

    Log-scaled against the theme's own maximum so one dense outlier does not
    flatten the rest, with a floor for title matches.
    """
    if not rows:
        return []
    max_per10k = max(p for _, p, _ in rows) or 1.0
    out = []
    for vid, per10k, title_hit in rows:
        w = math.log1p(per10k) / math.log1p(max_per10k) if max_per10k else 1.0
        if title_hit:
            w = max(w, TITLE_WEIGHT)
        out.append([vid, round(min(1.0, w), 3)])
    out.sort(key=lambda r: -r[1])
    return out


# ── Edges ────────────────────────────────────────────────────────────────

def build_links(theme_sets, min_shared=EDGE_MIN_SHARED,
                min_overlap=EDGE_MIN_OVERLAP, top_per_node=EDGE_TOP_PER_NODE):
    """Co-occurrence edges for the whole map, pruned to the strongest.

    theme_sets: ordered mapping theme_id -> set(video_id).
    """
    raw_edges = []
    ids = list(theme_sets)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            shared = len(theme_sets[a] & theme_sets[b])
            if shared < min_shared:
                continue
            overlap = shared / min(len(theme_sets[a]), len(theme_sets[b]))
            if overlap < min_overlap:
                continue
            raw_edges.append(
                {
                    "source": a,
                    "target": b,
                    "shared": shared,
                    "weight": round(overlap, 3),
                    "_score": overlap * math.sqrt(shared),
                }
            )

    # Prune to each node's strongest edges (union), keeping the map legible
    by_node = {}
    for e in raw_edges:
        by_node.setdefault(e["source"], []).append(e)
        by_node.setdefault(e["target"], []).append(e)
    kept = set()
    for node, node_edges in by_node.items():
        node_edges.sort(key=lambda e: -e["_score"])
        for e in node_edges[:top_per_node]:
            kept.add(id(e))
    edges = [
        {k: v for k, v in e.items() if not k.startswith("_")}
        for e in raw_edges
        if id(e) in kept
    ]

    # Ensure no theme node floats disconnected if it has any relation at all
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    for tid, tset in theme_sets.items():
        if tid in connected or not tset:
            continue
        best, best_score = None, 0.0
        for other, oset in theme_sets.items():
            if other == tid or not oset:
                continue
            shared = len(tset & oset)
            if shared < 2:
                continue
            overlap = shared / min(len(tset), len(oset))
            score = overlap * math.sqrt(shared)
            if score > best_score:
                best, best_score = other, score
        if best:
            shared = len(tset & theme_sets[best])
            edges.append(
                {
                    "source": tid,
                    "target": best,
                    "shared": shared,
                    "weight": round(
                        shared / min(len(tset), len(theme_sets[best])), 3
                    ),
                }
            )
    return edges


def link_theme(theme_id, episode_set, other_sets, min_shared=CUSTOM_EDGE_MIN_SHARED,
               min_overlap=CUSTOM_EDGE_MIN_OVERLAP, top=CUSTOM_EDGE_TOP):
    """Edges from ONE theme to an existing map — the custom-theme case.

    The curated map is left untouched; we only add the new node's own
    strongest relations, so adding a theme costs a single regex sweep rather
    than a 37-second full rebuild.
    """
    scored = []
    for other, oset in other_sets.items():
        if other == theme_id or not oset or not episode_set:
            continue
        shared = len(episode_set & oset)
        if shared < min_shared:
            continue
        overlap = shared / min(len(episode_set), len(oset))
        if overlap < min_overlap:
            continue
        scored.append(
            (
                overlap * math.sqrt(shared),
                {
                    "source": theme_id,
                    "target": other,
                    "shared": shared,
                    "weight": round(overlap, 3),
                },
            )
        )
    scored.sort(key=lambda s: (-s[0], s[1]["target"]))
    return [e for _, e in scored[:top]]


def custom_color(theme_id):
    """Stable colour per custom theme id (same node, same hue every reload)."""
    h = 0
    for ch in theme_id:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return CUSTOM_COLORS[h % len(CUSTOM_COLORS)]
