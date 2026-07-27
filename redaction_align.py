#!/usr/bin/env python3
"""
Redaction: edit a transcript as plain text, keep the timestamps intact.

A transcript is a list of timed snippets. Correcting the text by hand means
hunting through hundreds of {"text", "start", "duration"} objects — which is
exactly what the редакция editor removes: it shows paragraphs, takes the
edited paragraphs back, and this module puts the words back on the clock.

How the realignment works
-------------------------
The edited paragraph is diffed against the original words (word level,
punctuation- and case-insensitive for matching). Each opcode then decides
where the new words land:

  equal    → the word keeps the snippet it already had
  replace  → the new words are spread across the snippets they replaced
  insert   → the words join the snippet at the insertion point
  delete   → the words simply disappear

So fixing a word inside minute 12 moves nothing: only that snippet's text
changes, and every YouTube deep link on the site still points where it did.
Snippets that end up empty are dropped and their time is folded into the
neighbour, so the timeline stays gapless.

Deterministic, stdlib-only.
"""

import re
from difflib import SequenceMatcher

PARAGRAPH_GAP = 30.0  # seconds — mirrors formatTranscript() in index.html

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


def _key(word):
    """Comparison key: punctuation and case do not break a word's identity."""
    return _PUNCT.sub("", word.lower())


def _keys(words):
    return [_key(w) for w in words]


# ── Paragraphs ───────────────────────────────────────────────────────────

def iter_paragraphs(snippets, gap=PARAGRAPH_GAP):
    """Group snippets into the paragraphs the site displays.

    Returns [{index, first, last, start, end, text}] where first/last are
    inclusive snippet indices — the range an edited paragraph is realigned
    against.
    """
    paragraphs = []
    if not snippets:
        return paragraphs
    first = 0
    para_start = snippets[0].get("start", 0.0)
    for i, s in enumerate(snippets):
        if s.get("start", 0.0) - para_start > gap and i > first:
            paragraphs.append(_paragraph(snippets, len(paragraphs), first, i - 1))
            first = i
            para_start = s.get("start", 0.0)
    paragraphs.append(_paragraph(snippets, len(paragraphs), first, len(snippets) - 1))
    return paragraphs


def _paragraph(snippets, index, first, last):
    text = " ".join(
        s.get("text", "").strip() for s in snippets[first : last + 1]
    ).strip()
    text = re.sub(r"\s+", " ", text)
    start = snippets[first].get("start", 0.0)
    end = snippets[last].get("start", 0.0) + snippets[last].get("duration", 0.0)
    return {
        "index": index,
        "first": first,
        "last": last,
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
    }


# ── Realignment ──────────────────────────────────────────────────────────

