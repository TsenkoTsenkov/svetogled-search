#!/usr/bin/env python3
"""Apply Bulgarian language corrections to Whisper-generated Svetogled transcripts.

Focuses on common recurring Whisper errors, Bulgarian Orthodox terminology,
capitalization of divine names, and preposition doubling rules.
"""

import json
import re
import sys


# Literal replacements (word/phrase level). Applied to each snippet.
LITERAL_REPLACEMENTS = [
    # --- Common Whisper mishearings ---
    ("получителни", "поучителни"),
    ("човекотворни", "ръкотворни"),
    ("жръци", "жреци"),
    ("идули", "идоли"),
    ("Идула", "идолите"),
    ("злъбочаваме", "задълбочаваме"),
    ("вълдълбочина", "в дълбочина"),
    ("борадим", "боравим"),
    ("коммунистите", "комунистите"),
    ("коммунизма", "комунизма"),
    ("коммунизъм", "комунизъм"),
    ("изкуствени интелект", "изкуствен интелект"),
    ("свръх изкуствени интелект", "свръхизкуствен интелект"),
    ("свръхизкуствени интелект", "свръхизкуствен интелект"),
    ("един свръх изкуствен", "един свръхизкуствен"),
    ("станопис", "стенопис"),
    ("Зогравски", "Зографски"),
    ("зогравски", "зографски"),
    ("кулмидацията", "кулминацията"),
    ("Кулмидацията", "Кулминацията"),
    ("свет и пимен", "Свети Пимен"),
    ("Свет и пимен", "Свети Пимен"),
    ("свети пимен", "Свети Пимен"),
    ("Свети пимен", "Свети Пимен"),
    ("светоста", "светостта"),
    ("светлостта", "светостта"),
    ("побърквам", "подражавам"),
    ("подръжавам", "подражавам"),
    ("видикат", "издигат"),
    ("не ме е интересува", "не ме интересува"),
    ("понеже центъра", "понеже центърът"),
    ("център на коммунизма", "центърът на комунизма"),
    ("центъра на комунизма", "центърът на комунизма"),
    ("се захвани", "се захване"),
    ("не е мало", "няма"),
    ("не е мало кой", "няма кой"),
    ("по-ре-лефен", "по-релефен"),
    ("400 година", "1940 година"),
    ("да кажем 400 година", "да кажем 1940 година"),
    ("след 17-та година", "след 1917-а година"),
    ("до 12-та година", "до 1912-а година"),
    ("русофилски период на Стамболов", "русофилски период след Стамболов"),
    ("глупово", "глупаво"),
    ("Първ поглед", "На пръв поглед"),
    ("имам някакъв критерий", "имаме някакъв критерий"),
    ("ние трябва да имам", "ние трябва да имаме"),
    ("Емелян Погачов", "Емелян Пугачов"),
    ("Пугачов", "Пугачов"),
    ("и аз стигне, и аз не стигне", "и аз да стигна, и аз да не стигна"),
    ("Който и аз стигне", "Който и аз да стигна"),

    # --- Biblical/theological corrections ---
    (" Исус", " Иисус"),
    ("(Исус", "(Иисус"),
    ("Исус Христос", "Иисус Христос"),
    ("Исусе", "Иисусе"),
    ("Исуса", "Иисуса"),
    ("и е завел", "Йезавел"),
    ("И е Завел", "Йезавел"),

    # --- Grammar: definite article full form for subjects in common cases ---
    ("царият", "царят"),
    ("Царият", "Царят"),
    ("бездушния Ваал", "бездушният Ваал"),

    # --- Punctuation: затова (therefore, one word) in common phrases ---
    ("и за това ние", "и затова ние"),
    ("И за това ние", "И затова ние"),
    ("и за това може", "и затова може"),
    ("И за това може", "И затова може"),
    ("и за това тези", "и затова тези"),
    ("И за това тези", "И затова тези"),
    ("И за това е светец", "И затова е светец"),
    ("и за това е светец", "и затова е светец"),
    ("За това един естествен", "Затова един естествен"),
    ("за това един естествен", "затова един естествен"),
    ("Точно за това тези", "Точно затова тези"),
    ("точно за това тези", "точно затова тези"),
    ("За това имам", "Затова имам"),
    ("за това имам", "затова имам"),
    ("За това трябва", "Затова трябва"),
    ("за това трябва", "затова трябва"),
    ("и за това може да кажем", "и затова може да кажем"),
    ("И за това може да кажем", "И затова може да кажем"),

    # (preposition doubling handled in REGEX_REPLACEMENTS with \b boundaries
    # to avoid mangling already-correct forms like "във всяко")

    # --- Common orthography ---
    ("представлявате всъщност", "представлява всъщност"),
    ("сега нататък", "и така нататък"),
]


