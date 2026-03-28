#!/usr/bin/env python3
"""
Fix systematic speech-to-text errors in Bulgarian Orthodox Christian transcripts.

This script corrects common Whisper transcription errors found across 284 episodes
of the Светоглед podcast. Corrections are applied to both individual transcript
JSON files and the combined transcript file.

Categories of fixes:
1. Orthodox terminology (стойна война → световна война, etc.)
2. Proper names (Кирида Методия → Кирил и Методий, etc.)
3. Word merging errors (Климентохридски → Климент Охридски, etc.)
4. Speech-to-text artifacts (doubled words, corrupted syllables)
5. Bulgarian vs Russian spelling normalization
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
COMBINED_FILE = Path(__file__).parent / "transcripts_combined.json"
FULL_TEXT_FILE = Path(__file__).parent / "transcripts_full_text.txt"

# ─── REPLACEMENT RULES ───────────────────────────────────────────────────────
# Each rule is (pattern, replacement, description)
# Rules are applied in order. Use regex patterns where needed.

# Case-sensitive replacements (exact string matching)
EXACT_REPLACEMENTS = [
    # ── Orthodox terminology ──
    ("стойна война", "световна война", "World War - systematic Whisper mishearing"),
    ("Стойна война", "Световна война", "World War - capitalized"),
    ("СВЕТОГЛЕТ", "СВЕТОГЛЕД", "Show name corrupted (uppercase)"),
    ("Светоглет", "Светоглед", "Show name corrupted (capitalized)"),
    ("светоглет", "светоглед", "Show name corrupted (lowercase)"),

    # ── Лишен от сан (defrocked) ──
    ("Лишен от сам", "Лишен от сан", "Ecclesiastical term: defrocked"),
    ("лишен от сам", "лишен от сан", "Ecclesiastical term: defrocked (lowercase)"),

    # ── равноапостол (equal-to-the-apostles) ──
    ("ръвно апостол", "равноапостол", "Equal-to-apostles title"),
    ("ръвно апостола", "равноапостола", "Equal-to-apostles title (definite)"),
    ("ръвно апостолство", "равноапостолство", "Equal-to-apostles (abstract noun)"),
    ("Ръвно апостол", "Равноапостол", "Equal-to-apostles title (capitalized)"),

    # ── Saints and Church Fathers ──
    ("Свети Оан Златолуст", "Свети Йоан Златоуст", "St. John Chrysostom"),
    ("Свети Оан Золото", "Свети Йоан Златоуст", "St. John Chrysostom (corrupted)"),
    ("свети Оан Златолуст", "свети Йоан Златоуст", "St. John Chrysostom (lowercase)"),
    ("Григорий Двояслов", "Григорий Двоеслов", "Gregory the Dialogist - correct Bulgarian title"),
    ("Климентохридски", "Климент Охридски", "St. Clement of Ohrid - merged words"),
    ("климентохридски", "Климент Охридски", "St. Clement of Ohrid - merged words (lowercase)"),
    ("Св. Кирида Методия", "Св. Кирил и Методий", "Sts. Cyril and Methodius (corrupted)"),
    ("Кирида Методия", "Кирил и Методий", "Cyril and Methodius (corrupted)"),
    ("Кида Методи", "Кирил и Методий", "Cyril and Methodius (severely corrupted)"),
    ("Кирилми Методий", "Кирил и Методий", "Cyril and Methodius (merged)"),
    ("Кирилми методий", "Кирил и Методий", "Cyril and Methodius (merged, lowercase)"),
    ("Свети Нум", "Свети Наум", "St. Naum - missing letter"),
    ("свети Нум", "свети Наум", "St. Naum - missing letter (lowercase)"),

    # ── Bulgarian vs Russian spelling normalization ──
    # The host's name should be Bulgarian form
    ("Георгий Тодоров", "Георги Тодоров", "Host name - Bulgarian spelling"),

    # ── Word doubling artifacts ──
    ("ще ще ", "ще ", "Doubled modal verb"),
    ("ще ше ", "ще ", "Doubled modal verb (variant)"),

    # ── васалност (vassalage) ──
    ("въсълност", "васалност", "Vassalage - corrupted"),
    ("въсълността", "васалността", "Vassalage (definite) - corrupted"),
]

# Regex-based replacements for more complex patterns
REGEX_REPLACEMENTS = [
    # Fix "вместоистина" → "вместо истина" (word merging in specific context)
    (r"вместоистина", "вместо-истина", "Word merging: вместо + истина"),
    (r"Вместоистина", "Вместо-истина", "Word merging: вместо + истина (capitalized)"),

    # Normalize Исус → Иисус (correct Orthodox form)
    # "Иисус" is the proper Church Slavonic/Orthodox form used in Bulgarian tradition
    # Whisper sometimes drops the double И
    (r"(?<![И])Исус", "Иисус", "Orthodox standard: Иисус (restore dropped И)"),

    # Fix "Святи" → "Свети" (Russian → Bulgarian)
    (r"(?<!\w)Святи(?=\s)", "Свети", "Russian → Bulgarian: Святи → Свети"),
]


def apply_corrections(text: str) -> tuple[str, list[str]]:
    """Apply all corrections to a text string. Returns (corrected_text, list of changes made)."""
    changes = []

    # Apply exact replacements
    for old, new, desc in EXACT_REPLACEMENTS:
        if old in text:
            count = text.count(old)
            text = text.replace(old, new)
            changes.append(f"  [{count}x] {desc}: '{old}' → '{new}'")

    # Apply regex replacements
    for pattern, replacement, desc in REGEX_REPLACEMENTS:
        matches = re.findall(pattern, text)
        if matches:
            count = len(matches)
            text = re.sub(pattern, replacement, text)
            changes.append(f"  [{count}x] {desc}")

    return text, changes


def fix_transcript_file(filepath: Path, dry_run: bool = False) -> dict:
    """Fix a single transcript JSON file. Returns stats about changes made."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_changes = []
    snippets_changed = 0

    # Fix snippets
    for snippet in data.get("snippets", []):
        original = snippet["text"]
        corrected, changes = apply_corrections(original)
        if corrected != original:
            if not dry_run:
                snippet["text"] = corrected
            snippets_changed += 1
            all_changes.extend(changes)

    # Fix full_text
    if "full_text" in data:
        original_full = data["full_text"]
        corrected_full, full_changes = apply_corrections(original_full)
        if corrected_full != original_full:
            if not dry_run:
                data["full_text"] = corrected_full
            all_changes.extend([f"  [full_text] {c.strip()}" for c in full_changes])

    # Fix title
    if "title" in data:
        original_title = data["title"]
        corrected_title, title_changes = apply_corrections(original_title)
        if corrected_title != original_title:
            if not dry_run:
                data["title"] = corrected_title
            all_changes.extend([f"  [title] {c.strip()}" for c in title_changes])

    # Write back
    if all_changes and not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {
        "file": filepath.name,
        "snippets_changed": snippets_changed,
        "changes": all_changes,
    }


