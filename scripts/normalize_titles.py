#!/usr/bin/env python3
"""
Normalize episode titles to a consistent format.

Goals:
- Strip "Радио Зорана - Светоглед с Георги Тодоров" prefix
- Keep the original Беседа/издание number if present
- Normalize ALL CAPS to sentence case (preserve proper nouns)
- Clean up whitespace and formatting artifacts
- Add playlist_order field to JSON for chronological sorting
"""

import json
import re
import subprocess
from pathlib import Path

TRANSCRIPTS_DIR = Path(__file__).parent.parent / "transcripts"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLvX0cuPYCospMRKzBKtS5xYPFpsuEQwDQ"


def get_playlist_order():
    """Get playlist order. Playlist is reverse chronological (index 1 = newest)."""
    result = subprocess.run(
        [
            "yt-dlp", "--flat-playlist",
            "--print", "%(playlist_index)s\t%(id)s",
            PLAYLIST_URL,
        ],
        capture_output=True, text=True, timeout=120,
    )
    order = {}
    lines = result.stdout.strip().split("\n")
    max_idx = len(lines)
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            idx, vid = parts
            if vid not in order:
                # Convert to chronological: oldest = 1
                order[vid] = max_idx - int(idx) + 1
    return order


def extract_episode_number(title):
    """Extract the canonical episode number from the title."""
    # Try various patterns
    patterns = [
        r'\(Беседа\s+(\d+)\)?',      # (Беседа 229)
        r'[Бб]еседа\s+(\d+)',         # Беседа 207, беседа 131
        r'(\d+)\s+беседа\b',          # 148 беседа
        r'издание\s+(\d+)',            # издание 168
        r'(\d+)\s+издание\b',         # 93 издание
        r'(\d+)\s+изд\.',             # 93 изд.
        r'бр\.\s*(\d+)',              # бр. 200
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def clean_title(title):
    """Strip prefix and normalize formatting."""

    # Remove "Радио Зорана" prefix variations (including typos like Свеоглед, Свеетоглед, Светпоглед)
    patterns = [
        r'^Радио Зорана\s*-?\s*"?Све+т[оп]?оглед"?\s*с\s*(?:водещ\s+)?(?:богослова\s+)?Георги Тодоров\s*-?\s*',
        r'^Радио Зорана\s*-?\s*"?Све+т[оп]?оглед"?\s*-?\s*',
        r'^СВЕТОГЛЕД С ГЕОРГИ ТОДОРОВ\s*\|\s*',
        r'^Светоглед\s+\d+\s+',
    ]
    cleaned = title
    for pat in patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)

    # Remove inline episode number references (we'll re-add canonically)
    num_patterns = [
        r'\(Беседа\s+\d+\)?\s*',
        r'\|\s*Беседа\s+\d+\s*',
        r'издание\s+\d+\s*-?\s*',
        r'\d+\s+изд\.\s*-?\s*',
        r'[Бб]еседа\s+\d+\s*-?\s*',
        r'\d+\s+издание\s*-?\s*',
        r'\d+\s+беседа\s*-?\s*',
        r'\d+\s+БЕСЕДА\s*-?\s*',
        r'бр\.\s*\d+\s*-?\s*',
    ]
    for pat in num_patterns:
        cleaned = re.sub(pat, '', cleaned)

    # Remove "Проектът е реализиран с финансовата подкрепа на Национален фонд Култура"
    cleaned = re.sub(
        r'\s*-?\s*Проектът е реализиран с финансовата подкрепа на Национален фонд Култура',
        '', cleaned
    )

    # Fix ALL CAPS to title-like case, but carefully
    if cleaned == cleaned.upper() and len(cleaned) > 10:
        words = cleaned.split()
        result = []
        for i, word in enumerate(words):
            if i == 0:
                result.append(word[0] + word[1:].lower() if len(word) > 1 else word)
            elif word in ('И', 'В', 'НА', 'ОТ', 'ЗА', 'С', 'ПО', 'БЕЗ', 'ДО'):
                result.append(word.lower())
            elif len(word) <= 3 and word.isalpha():
                result.append(word.lower())
            else:
                result.append(word[0] + word[1:].lower() if len(word) > 1 else word)
        cleaned = ' '.join(result)

    # Clean up whitespace and punctuation artifacts
    cleaned = cleaned.strip(' -–—.,')
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = re.sub(r'\(\s*\)', '', cleaned)  # remove empty parens
    cleaned = cleaned.strip()

    # Capitalize first letter if it starts lowercase
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned


def main():
    playlist_order = get_playlist_order()
    if not playlist_order:
        print("Failed to get playlist order. Ensure yt-dlp is available.")
        return

    changes = []
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        vid = f.stem
        with open(f) as fh:
            data = json.load(fh)

        old_title = data["title"]
        ep_num = extract_episode_number(old_title)
        new_title = clean_title(old_title)

        # Re-add episode number in canonical format
        if ep_num is not None:
            new_title = f"{new_title} (Беседа {ep_num})"

        # Add playlist_order for chronological sorting
        needs_write = False

        if vid in playlist_order:
            if data.get("playlist_order") != playlist_order[vid]:
                data["playlist_order"] = playlist_order[vid]
                needs_write = True

        if new_title != old_title:
            data["title"] = new_title
            changes.append((vid, old_title, new_title))
            print(f"  {old_title}")
            print(f"  → {new_title}")
            print()
            needs_write = True

        if needs_write:
            with open(f, "w") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)

    print(f"\n{len(changes)} titles updated out of {len(list(TRANSCRIPTS_DIR.glob('*.json')))} episodes")


if __name__ == "__main__":
    main()