# Regex replacements (applied to full_text and each snippet text)
REGEX_REPLACEMENTS = [
    # Capitalize Бог when referring to the Christian God (context-sensitive)
    (r"\bна бога\b", "на Бога"),
    (r"\bот бога\b", "от Бога"),
    (r"\bкъм бога\b", "към Бога"),
    (r"\bза бога\b", "за Бога"),
    (r"\bв бога\b", "в Бога"),
    (r"\bистинския бог\b", "истинският Бог"),
    (r"\bистинският бог\b", "истинският Бог"),
    (r"\bедин бог\b", "един Бог"),
    (r"\bединия бог\b", "единият Бог"),
    (r"\bединият бог\b", "единият Бог"),
    (r"\bбог дарява\b", "Бог дарява"),
    (r"\bбог може\b", "Бог може"),
    (r"\bбог погубил\b", "Бог погубил"),
    (r"\bбог е\b", "Бог е"),
    (r"\bбог не\b", "Бог не"),
    (r"\bпсевдо-бог\b", "псевдобог"),
    (r"\bпсевдо бог\b", "псевдобог"),

    # Божи/Божия/Божие etc. - always capitalize
    (r"\bбожий\b", "Божий"),
    (r"\bбожия\b", "Божия"),
    (r"\bбожието\b", "Божието"),
    (r"\bбожията\b", "Божията"),
    (r"\bбожие\b", "Божие"),
    (r"\bбожи\b", "Божи"),

    # Църквата when meaning "the Church" institution (after тази/нашата/Христовата)
    (r"\b(Христовата|Христовите|Светата) църква\b", r"\1 Църква"),
    (r"\b(Христовата|Христовите|Светата) църкви\b", r"\1 Църкви"),

    # Свети + saint name: capitalize
    (r"\bсвети Пимен\b", "Свети Пимен"),
    (r"\bсвети Илия\b", "Свети Илия"),
    (r"\bсвети Николай\b", "Свети Николай"),
    (r"\bсвети Иван\b", "Свети Иван"),
    (r"\bсв\. ([А-ЯЁ])", r"св. \1"),

    # Preposition doubling (regex-based)
    (r"\bв (в[а-я])", r"във \1"),
    (r"\bВ (в[а-я])", r"Във \1"),
    (r"\bв (ф[а-я])", r"във \1"),
    (r"\bВ (ф[а-я])", r"Във \1"),
    (r"\bс (с[а-я])", r"със \1"),
    (r"\bС (с[а-я])", r"Със \1"),
    (r"\bс (з[а-я])", r"със \1"),
    (r"\bС (з[а-я])", r"Със \1"),

    # Normalize double spaces
    (r"[ ]{2,}", " "),
    (r" ,", ","),
    (r" \.", "."),
]

# Fixes that should only be applied at full-text level (cross-snippet)
FULL_TEXT_ONLY = [
    # Fix split proper names & direct speech
    ("Деус екс махина", "Deus ex machina"),
    ("Деус Екс Махина", "Deus ex machina"),
    # The above replacement in LITERAL would also apply but we want the Latin form here
    # Common duplication in intros (Whisper artifact)
    ("Започва Светоглед Започва Светоглед", "Започва Светоглед."),
    ("ЗАПОЧВА СВЕТОГЛЕД Започва Светоглед", "Започва Светоглед"),
    ("Радио Зорана Представя Светоглед", "Радио Зорана представя „Светоглед“"),
    ("радио Зорана", "Радио „Зорана“"),
    ("Радио Зорана", "Радио „Зорана“"),
    ("Радио „„Зорана“", "Радио „Зорана“"),
    ("„Зорана“\u201c", "„Зорана“"),
]


def correct_text(text: str) -> str:
    """Apply literal then regex replacements to a piece of text."""
    for wrong, right in LITERAL_REPLACEMENTS:
        if wrong in text:
            text = text.replace(wrong, right)
    for pattern, repl in REGEX_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    return text


def correct_full_text(text: str) -> str:
    text = correct_text(text)
    for wrong, right in FULL_TEXT_ONLY:
        text = text.replace(wrong, right)
    # Collapse any extra whitespace that may have been introduced
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def fix_transcript(data: dict) -> dict:
    for snippet in data.get("snippets", []):
        snippet["text"] = correct_text(snippet["text"])
    # Rebuild full_text from corrected snippets, then apply cross-snippet fixes
    full = " ".join(s["text"] for s in data["snippets"])
    data["full_text"] = correct_full_text(full)
    return data


def main():
    for path in sys.argv[1:]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = fix_transcript(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Fixed: {path}")


if __name__ == "__main__":
    main()