def rebuild_combined_files():
    """Rebuild transcripts_combined.json and transcripts_full_text.txt from individual files."""
    all_transcripts = []
    full_text_parts = []

    for filepath in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            all_transcripts.append(data)

            # Build full text entry
            title = data.get("title", filepath.stem)
            video_id = data.get("video_id", filepath.stem)
            full_text = data.get("full_text", "")
            full_text_parts.append(f"=== {title} ({video_id}) ===\n{full_text}\n")

    # Write combined JSON
    with open(COMBINED_FILE, "w", encoding="utf-8") as f:
        json.dump(all_transcripts, f, ensure_ascii=False, indent=2)
    print(f"Rebuilt {COMBINED_FILE} ({len(all_transcripts)} transcripts)")

    # Write full text
    with open(FULL_TEXT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(full_text_parts))
    print(f"Rebuilt {FULL_TEXT_FILE}")


def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    skip_combined = "--skip-combined" in sys.argv

    if dry_run:
        print("=== DRY RUN MODE — no files will be modified ===\n")

    print(f"Processing transcripts in {TRANSCRIPTS_DIR}...\n")

    files_changed = 0
    total_snippet_changes = 0
    change_summary = defaultdict(int)

    for filepath in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        result = fix_transcript_file(filepath, dry_run=dry_run)

        if result["changes"]:
            files_changed += 1
            total_snippet_changes += result["snippets_changed"]

            if verbose:
                print(f"\n{result['file']}:")
                for change in result["changes"]:
                    print(change)

            # Aggregate change descriptions
            for change in result["changes"]:
                # Extract description part
                parts = change.strip().split("] ", 1)
                if len(parts) > 1:
                    change_summary[parts[1]] += 1

    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"Files processed: {len(list(TRANSCRIPTS_DIR.glob('*.json')))}")
    print(f"Files with changes: {files_changed}")
    print(f"Snippets corrected: {total_snippet_changes}")
    print(f"\nCorrection breakdown:")
    for desc, count in sorted(change_summary.items(), key=lambda x: -x[1]):
        print(f"  {count:4d}x  {desc}")

    if not dry_run and not skip_combined and files_changed > 0:
        print(f"\nRebuilding combined files...")
        rebuild_combined_files()

    if dry_run:
        print(f"\n(Dry run - no files were modified. Run without --dry-run to apply.)")


if __name__ == "__main__":
    main()
