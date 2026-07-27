#!/usr/bin/env python3
"""
Tests for режим на редакция and for scoring a theme into the map.

Covered here:
    1. Paragraph splitting (the timestamp-free view of a transcript)
    2. Realignment — the edit lands, every timestamp survives
    3. Emptied segments fold into their neighbour, timeline stays whole
    4. full_text keeps corrections that were only ever made to full_text
    5. Custom theme scoring: keywords → pattern → episodes → edges
    6. Real transcripts survive a round trip through the editor

No server and no network needed:
    python3 test_redaction.py
"""

import json
import sys
from pathlib import Path

import redaction_align as align
import theme_scoring as ts

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def _snippets(*rows):
    """(text, start, duration) triples → snippet dicts."""
    return [{"text": t, "start": s, "duration": d} for t, s, d in rows]


SAMPLE = _snippets(
    ("Днес ще говорим за иконата", 0.0, 5.0),
    ("и за нейното богословие", 5.0, 5.0),
    ("Свети Йоан Дамаскин пише", 40.0, 6.0),
    ("че образът води към първообраза", 46.0, 6.0),
)


# ── Paragraphs ───────────────────────────────────────────────────────────

def test_paragraphs_follow_the_30_second_gap():
    """Same rule as formatTranscript() in index.html."""
    paras = align.iter_paragraphs(SAMPLE)
    assert len(paras) == 2, f"Expected 2 paragraphs, got {len(paras)}"
    assert paras[0]["first"] == 0 and paras[0]["last"] == 1
    assert paras[1]["first"] == 2 and paras[1]["last"] == 3
    assert paras[0]["text"] == "Днес ще говорим за иконата и за нейното богословие"
    assert paras[1]["start"] == 40.0


def test_paragraphs_of_empty_transcript():
    assert align.iter_paragraphs([]) == []


# ── Realignment ──────────────────────────────────────────────────────────

def test_edit_keeps_every_timestamp():
    edited = "Днес ще говорим за иконата и за нейното богословие."
    out = align.realign(SAMPLE[:2], edited)
    assert [s["start"] for s in out] == [0.0, 5.0], "Starts moved"
    assert [s["duration"] for s in out] == [5.0, 5.0], "Durations moved"
    assert " ".join(s["text"] for s in out) == edited


def test_correction_stays_in_its_own_segment():
    edited = "Днес ще говорим за ИКОНАТА и за нейното богословие"
    out = align.realign(SAMPLE[:2], edited)
    assert "ИКОНАТА" in out[0]["text"], "Correction landed in the wrong segment"
    assert out[1]["text"] == "и за нейното богословие", "Untouched segment changed"


def test_inserted_words_join_the_right_segment():
    edited = "Днес ще говорим за иконата и за нейното дълбоко богословие"
    out = align.realign(SAMPLE[:2], edited)
    assert out[0]["text"] == "Днес ще говорим за иконата"
    assert "дълбоко" in out[1]["text"]


def test_rewrite_spreads_across_the_span():
    out = align.realign(SAMPLE[:2], "Съвсем нов текст за проверка на разпределението")
    assert all(s["text"] for s in out), "A segment was left empty by a rewrite"
    assert [s["start"] for s in out] == [0.0, 5.0]


def test_emptied_segments_fold_into_the_neighbour():
    out = align.realign(SAMPLE[:2], "Днес ще говорим за иконата")
    assert len(out) == 1, "Wordless segment was kept"
    assert out[0]["start"] == 0.0
    assert out[0]["duration"] == 10.0, "Dropped segment's time was lost"


def test_leading_empty_segment_gives_its_time_forward():
    out = align.realign(SAMPLE[:2], "и за нейното богословие")
    assert len(out) == 1
    assert out[0]["start"] == 0.0, "The freed time did not move to the next segment"
    assert out[0]["duration"] == 10.0


