#!/usr/bin/env python3
"""Fix Bulgarian language issues in a single transcript episode."""

import json
import sys
import copy
import re


def fix_transcript(data):
    """Apply corrections to transcript data, modifying both snippets and full_text."""

    # === SNIPPET-LEVEL CORRECTIONS ===
    snippet_corrections = [
        # Whisper misheard words
        ("получителни", "поучителни"),
        ("Има луцаре и императори.", "Има царе и императори."),
        ("и е завел.", "Йезавел."),
        ("Идула", "идолите"),
        ("будат телата", "бодат телата"),
        ("жръци", "жреци"),
        # Grammatical: царият -> царят
        ("царият", "царят"),
        # бездушния -> бездушният (subject position)
        ("бездушния Ваал", "бездушният Ваал"),
        # Fire FROM heaven, not TO heaven
        ("огън на небето,", "огън от небето,"),
        # затова (one word when meaning "therefore")
        ("и за това погубва", "и затова погубва"),
        # Божие -> Божие (capitalize)
        ("божие наказание", "Божие наказание"),
    ]

    for snippet in data['snippets']:
        for wrong, correct in snippet_corrections:
            if wrong in snippet['text']:
                snippet['text'] = snippet['text'].replace(wrong, correct)

    # === REBUILD FULL TEXT ===
    full_text = ' '.join(s['text'] for s in data['snippets'])

    # === FULL TEXT CORRECTIONS ===
    # Fix capitalization of Бог (God) - uppercase when referring to the Christian God
    # Pattern: lowercase "бог" not preceded by word chars (to avoid matching inside words)
    # We need to be selective: "бог Ваал" stays lowercase (false god),
    # but "истинския бог", "на бога", etc. get capitalized

    god_patterns = [
        (r'\bбог може\b', 'Бог може'),
        (r'\bбог погубил\b', 'Бог погубил'),
        (r'\bбог дарява\b', 'Бог дарява'),
        (r'\bна бога\b', 'на Бога'),
        (r'\bот бога\b', 'от Бога'),
        (r'\bедин бог\b', 'един Бог'),
        (r'\bистинския бог\b', 'истинският Бог'),
        (r'\bистинският бог\b', 'истинският Бог'),
        (r'\bслужение на бога\b', 'служение на Бога'),
    ]
    for pattern, replacement in god_patterns:
        full_text = re.sub(pattern, replacement, full_text)

    # Fix "Той се оженил за една езичница Йезавел. И построил"
    # -> proper comma usage around the name
    full_text = full_text.replace(
        "за една езичница Йезавел. И построил",
        "за една езичница, Йезавел, и построил"
    )

    # Fix intro repetition
    full_text = full_text.replace(
        "Християнски разкази за деца Християнски разкази за деца",
        "Християнски разкази за деца."
    )
    full_text = full_text.replace(
        "поучителни истории Само",
        "поучителни истории. Само"
    )
    full_text = full_text.replace(
        "радио Зорана Свети",
        "радио \u201eЗорана\u201c. Свети"
    )

    # Add direct speech punctuation
    # "Той му казал, заповядай..." -> "Той му казал: \u201eЗаповядай..."
    full_text = full_text.replace(
        "Той му казал, заповядай",
        "Той му казал: \u201eЗаповядай"
    )
    full_text = full_text.replace(
        "и жреците. Царят",
        "и жреците.\u201c Царят"
    )
    full_text = full_text.replace(
        "Илия предложил, нека",
        "Илия предложил: \u201eНека"
    )
    # Close the quote after "той е истинският Бог."
    full_text = full_text.replace(
        "истинският Бог. Така и направили.",
        "истинският Бог.\u201c Така и направили."
    )
    full_text = full_text.replace(
        "и се помолил така. Господи,",
        "и се помолил така: \u201eГосподи,"
    )
    full_text = full_text.replace(
        "истинският Бог. В същия",
        "истинският Бог.\u201c В същия"
    )
    full_text = full_text.replace(
        "и извикал. Богът,",
        "и извикал: \u201eБогът,"
    )
    full_text = full_text.replace(
        "истинският Бог. Тогава пророк",
        "истинският Бог.\u201c Тогава пророк"
    )

    # Add period after "Свети пророк Илия" (title heading)
    # This appears as a heading in the intro
    full_text = full_text.replace(
        "\u201c. Свети пророк Илия Има",
        "\u201c. Свети пророк Илия. Има"
    )

    data['full_text'] = full_text
    return data


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'transcripts/gGhf8HSSGwI.json'

    with open(filepath, 'r') as f:
        data = json.load(f)

    original_text = data['full_text']
    data = fix_transcript(data)

    with open(filepath, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Fixed: {filepath}")
    print(f"\n=== CORRECTED FULL TEXT ===")
    print(data['full_text'])


if __name__ == '__main__':
    main()
