#!/usr/bin/env python3
"""
Index all transcripts into Meilisearch for full-text search.
Each segment becomes a searchable document with video info and timestamp.

Usage:
    python index_to_meili.py          # Index all transcripts
    python index_to_meili.py --fresh  # Delete index and re-index everything

Requires: pip install meilisearch
"""

import json
import sys
from pathlib import Path

import meilisearch

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "svetogled-search-key"
INDEX_NAME = "segments"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

# We group consecutive segments into chunks for better search context
CHUNK_SIZE = 5  # Number of segments to combine into one searchable document


def chunk_segments(segments, chunk_size=CHUNK_SIZE):
    """Group segments into chunks for more meaningful search results."""
    chunks = []
    for i in range(0, len(segments), chunk_size):
        group = segments[i:i + chunk_size]
        text = " ".join(s["text"] for s in group)
        start = group[0]["start"]
        end = group[-1]["start"] + group[-1].get("duration", 0)
        chunks.append({
            "text": text,
            "start": start,
            "end": end,
        })
    return chunks


def build_documents():
    """Build search documents from all transcript files."""
    documents = []
    doc_id = 0

    for fpath in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(fpath.read_text(encoding="utf-8"))
        video_id = data["video_id"]
        title = data["title"]
        source = data.get("source", "unknown")
        snippets = data.get("snippets", [])

        if not snippets:
            continue

        # Index chunked segments (for contextual search)
        chunks = chunk_segments(snippets)
        for chunk in chunks:
            start_sec = int(chunk["start"])
            mins = start_sec // 60
            secs = start_sec % 60
            documents.append({
                "id": doc_id,
                "video_id": video_id,
                "title": title,
                "source": source,
                "text": chunk["text"],
                "start_seconds": start_sec,
                "timestamp": f"{mins:02d}:{secs:02d}",
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}&t={start_sec}",
            })
            doc_id += 1

        # Full transcript documents removed — they always show 00:00 timestamps
        # and the chunked segments already cover all the text.

    return documents


def main():
    fresh = "--fresh" in sys.argv

    client = meilisearch.Client(MEILI_URL, MEILI_KEY)

    if fresh:
        print("Deleting existing index...")
        try:
            client.delete_index(INDEX_NAME)
        except Exception:
            pass

    # Create or get index
    client.create_index(INDEX_NAME, {"primaryKey": "id"})
    index = client.index(INDEX_NAME)

    # Configure searchable and filterable attributes
    index.update_settings({
        "searchableAttributes": ["text", "title"],
        "filterableAttributes": ["video_id", "title", "source"],
        "sortableAttributes": ["start_seconds", "title"],
        "displayedAttributes": [
            "video_id", "title", "text", "timestamp",
            "start_seconds", "youtube_url", "source"
        ],
    })

    print("Building documents from transcripts...")
    documents = build_documents()
    print(f"Total documents: {len(documents)}")

    # Index in batches of 1000
    batch_size = 1000
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        task = index.add_documents(batch)
        print(f"  Indexed batch {i // batch_size + 1} ({len(batch)} docs) — task: {task.task_uid}")

    # Wait for indexing to complete
    print("Waiting for indexing to complete...")
    client.wait_for_task(task.task_uid, timeout_in_ms=600000)
    print("Done!")

    stats = index.get_stats()
    print(f"\nIndex stats:")
    print(f"  Documents: {stats.number_of_documents}")
    print(f"  Indexing:  {stats.is_indexing}")
    print(f"\nSearch UI: http://127.0.0.1:7700")
    print(f"API key:   {MEILI_KEY}")


if __name__ == "__main__":
    main()