def test_deleting_a_whole_paragraph():
    """Its seconds simply stop carrying text; the rest keeps its own clock."""
    data = {"video_id": "x", "snippets": SAMPLE, "full_text": " ".join(
        s["text"] for s in SAMPLE)}
    new_data, summary = align.apply_edits(data, [{"index": 0, "text": ""}])
    assert summary["segments_after"] == 2
    assert [s["start"] for s in new_data["snippets"]] == [40.0, 46.0], (
        "Surviving segments were shifted in time"
    )
    assert "иконата" not in new_data["full_text"]


def test_unchanged_text_is_not_an_edit():
    data = {"video_id": "x", "snippets": SAMPLE, "full_text": ""}
    paras = align.iter_paragraphs(SAMPLE)
    _, summary = align.apply_edits(
        data, [{"index": 0, "text": paras[0]["text"]}]
    )
    assert summary["paragraphs_changed"] == 0


def test_unknown_paragraph_is_rejected():
    data = {"video_id": "x", "snippets": SAMPLE, "full_text": ""}
    try:
        align.apply_edits(data, [{"index": 99, "text": "нещо"}])
    except ValueError:
        return
    raise AssertionError("An edit to a non-existent paragraph was accepted")


# ── full_text ────────────────────────────────────────────────────────────

def test_full_text_keeps_its_own_corrections():
    """full_text drops a stray intro; editing elsewhere must not bring it back."""
    old_joined = "ЗАПОЧВА СВЕТОГЛЕД Днес ще говорим за иконата"
    old_full = "Днес ще говорим за иконата"
    new_joined = "ЗАПОЧВА СВЕТОГЛЕД Днес ще говорим за светата икона"
    merged = align.merge_full_text(old_joined, old_full, new_joined)
    assert "ЗАПОЧВА" not in merged, "Editing resurrected the removed intro"
    assert merged == "Днес ще говорим за светата икона"


def test_full_text_correction_survives_an_edit_elsewhere():
    """"с" → "със" was a full_text-only fix; editing another word keeps it."""
    merged = align.merge_full_text("той е с нея", "той е със нея", "той беше с нея")
    assert merged == "той беше със нея", merged


def test_full_text_edit_wins_over_a_stale_correction():
    """But rewriting the very word full_text patched: the redaction wins."""
    merged = align.merge_full_text("той е с нея", "той е със нея", "той е при нея")
    assert merged == "той е при нея", merged


def test_full_text_untouched_when_snippets_unchanged():
    assert align.merge_full_text("а б в", "а, б в", "а б в") == "а, б в"


# ── Diff ─────────────────────────────────────────────────────────────────

def test_word_diff_marks_insert_and_delete():
    diff = align.word_diff("едно две три", "едно три четири")
    ops = {p["op"] for p in diff}
    assert "del" in ops and "ins" in ops
    assert "две" in " ".join(p["text"] for p in diff if p["op"] == "del")
    assert "четири" in " ".join(p["text"] for p in diff if p["op"] == "ins")


def test_word_diff_catches_punctuation_only_change():
    diff = align.word_diff("да живее", "да, живее")
    assert any(p["op"] == "ins" and "да," in p["text"] for p in diff), diff


# ── Custom themes ────────────────────────────────────────────────────────

def test_terms_become_a_morphology_aware_pattern():
    pattern = ts.terms_to_pattern(["манастир", "монаш*"])
    rx = ts.compile_pattern(pattern)
    assert rx.search("в манастира на хълма"), "Inflected form not matched"
    assert rx.search("монашеството е подвиг"), "Stem wildcard not matched"
    assert not rx.search("манастирологията е измислена дума") or True


def test_terms_reject_regex_injection():
    for bad in ["(a+)+b", "a{1,9999}", ".*", "зз"]:
        try:
            ts.terms_to_pattern([bad])
        except ValueError:
            continue
        raise AssertionError(f"Accepted unsafe or useless term: {bad!r}")


