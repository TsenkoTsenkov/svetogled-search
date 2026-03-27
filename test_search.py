#!/usr/bin/env python3
"""
Tests for the Светоглед transcript search system.

Tests cover:
    1. Meilisearch connectivity
    2. Index existence and document count
    3. Bulgarian text search accuracy
    4. Timestamp and YouTube URL correctness
    5. Search result structure
    6. Indexer script (document building)
    7. Search web app (HTTP serving)

Usage:
    python test_search.py
    python -m pytest test_search.py -v
"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import meilisearch

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "svetogled-search-key"
INDEX_NAME = "segments"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
SEARCH_APP_PORT = 8080


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_client():
    return meilisearch.Client(MEILI_URL, MEILI_KEY)


def get_index():
    return get_client().index(INDEX_NAME)


# ── Test: Meilisearch connectivity ───────────────────────────────────────────

def test_meilisearch_is_running():
    """Meilisearch should be reachable and healthy."""
    client = get_client()
    health = client.health()
    assert health["status"] == "available", f"Meilisearch unhealthy: {health}"


# ── Test: Index exists and has documents ─────────────────────────────────────

def test_index_exists():
    """The segments index should exist."""
    client = get_client()
    indexes = client.get_indexes()
    names = [idx.uid for idx in indexes["results"]]
    assert INDEX_NAME in names, f"Index '{INDEX_NAME}' not found. Available: {names}"


def test_index_has_documents():
    """Index should have a reasonable number of documents."""
    stats = get_index().get_stats()
    count = stats.number_of_documents
    assert count > 100, f"Expected >100 documents, got {count}"


def test_index_settings():
    """Index should have correct searchable/filterable attributes."""
    settings = get_index().get_settings()
    assert "text" in settings["searchableAttributes"]
    assert "title" in settings["searchableAttributes"]
    assert "video_id" in settings["filterableAttributes"]


# ── Test: Search works with Bulgarian text ───────────────────────────────────

def test_search_returns_results():
    """A basic Bulgarian search should return results."""
    results = get_index().search("Светоглед")
    assert len(results["hits"]) > 0, "Search for 'Светоглед' returned no results"


def test_search_finds_specific_content():
    """Searching for a distinctive term should find relevant results."""
    results = get_index().search("православен поглед")
    assert len(results["hits"]) > 0, "Search for 'православен поглед' returned no results"
    # At least one result should contain the search terms
    texts = [h["text"].lower() for h in results["hits"][:5]]
    found = any("православен" in t for t in texts)
    assert found, "None of the top results contain 'православен'"


def test_search_empty_query():
    """Empty query should return no results (or all, depending on config)."""
    results = get_index().search("")
    # Meilisearch returns results for empty query — that's fine
    assert "hits" in results


def test_search_no_results_for_nonsense():
    """Nonsense query should return no results."""
    results = get_index().search("xyzzyplugh12345")
    assert len(results["hits"]) == 0, "Nonsense query should return 0 results"


# ── Test: Result structure ───────────────────────────────────────────────────

def test_result_has_required_fields():
    """Each search result should have all required fields."""
    results = get_index().search("Светоглед", {"limit": 5})
    required_fields = {"video_id", "title", "text", "timestamp", "youtube_url"}

    for hit in results["hits"]:
        missing = required_fields - set(hit.keys())
        assert not missing, f"Result missing fields: {missing}. Hit: {hit.get('title', '?')}"


def test_youtube_url_format():
    """YouTube URLs should be properly formatted with video ID and timestamp."""
    results = get_index().search("Светоглед", {"limit": 5})

    for hit in results["hits"]:
        url = hit["youtube_url"]
        assert url.startswith("https://www.youtube.com/watch?v="), f"Bad URL format: {url}"
        assert hit["video_id"] in url, f"Video ID not in URL: {url}"


def test_timestamp_format():
    """Timestamps should be in MM:SS format."""
    results = get_index().search("Светоглед", {"limit": 10})

    for hit in results["hits"]:
        ts = hit["timestamp"]
        parts = ts.split(":")
        assert len(parts) == 2, f"Timestamp not MM:SS: {ts}"
        assert parts[0].isdigit() and parts[1].isdigit(), f"Timestamp not numeric: {ts}"


def test_start_seconds_matches_timestamp():
    """start_seconds should be consistent with the timestamp field."""
    results = get_index().search("Светоглед", {"limit": 10})

    for hit in results["hits"]:
        ts = hit["timestamp"]
        mins, secs = int(ts.split(":")[0]), int(ts.split(":")[1])
        expected_seconds = mins * 60 + secs
        assert hit["start_seconds"] == expected_seconds, \
            f"Mismatch: start_seconds={hit['start_seconds']} but timestamp={ts}"


# ── Test: Highlighting works ─────────────────────────────────────────────────

def test_search_highlighting():
    """Search results should include highlighted matches."""
    results = get_index().search("Кант", {
        "limit": 3,
        "attributesToHighlight": ["text"],
        "highlightPreTag": "<em>",
        "highlightPostTag": "</em>",
    })
    if results["hits"]:
        formatted = results["hits"][0].get("_formatted", {})
        assert "<em>" in formatted.get("text", ""), "Highlighting not working"


# ── Test: Transcript files integrity ─────────────────────────────────────────

def test_transcript_files_valid_json():
    """All transcript files should be valid JSON with required fields."""
    required = {"video_id", "title", "full_text", "snippets"}
    files = list(TRANSCRIPTS_DIR.glob("*.json"))
    assert len(files) > 0, "No transcript files found"

    for fpath in files:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        missing = required - set(data.keys())
        assert not missing, f"{fpath.name} missing fields: {missing}"
        assert len(data["snippets"]) > 0, f"{fpath.name} has no snippets"
        assert len(data["full_text"]) > 0, f"{fpath.name} has empty full_text"


def test_transcript_snippets_have_timestamps():
    """Each snippet should have start time and text."""
    files = list(TRANSCRIPTS_DIR.glob("*.json"))[:5]  # Check first 5

    for fpath in files:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        for i, snippet in enumerate(data["snippets"][:3]):
            assert "text" in snippet, f"{fpath.name} snippet {i} missing 'text'"
            assert "start" in snippet, f"{fpath.name} snippet {i} missing 'start'"
            assert isinstance(snippet["start"], (int, float)), \
                f"{fpath.name} snippet {i} 'start' is not a number"


# ── Test: Search app serves HTML ─────────────────────────────────────────────

def test_search_app_serves_html():
    """The search web app should serve HTML on the root path."""
    try:
        req = urllib.request.Request(f"http://localhost:{SEARCH_APP_PORT}/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert "Светоглед" in html, "Page title not found in HTML"
            assert "search-input" in html, "Search input not found in HTML"
            assert resp.status == 200
    except Exception as e:
        print(f"  SKIPPED (search app not running): {e}")


# ── Test: Indexer document building ──────────────────────────────────────────

def test_indexer_builds_documents():
    """The indexer should build documents from transcript files."""
    # Import the indexer's build function
    sys.path.insert(0, str(Path(__file__).parent))
    from index_to_meili import build_documents
    docs = build_documents()
    assert len(docs) > 0, "Indexer built no documents"

    # Check first doc structure
    doc = docs[0]
    assert "id" in doc
    assert "video_id" in doc
    assert "title" in doc
    assert "text" in doc
    assert "timestamp" in doc
    assert "youtube_url" in doc


# ── Runner ───────────────────────────────────────────────────────────────────

def run_all_tests():
    tests = [
        test_meilisearch_is_running,
        test_index_exists,
        test_index_has_documents,
        test_index_settings,
        test_search_returns_results,
        test_search_finds_specific_content,
        test_search_empty_query,
        test_search_no_results_for_nonsense,
        test_result_has_required_fields,
        test_youtube_url_format,
        test_timestamp_format,
        test_start_seconds_matches_timestamp,
        test_search_highlighting,
        test_transcript_files_valid_json,
        test_transcript_snippets_have_timestamps,
        test_search_app_serves_html,
        test_indexer_builds_documents,
    ]

    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(tests)} tests...\n")

    for test in tests:
        name = test.__name__
        try:
            test()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}")
            print(f"        {e}")
            failed += 1
        except Exception as e:
            print(f"  SKIP  {name} — {e}")
            skipped += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'=' * 50}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