def realign(snippets, new_text):
    """Redistribute `new_text` over the timings of `snippets`.

    Returns a new list of snippets (same clock, new words). Snippets left
    without words are dropped and their duration is folded into the previous
    snippet — or into the next one, when the first snippet goes.
    """
    orig_words = []
    for i, s in enumerate(snippets):
        for w in s.get("text", "").split():
            orig_words.append((w, i))
    new_words = new_text.split()

    buckets = [[] for _ in snippets]
    if not orig_words:
        # Nothing to align against (an empty range): put it all in the first.
        if buckets:
            buckets[0] = new_words
    else:
        matcher = SequenceMatcher(
            None, _keys([w for w, _ in orig_words]), _keys(new_words),
            autojunk=False,
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    buckets[orig_words[i1 + k][1]].append(new_words[j1 + k])
            elif tag == "delete":
                continue
            elif tag == "insert":
                # Attach to the snippet the insertion point sits in; at the
                # very end, to the last snippet that had words.
                idx = (
                    orig_words[i1][1]
                    if i1 < len(orig_words)
                    else orig_words[-1][1]
                )
                buckets[idx].extend(new_words[j1:j2])
            else:  # replace — spread the new words across the span they cover
                span = i2 - i1
                count = j2 - j1
                for k in range(count):
                    offset = (k * span) // count if count else 0
                    idx = orig_words[min(i1 + offset, i2 - 1)][1]
                    buckets[idx].append(new_words[j1 + k])

    rebuilt = []
    for i, s in enumerate(snippets):
        out = dict(s)
        out["text"] = " ".join(buckets[i])
        rebuilt.append(out)
    return _drop_empty(rebuilt)


def _drop_empty(snippets):
    """Remove wordless snippets, folding their time into a neighbour."""
    kept = []
    pending = 0.0  # duration of dropped snippets waiting for a home
    pending_start = None
    for s in snippets:
        if not s.get("text", "").strip():
            if kept:
                kept[-1]["duration"] = round(
                    kept[-1].get("duration", 0.0) + s.get("duration", 0.0), 3
                )
            else:
                # Leading empties: the next snippet starts where they did.
                if pending_start is None:
                    pending_start = s.get("start", 0.0)
                pending += s.get("duration", 0.0)
            continue
        if pending or pending_start is not None:
            s = dict(s)
            s["duration"] = round(s.get("duration", 0.0) + pending, 3)
            s["start"] = round(
                pending_start if pending_start is not None else s.get("start", 0.0), 3
            )
            pending = 0.0
            pending_start = None
        kept.append(s)
    return kept


# ── full_text ────────────────────────────────────────────────────────────

def merge_full_text(old_joined, old_full_text, new_joined):
    """Carry the edit into full_text without undoing past corrections.

    full_text is not always the plain join of the snippets: correction passes
    (scripts/correct_transcripts.py, fix_episode.py) have edited it on its
    own — dropping a stray "ЗАПОЧВА СВЕТОГЛЕД" intro, fixing "с" → "със".
    Rebuilding it from the snippets would quietly undo all of that.

    So this is a three-way merge: base = the old joined snippets, "theirs" =
    the existing full_text, "ours" = the newly joined snippets. Every place
    full_text already differed is re-applied, unless the redaction touched
    that very span — there, the redaction wins.
    """
    base = old_joined.split()
    theirs = old_full_text.split()
    ours = new_joined.split()
    if base == ours:
        return old_full_text
    drift = [
        op
        for op in SequenceMatcher(None, base, theirs, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if not drift:
        return " ".join(ours)

    equal_blocks = [
        (i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in SequenceMatcher(
            None, base, ours, autojunk=False
        ).get_opcodes()
        if tag == "equal"
    ]

    def locate(i1, i2):
        """Base span → span in the edited text, or None if the redaction
        touched it. The whole span must sit inside one unchanged block: a
        correction may only be re-applied where the words it patched are
        still the words that are there."""
        for b1, b2, bj1, _ in equal_blocks:
            if i1 == i2:  # a pure insertion may sit on a block boundary
                if b1 <= i1 <= b2:
                    return (bj1 + (i1 - b1), bj1 + (i1 - b1))
            elif b1 <= i1 and i2 <= b2:
                return (bj1 + (i1 - b1), bj1 + (i2 - b1))
        return None

    patches = []
    for _tag, i1, i2, j1, j2 in drift:
        span = locate(i1, i2)
        if span is None:
            continue  # the redaction rewrote this span — leave it alone
        patches.append((span[0], span[1], theirs[j1:j2]))

    patches.sort(key=lambda p: p[0])
    out = []
    cursor = 0
    for start, end, words in patches:
        if start < cursor:
            continue  # overlapping patch, keep the first
        out.extend(ours[cursor:start])
        out.extend(words)
        cursor = end
    out.extend(ours[cursor:])
    return " ".join(out)


# ── Applying an edit ─────────────────────────────────────────────────────

def apply_edits(data, edits, gap=PARAGRAPH_GAP):
    """Apply paragraph edits to a transcript dict.

    edits: [{"index": <paragraph index>, "text": "<edited text>"}]
    Returns (new_data, summary). The input dict is not modified.
    """
    snippets = [dict(s) for s in data.get("snippets", [])]
    paragraphs = iter_paragraphs(snippets, gap)
    by_index = {p["index"]: p for p in paragraphs}

    changed = []
    for edit in edits:
        try:
            index = int(edit.get("index"))
        except (TypeError, ValueError):
            raise ValueError("Липсва номер на абзац.")
        para = by_index.get(index)
        if para is None:
            raise ValueError(f"Няма абзац №{index}.")
        new_text = re.sub(r"\s+", " ", str(edit.get("text", ""))).strip()
        if new_text == para["text"]:
            continue
        changed.append((para, new_text))

    old_joined = " ".join(s.get("text", "") for s in snippets)

    # Apply from the last paragraph backwards so earlier ranges stay valid
    # even when a paragraph loses snippets.
    for para, new_text in sorted(changed, key=lambda c: -c[0]["first"]):
        span = snippets[para["first"] : para["last"] + 1]
        snippets[para["first"] : para["last"] + 1] = realign(span, new_text)

    new_joined = " ".join(s.get("text", "") for s in snippets)
    new_data = dict(data)
    new_data["snippets"] = snippets
    new_data["segment_count"] = len(snippets)
    new_data["full_text"] = merge_full_text(
        old_joined, data.get("full_text", old_joined), new_joined
    )

    summary = {
        "paragraphs_changed": len(changed),
        "segments_before": len(data.get("snippets", [])),
        "segments_after": len(snippets),
        "words_before": len(old_joined.split()),
        "words_after": len(new_joined.split()),
        "changed_paragraphs": [p["index"] for p, _ in changed],
    }
    return new_data, summary


# ── Diff for review ──────────────────────────────────────────────────────

def word_diff(old_text, new_text):
    """Word-level diff as [{op, text}] — 'same' | 'del' | 'ins'."""
    old_words = old_text.split()
    new_words = new_text.split()
    out = []

    def push(op, words):
        if not words:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += " " + " ".join(words)
        else:
            out.append({"op": op, "text": " ".join(words)})

    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, _keys(old_words), _keys(new_words), autojunk=False
    ).get_opcodes():
        if tag == "equal":
            # Same words, but punctuation or case may still have changed.
            for k in range(i2 - i1):
                if old_words[i1 + k] == new_words[j1 + k]:
                    push("same", [new_words[j1 + k]])
                else:
                    push("del", [old_words[i1 + k]])
                    push("ins", [new_words[j1 + k]])
        elif tag == "delete":
            push("del", old_words[i1:i2])
        elif tag == "insert":
            push("ins", new_words[j1:j2])
        else:
            push("del", old_words[i1:i2])
            push("ins", new_words[j1:j2])
    return out