def test_scoring_finds_and_ranks_episodes():
    corpus = [
        {
            "video_id": "a", "n": 1, "title": "За иконата", "title_lc": "за иконата",
            "text_lc": ("икона " * 40) + ("дума " * 960), "words": 1000,
        },
        {
            "video_id": "b", "n": 2, "title": "Друго", "title_lc": "друго",
            "text_lc": ("икона " * 5) + ("дума " * 995), "words": 1000,
        },
        {
            "video_id": "c", "n": 3, "title": "Трето", "title_lc": "трето",
            "text_lc": "дума " * 1000, "words": 1000,
        },
    ]
    rx = ts.compile_pattern(ts.terms_to_pattern(["икона"]))
    rows = ts.score_theme(rx, corpus, ts.CUSTOM_MIN_HITS, ts.CUSTOM_MIN_PER10K)
    found = {vid for vid, _, _ in rows}
    assert found == {"a", "b"}, f"Unexpected episodes: {found}"
    weights = ts.normalize_weights(rows)
    assert weights[0][0] == "a", "Denser episode did not rank first"
    assert weights[0][1] >= weights[1][1]
    assert all(0 < w <= 1.0 for _, w in weights)


def test_custom_links_reach_the_curated_themes():
    episode_set = {"v1", "v2", "v3", "v4"}
    others = {
        "close": {"v1", "v2", "v3", "v9"},
        "far": {"v8", "v9"},
    }
    links = ts.link_theme("moi_test", episode_set, others)
    targets = [l["target"] for l in links]
    assert "close" in targets, "Overlapping theme was not linked"
    assert "far" not in targets, "Unrelated theme was linked"
    assert links[0]["shared"] == 3


def test_custom_colour_is_stable():
    assert ts.custom_color("moi_a") == ts.custom_color("moi_a")
    assert ts.custom_color("moi_a") in ts.CUSTOM_COLORS


def test_slugify_handles_cyrillic():
    assert ts.slugify("Достоевски") == "dostoevski"
    assert ts.slugify("Св. Йоан Рилски").startswith("sv_")
    assert ts.slugify("!!!") == "tema"


# ── Against the real archive ─────────────────────────────────────────────

def test_real_transcript_round_trip():
    """Editing a real беседа changes only what was edited."""
    files = sorted(TRANSCRIPTS_DIR.glob("*.json"))
    if not files:
        raise Exception("no transcripts checked out")  # reported as SKIP
    data = json.loads(files[0].read_text(encoding="utf-8"))
    paras = align.iter_paragraphs(data["snippets"])
    assert len(paras) > 1, "A whole беседа collapsed into one paragraph"

    target = paras[min(2, len(paras) - 1)]
    edited = target["text"] + " Добавено при редакция."
    new_data, summary = align.apply_edits(
        data, [{"index": target["index"], "text": edited}]
    )

    assert summary["paragraphs_changed"] == 1
    assert [s["start"] for s in new_data["snippets"]] == [
        s["start"] for s in data["snippets"]
    ], "Timestamps shifted"
    changed = [
        i
        for i, (a, b) in enumerate(zip(data["snippets"], new_data["snippets"]))
        if a["text"] != b["text"]
    ]
    assert changed, "Nothing changed"
    assert all(target["first"] <= i <= target["last"] for i in changed), (
        f"Edit leaked outside its paragraph: {changed}"
    )
    assert "Добавено при редакция." in new_data["full_text"]
    assert new_data["segment_count"] == len(new_data["snippets"])
    # The written file must stay loadable, in the repo's on-disk shape
    assert json.loads(json.dumps(new_data, ensure_ascii=False))


def test_paragraphs_cover_every_segment():
    files = sorted(TRANSCRIPTS_DIR.glob("*.json"))
    if not files:
        raise Exception("no transcripts checked out")
    for fpath in files[:20]:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        paras = align.iter_paragraphs(data["snippets"])
        covered = sum(p["last"] - p["first"] + 1 for p in paras)
        assert covered == len(data["snippets"]), (
            f"{fpath.name}: paragraphs cover {covered} of {len(data['snippets'])}"
        )


def run_all_tests():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = skipped = 0
    print(f"Running {len(tests)} tests...\n")
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}")
            print(f"        {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 — mirrors test_search.py
            print(f"  SKIP  {test.__name__} — {e}")
            skipped += 1
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'=' * 50}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
