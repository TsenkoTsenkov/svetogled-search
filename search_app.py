#!/usr/bin/env python3
"""
Светоглед Transcript Search — full-featured research tool.

Usage:
    python search_app.py
    Then open http://localhost:8080
"""

import gzip
import json
import os
import re
from collections import Counter
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

PORT = int(os.environ.get("PORT", 8080))
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
HTML_FILE = Path(__file__).parent / "index.html"


def _minify_html(html_bytes):
    """Lightweight minification: collapse whitespace in CSS/JS, strip HTML comments."""
    text = html_bytes.decode("utf-8")
    # Remove HTML comments (but not conditional comments)
    text = re.sub(r'<!--(?!\[).*?-->', '', text, flags=re.DOTALL)
    # Collapse runs of whitespace (spaces/tabs) into single space, preserve newlines
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove whitespace around newlines
    text = re.sub(r' ?\n ?', '\n', text)
    # Collapse multiple blank lines into one
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.encode("utf-8")


# Count episodes at startup (excluding duplicates by segment count)
def _get_duration(data):
    """Get episode duration in seconds from the last segment's start time."""
    snippets = data.get("snippets") or data.get("segments", [])
    if snippets:
        return snippets[-1].get("start", 0)
    return 0


def _is_reupload(dur_a, dur_b):
    """Two episodes with same number are re-uploads if durations are within 5%."""
    if dur_a == 0 or dur_b == 0:
        return False
    return abs(dur_a - dur_b) / max(dur_a, dur_b) < 0.05


def _count_episodes():
    seen = {}
    count = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        n = data.get("episode_number", 0)
        dur = _get_duration(data)
        if n in seen and _is_reupload(seen[n], dur):
            continue  # skip re-upload
        seen[n] = dur
        count += 1
    return count

EPISODE_COUNT = _count_episodes()

# Pre-minify at startup, inject dynamic episode count
def _prepare_html():
    if not HTML_FILE.exists():
        return b""
    html = HTML_FILE.read_bytes()
    html = html.replace(b"{{EPISODE_COUNT}}", str(EPISODE_COUNT).encode())
    return _minify_html(html)

_MINIFIED_HTML = _prepare_html()

STOP_WORDS = set("""
и в на от за с по към до при без между със
се е са бе да не ни че ще ли бъде бъдат била било били
но как какво кой кога защо когато защото тоест обаче
те ги тя той то ние вие нас вас тях него нея нему
този тази това тези онзи онази онова някой някоя някое някои
един една едно едни
има няма може нито нищо никога никой
съм си сте сме бях бяха бяхме
ако или още все пък дори нито
като също така тук там където
който която което които чието
вече сега после преди докато
може могат съвсем съответно
значи казва казват също
много всичко всеки всяка свой своя своите своята
какъв каква какви
само вече нали именно просто
друг друга другия другата другите другото
първо второ трето
ами ама нека нали хайде ето
тогава после после затова оттам оттук
ината ният ната ните ият ото ата
между повече малко горе долу вътре отвън
него нея нему тях техен техни
върху срещу чрез около след преди
начин начина начинът случай случая
време времето години годината годишен
прави правят правим правите
беше бяха бяхме
кажем казвам казваме
наистина напълно донякъде
може могат можем
някакъв някаква някакви някъде
обаче въпреки разбира
точно абсолютно
нататък
тоест примерно
продължим продължим продължаваме продължават
въпрос въпроса въпросът
отношение отношението
момент момента моментът
страна страната
част частта
важно важен важна
голям голяма големия голямата
такъв такава такива такова
нещо неща нещата
хора хората
""".split())

# Words that look capitalized but are not real names
STOP_NAMES = set("""
България Защото Тоест Дима Субтитри Torzok Същността
Абонирайте Всички Ами След Първо Нека Обаче
Почти Тогава Примерно Точно Както Дали Нещо
Ето Трябва Започва Светоглед Предаването
Здравейте Имаме Темата Беседа Днешната Имало
Виждаме Казва Казват Казваме Говори Говорим
Например Разбира Продължаваме Продължава
Тоест Значи Всъщност Навсякъде Въпреки
Наистина Естествено Следващ Следващата
Виждаме Минимум Максимум Повечето
Днес Вчера Утре Много Малко Повече
Цялата Целия Целият Голямата Големия
Направи Направил Направиха Направили
Случай Случая Начало Началото Момент
Въпрос Въпроса Отговор Отговора
Предаване Предаването Тема Темата
Добре Лошо Освен Втората Второто Втория
Къде Кога Какво Защо Откъде Докъде
Нямаме Нямат Имаме Имат
Първата Първия Първото Третата Третия
Последната Последния Последното
Някога Никога Сякаш Впрочем Навярно
Виждам Виждаме Мислим Мислят Мисля
Тъкмо Донякъде Засега Междувпрочтем
Сигурно Понеже Макар Ясно Истина
Трябваше Случи Получи Стана Станал
Знаем Знаят Правя Дойде Дойдат
Пита Питам Оказва Живот Живота
Георги Тодоров
Поради През Винаги Става Иначе Българската
Значи Всъщност Затова Оттук Оттам
Докато Обикновено Следователно Разбираме
Западна Западната Западния Източна Източната
Голяма Големия Малка Малката Нова Новата Стара Старата
Различни Определено Основно Нашата Нашия Своята Своя
Дори Напротив Обратно Между Преди Днешен
Самия Самата Цялата Целия Единствено
Трета Четвърта Хиляди Милиони
Какви Колко Кому Тъй Чак
Ставаше Стане Стават Може Могат
Повече Отново Вътре Горе Долу
Имаше Други Другия Другата Друго
Зорана Радио
Включително Новото Крайна Божието
Стига Ясна Вижда Минава Погледнем
Dima Torzok Субтитри
Тука Поначало Фактически Вероятно Особено Изобщо
Каквото Същото Негова Неговият Велики
Второто Втори Втория Второ
Тодор Човек Стария
Високо Главно Обратно Огромна
Решава Случило Смятат Остане Негово Казваше
Действително Обикновено Историческо Създават
Изключение Правиш
""".split())

# Common Bulgarian verb forms and generic words to exclude from concepts
STOP_CONCEPTS = set("""
направи направиха направил направим направили
същия същият същата същото същите
почти просто наистина напълно донякъде
никакъв никаква никакви
неговото неговия неговата неговите
нейното нейния нейната нейните
техните тяхното нашите нашата нашия
някакъв някаква някакви
когато отколкото
въпреки въпросът
другите другата другия другото
всъщност
трябва трябваше
означава означавало
например
години годината годишен
останал останала останали
започва започваме започнал
получава получи получили
различни различен различна
определен определена определено
истината истинския истинската
момента моментът
поради именно
разказва разказват
написал написали написана
постоянно специално
казвам казваме казвате казват
вероятно
следва следват следващ
голяма голямата големия
означава означавало
отношение отношението
продължава продължаваме продължават
никога никъде
събор събора
подобни подобно случайно
първите вторите третите
мислене мисълта
посока посоката
струва стигнал стигне
веднага донякъде
живеем живота живее живял
повечето повече
откъде останало говорят смятаме искаме
разбираме представим виждат
работата големите останали
говорим говорят говори
минава погледнем напротив съжаление
приема западна световна
""".split())


def _is_likely_verb_or_filler(word):
    """Heuristic: Bulgarian verbs and fillers end with specific suffixes."""
    w = word.lower()
    # Common verb endings
    verb_suffixes = (
        'ва', 'ват', 'вам', 'ваме', 'вате', 'ваш', 'вай',
        'ше', 'ша', 'шем',
        'ме', 'те', 'ли', 'ло', 'ла',
        'ем', 'ете', 'ат', 'ят',
        'им', 'ите',
        'ах', 'яхме', 'яхте',
        'ъл', 'ала', 'али', 'ало',
        'де',  # създаде, направиде
        'жа', 'жат',  # държа, държат
    )
    # Adjective/pronoun/adverb endings (generic filler words)
    filler_suffixes = (
        'ски', 'ска', 'ско',
        'чки', 'чка', 'чко',
        'чно', 'лно', 'тно',
        'ово', 'ево',
        'ия', 'ият',  # втория, старият
        'ата', 'ото', 'ите',  # главата, другото, другите
        'акво', 'якво',  # никакво, какво
        'якъв', 'акъв',  # никакъв, всякакъв
        'ови', 'ови',  # негови, духови
        'виш', 'вим',  # правиш, правим
        'дна', 'дно',  # гледна, гледно
        'ани',          # свързани, написани
        'ени',          # решени, получени
        'бни',          # подобни
        'жни',          # възможни
    )

    if w.endswith(verb_suffixes):
        return True
    if w.endswith(filler_suffixes) and len(w) < 12:
        return True
    return False


def _is_proper_noun(word):
    """Check if a word is likely a proper noun (person, place, concept name)."""
    # Must start with uppercase
    if not word[0].isupper():
        return False
    # Skip words that are common Bulgarian sentence starters
    if word in STOP_NAMES:
        return False
    if word.lower() in STOP_WORDS:
        return False
    # Very short words are usually not names
    if len(word) < 4:
        return False
    return True


def build_topics():
    """Analyze transcripts for meaningful names and concepts using smarter filtering."""
    import math

    name_episode_count = Counter()
    concept_episode_count = Counter()
    total_episodes = max(1, sum(1 for _ in TRANSCRIPTS_DIR.glob("*.json")))

    for f in TRANSCRIPTS_DIR.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        text = data.get("full_text", "")

        # Names: capitalized words, deduplicated per episode
        cap_words = set(re.findall(r'[А-ЯA-Z][а-яa-z]{3,}', text))
        for w in cap_words:
            if _is_proper_noun(w):
                name_episode_count[w] += 1

        # Concepts: only nouns (skip verbs, adjectives, adverbs via suffix heuristic)
        words = set(re.findall(r'[а-я]{6,}', text.lower()))
        for w in words:
            if (w not in STOP_WORDS
                    and w not in STOP_CONCEPTS
                    and not _is_likely_verb_or_filler(w)):
                concept_episode_count[w] += 1

    # Names: appear in 3+ episodes, not too common (>60% is generic like "Бог")
    names = [(w, c) for w, c in name_episode_count.most_common(500)
             if 3 <= c <= total_episodes * 0.6]
    names.sort(key=lambda x: -x[1])

    # Concepts: use TF-IDF-like scoring — penalize terms that appear everywhere
    name_lower = {w.lower() for w, _ in names}
    scored_concepts = []
    for w, doc_count in concept_episode_count.most_common(1000):
        if (w in name_lower or w in STOP_WORDS or w in STOP_CONCEPTS
                or _is_likely_verb_or_filler(w)):
            continue
        # IDF: rare terms score higher
        idf = math.log(total_episodes / max(1, doc_count))
        # Only keep terms that appear in 3+ but < 40% of episodes
        if 3 <= doc_count <= total_episodes * 0.4:
            scored_concepts.append((w, doc_count, doc_count * idf))

    scored_concepts.sort(key=lambda x: -x[2])  # Sort by TF-IDF score

    return [
        {"category": "Имена и лица",
         "items": [{"term": w, "count": c} for w, c in names[:50]]},
        {"category": "Понятия и теми",
         "items": [{"term": w, "count": c} for w, c, _ in scored_concepts[:50]]},
    ]


def _html_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _format_timestamp(seconds):
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _render_episode_page(data):
    video_id = data["video_id"]
    title = _html_escape(data["title"])
    segment_count = data.get("segment_count", 0)
    snippets = data.get("snippets", [])
    yt_url = f"https://www.youtube.com/watch?v={video_id}"

    # Build transcript segments with timestamp data
    segments_data = []
    for s in snippets:
        segments_data.append({
            "text": s["text"],
            "start": int(s["start"]),
            "ts": _format_timestamp(s["start"]),
        })

    segments_json = json.dumps(segments_data, ensure_ascii=False)

    # Build static HTML paragraphs for SEO (no JS needed for crawlers)
    seo_paragraphs = []
    chunk = []
    for i, s in enumerate(snippets):
        chunk.append(_html_escape(s["text"]))
        if (i + 1) % 15 == 0:
            seo_paragraphs.append("<p>" + " ".join(chunk) + "</p>")
            chunk = []
    if chunk:
        seo_paragraphs.append("<p>" + " ".join(chunk) + "</p>")
    seo_html = "\n".join(seo_paragraphs)

    # First 300 chars of text for meta description
    full_text = data.get("full_text", "")
    desc_text = full_text[:300].replace('"', "'").replace("\n", " ").strip()
    if len(full_text) > 300:
        desc_text += "..."

    return f"""<!DOCTYPE html>
<html lang="bg">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Светоглед с Георги Тодоров</title>
    <meta name="description" content="{_html_escape(desc_text)}">
    <link rel="canonical" href="https://svetogled-arhiv.com/episode/{video_id}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="https://svetogled-arhiv.com/episode/{video_id}">
    <meta property="og:title" content="{title} — Светоглед">
    <meta property="og:description" content="{_html_escape(desc_text)}">
    <meta property="og:locale" content="bg_BG">
    <meta property="og:site_name" content="Светоглед Архив">
    <meta property="og:image" content="https://img.youtube.com/vi/{video_id}/hqdefault.jpg">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:image" content="https://img.youtube.com/vi/{video_id}/hqdefault.jpg">
    <script type="application/ld+json">
    {{
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": "{title}",
        "url": "https://svetogled-arhiv.com/episode/{video_id}",
        "description": "{_html_escape(desc_text)}",
        "associatedMedia": {{
            "@type": "VideoObject",
            "name": "{title}",
            "description": "{_html_escape(desc_text)}",
            "embedUrl": "https://www.youtube.com/embed/{video_id}",
            "thumbnailUrl": "https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "uploadDate": "{data.get('upload_date', '2024-01-01')}",
            "contentUrl": "https://www.youtube.com/watch?v={video_id}"
        }},
        "partOfSeries": {{
            "@type": "PodcastSeries",
            "name": "Светоглед",
            "author": {{
                "@type": "Person",
                "name": "Георги Тодоров"
            }},
            "publisher": {{
                "@type": "RadioStation",
                "name": "Радио Зорана"
            }}
        }},
        "inLanguage": "bg"
    }}
    </script>
    <style>
        :root {{
            --bg: #0a0a0e;
            --bg-card: #161218;
            --accent: #c8994c;
            --accent2: #d4a853;
            --wine: #6b2038;
            --text: #e8e4e0;
            --text-dim: #8a8078;
            --text-dimmer: #6a6060;
            --border: #2a2228;
            --gold: #c8994c;
            --radius: 16px;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        ::selection {{ background: rgba(200, 153, 76, 0.35); color: #fff; }}
        ::-moz-selection {{ background: rgba(200, 153, 76, 0.35); color: #fff; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }}
        @media (min-width: 1024px) {{
            html {{ zoom: 1.3; }}
        }}
        .sacred-bg {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            pointer-events: none;
            z-index: 0;
        }}
        .sacred-bg img {{
            position: absolute;
            filter: sepia(20%) brightness(1.15) saturate(0.6);
        }}
        .sacred-bg .icon-christ {{
            top: 0; left: 50%;
            transform: translateX(-50%);
            width: 600px; height: auto;
            opacity: 0.35;
            filter: sepia(20%) brightness(1.1) saturate(0.5);
            mask-image: radial-gradient(ellipse 85% 65% at 50% 35%, rgba(0,0,0,0.9) 0%, transparent 70%);
            -webkit-mask-image: radial-gradient(ellipse 85% 65% at 50% 35%, rgba(0,0,0,0.9) 0%, transparent 70%);
        }}
        .sacred-bg .icon-theotokos {{
            top: 35%; left: 2%;
            width: 300px; height: auto;
            opacity: 0.38;
            filter: sepia(20%) brightness(1.2) saturate(0.6);
            mask-image: radial-gradient(ellipse 75% 70% at center, rgba(0,0,0,0.85) 0%, transparent 72%);
            -webkit-mask-image: radial-gradient(ellipse 75% 70% at center, rgba(0,0,0,0.85) 0%, transparent 72%);
        }}
        .sacred-bg .icon-topright-mirror {{
            top: 0; left: 2%;
            width: 500px; height: auto;
            opacity: 0.30;
            filter: sepia(20%) brightness(1.15) saturate(0.6);
            transform: scaleX(-1);
            mask-image: radial-gradient(ellipse 80% 70% at center, rgba(0,0,0,0.8) 0%, transparent 72%);
            -webkit-mask-image: radial-gradient(ellipse 80% 70% at center, rgba(0,0,0,0.8) 0%, transparent 72%);
        }}
        .sacred-bg .icon-topleft {{
            top: 0; right: 2%;
            width: 500px; height: auto;
            opacity: 0.30;
            filter: sepia(20%) brightness(1.15) saturate(0.6);
            mask-image: radial-gradient(ellipse 80% 70% at center, rgba(0,0,0,0.8) 0%, transparent 72%);
            -webkit-mask-image: radial-gradient(ellipse 80% 70% at center, rgba(0,0,0,0.8) 0%, transparent 72%);
        }}
        .sacred-bg .icon-george {{
            bottom: 5%; right: 2%;
            width: 260px; height: auto;
            opacity: 0.35;
            filter: sepia(25%) brightness(1.15) saturate(0.5);
            mask-image: radial-gradient(ellipse 80% 80% at center, rgba(0,0,0,0.85) 0%, transparent 75%);
            -webkit-mask-image: radial-gradient(ellipse 80% 80% at center, rgba(0,0,0,0.85) 0%, transparent 75%);
        }}
        .sacred-bg .glow {{
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background:
                radial-gradient(ellipse 600px 700px at 50% 30%, rgba(200, 153, 76, 0.04) 0%, transparent 70%),
                radial-gradient(ellipse 400px 500px at 5% 50%, rgba(107, 32, 56, 0.05) 0%, transparent 70%),
                radial-gradient(ellipse 400px 400px at 95% 70%, rgba(200, 153, 76, 0.03) 0%, transparent 60%);
        }}
        body > *:not(.sacred-bg):not(.reader-overlay) {{ position: relative; z-index: 1; }}
        .ep-header {{
            border-bottom: 1px solid rgba(200, 153, 76, 0.15);
            padding: 16px 20px 14px;
            background: transparent;
            text-align: center;
        }}
        .ep-header-title {{
            font-size: 15px;
            font-weight: 600;
            color: var(--gold);
            text-shadow: 0 0 30px rgba(218, 165, 32, 0.2);
            margin-bottom: 3px;
            letter-spacing: 0.5px;
        }}
        .ep-header-sub {{
            font-size: 11px;
            color: var(--text-dim);
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        .back {{
            display: inline-block;
            color: var(--accent);
            text-decoration: none;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .back:hover {{ text-decoration: underline; }}
        h1 {{
            font-size: 22px;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .meta {{
            color: var(--text-dim);
            font-size: 13px;
            margin-bottom: 20px;
        }}
        .meta a {{ color: var(--accent); text-decoration: none; }}
        .meta a:hover {{ text-decoration: underline; }}
        .video-embed {{
            position: relative;
            padding-bottom: 56.25%;
            margin-bottom: 24px;
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }}
        .video-embed iframe {{
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 100%;
            border: none;
        }}
        .transcript {{
            background: linear-gradient(160deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 40%, rgba(200, 153, 76, 0.02) 100%);
            border-radius: 16px;
            padding: 28px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-top-color: rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(12px) saturate(1.4);
            -webkit-backdrop-filter: blur(12px) saturate(1.4);
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.08);
        }}
        .transcript-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .transcript-header h2 {{
            font-size: 16px;
            color: #fff;
            margin: 0;
        }}
        .controls {{
            display: flex;
            gap: 6px;
            align-items: center;
            flex-wrap: wrap;
        }}
        .ctrl-btn {{
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 20px;
            cursor: pointer;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-top-color: rgba(255, 255, 255, 0.12);
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            color: var(--text-dim);
            transition: all 0.2s;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }}
        .ctrl-btn:hover {{ color: #fff; border-color: rgba(255, 255, 255, 0.15); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.08); }}
        .ctrl-btn.active {{ color: var(--gold); border-color: rgba(200, 153, 76, 0.3); background: linear-gradient(135deg, rgba(200, 153, 76, 0.15) 0%, rgba(200, 153, 76, 0.05) 100%); }}
        .ctrl-select {{
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%);
            color: var(--text-dim);
            cursor: pointer;
        }}
        .transcript-body {{
            color: #ccc;
            font-size: 14.5px;
            line-height: 1.9;
        }}
        .transcript-body p {{
            margin-bottom: 14px;
        }}
        .transcript-body p:first-child {{ text-indent: 0; }}
        .ts {{
            color: var(--accent2);
            text-decoration: none;
            font-size: 11px;
            font-weight: 600;
            opacity: 0.4;
            margin-right: 3px;
            transition: opacity 0.2s;
        }}
        .ts:hover {{ opacity: 1; text-decoration: underline; }}
        .seo-fallback {{ display: none; }}
        .reader-overlay {{
            display: none;
            position: fixed !important;
            top: 0; left: 0; right: 0; bottom: 0;
            z-index: 1000 !important;
            background: linear-gradient(90deg,
                rgba(10, 8, 14, 0.3) 0%,
                rgba(10, 8, 14, 0.85) 20%,
                rgba(10, 8, 14, 0.92) 50%,
                rgba(10, 8, 14, 0.85) 80%,
                rgba(10, 8, 14, 0.3) 100%);
            overflow-y: auto;
            padding: 0;
        }}
        .reader-overlay.active {{ display: block !important; }}
        .reader-toolbar {{
            position: sticky;
            top: 0;
            z-index: 1001;
            max-width: 720px;
            margin: 0 auto;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%);
            backdrop-filter: blur(20px) saturate(1.4);
            -webkit-backdrop-filter: blur(20px) saturate(1.4);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-bottom: 1px solid rgba(200, 153, 76, 0.12);
            border-radius: 16px 16px 0 0;
            padding: 10px 24px;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }}
        .reader-toolbar .ctrl-btn {{ font-size: 12px; padding: 4px 12px; }}
        .reader-content {{
            max-width: 720px;
            margin: 0 auto;
            padding: 32px 32px 80px;
            line-height: 2;
            color: #ddd;
            font-size: 16px;
            background: linear-gradient(160deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 40%, rgba(200, 153, 76, 0.02) 100%);
            backdrop-filter: blur(12px) saturate(1.4);
            -webkit-backdrop-filter: blur(12px) saturate(1.4);
            border-radius: 0 0 16px 16px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-top: none;
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }}
        .reader-content p {{ margin-bottom: 18px; }}
        .font-size-label {{
            color: var(--text-dim);
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .font-btn {{
            width: 28px;
            height: 28px;
            border: 1px solid var(--border);
            border-radius: 50%;
            background: none;
            color: var(--text-dim);
            cursor: pointer;
            font-size: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }}
        .font-btn:hover {{ color: #fff; border-color: var(--text-dim); }}
        @media (max-width: 600px) {{
            .container {{ padding: 14px; }}
            h1 {{ font-size: 18px; }}
            .transcript {{ padding: 16px; }}
            .transcript-body {{ font-size: 13.5px; }}
            .transcript-header {{ flex-direction: column; align-items: flex-start; }}
            .sacred-bg .icon-theotokos {{ display: none; }}
            .sacred-bg .icon-george {{ display: none; }}
            .sacred-bg .icon-topright-mirror {{ display: none; }}
            .sacred-bg .icon-topleft {{ display: none; }}
            .sacred-bg .icon-christ {{ width: 350px; opacity: 0.25; }}
        }}
    </style>
</head>
<body>
    <div class="sacred-bg" aria-hidden="true">
        <img class="icon-christ" src="/static/christ-pantocrator.webp" alt="">
        <img class="icon-topright-mirror" src="/static/last-judgment.webp" alt="">
        <img class="icon-theotokos" src="/static/theotokos.webp" alt="">
        <img class="icon-topleft" src="/static/last-judgment.webp" alt="">
        <img class="icon-george" src="/static/saint-george.webp" alt="">
        <div class="glow"></div>
    </div>
    <header class="ep-header">
        <div class="ep-header-title">Светоглед</div>
        <div class="ep-header-sub">Архив на предаването с Георги Тодоров по Радио Зорана</div>
    </header>
    <div class="container">
        <a href="/" class="back">&larr; Към търсенето</a>
        <h1>{title}</h1>
        <div class="meta">
            Светоглед с Георги Тодоров по Радио Зорана &middot;
            {segment_count} сегмента &middot;
            <a href="{yt_url}" target="_blank" rel="noopener noreferrer">Гледай в YouTube &rarr;</a>
        </div>
        <div class="video-embed">
            <iframe src="https://www.youtube.com/embed/{video_id}" allowfullscreen loading="lazy"></iframe>
        </div>
        <div class="transcript">
            <div class="transcript-header">
                <h2>Пълна транскрипция</h2>
                <div class="controls">
                    <button class="ctrl-btn active" onclick="setMode('clean', this)" title="Само текст">Четене</button>
                    <button class="ctrl-btn" onclick="setMode('timestamps', this)" title="С времена">С времена</button>
                    <label style="color:var(--text-dim);font-size:12px;display:flex;align-items:center;gap:4px">
                        Абзац:
                        <select class="ctrl-select" id="chunk-size" onchange="renderTranscript()">
                            <option value="5">5 сегм.</option>
                            <option value="10">10 сегм.</option>
                            <option value="15" selected>15 сегм.</option>
                            <option value="30">30 сегм.</option>
                            <option value="60">1 мин.</option>
                        </select>
                    </label>
                    <button class="ctrl-btn" onclick="exportText()" title="Копирай текста">Копирай</button>
                    <button class="ctrl-btn" onclick="downloadText()" title="Свали като файл">Свали .txt</button>
                    <button class="ctrl-btn fullscreen-btn" onclick="openReader()" title="Четене на цял екран" style="margin-left:auto;color:var(--gold);border-color:var(--gold)">&#9634; Цял екран</button>
                </div>
            </div>
            <div class="transcript-body" id="transcript-body"></div>
            <noscript><div class="transcript-body">{seo_html}</div></noscript>
            <div class="seo-fallback">{seo_html}</div>
        </div>
    </div>
    <div class="reader-overlay" id="reader-overlay">
        <div class="reader-toolbar">
            <button class="ctrl-btn" onclick="closeReader()" style="color:var(--gold);border-color:var(--gold)">&larr; Затвори</button>
            <span style="color:var(--text-dim);font-size:13px;flex:1;text-align:center">{title}</span>
            <div class="font-size-label">
                <button class="font-btn" onclick="changeFontSize(-1)" title="По-малък шрифт">A-</button>
                <span id="font-size-display">16</span>px
                <button class="font-btn" onclick="changeFontSize(1)" title="По-голям шрифт">A+</button>
            </div>
            <select class="ctrl-select" onchange="changeFontFamily(this.value)" style="margin-left:6px">
                <option value="sans">Sans-serif</option>
                <option value="serif">Serif</option>
                <option value="mono">Monospace</option>
            </select>
        </div>
        <div class="reader-content" id="reader-content"></div>
    </div>
    <script>
    var segments = {segments_json};
    var videoId = '{video_id}';
    var ytUrl = '{yt_url}';
    var mode = 'clean';
    var episodeTitle = '{title}';

    function setMode(m, btn) {{
        mode = m;
        document.querySelectorAll('.ctrl-btn:not(.fullscreen-btn)').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        renderTranscript();
    }}

    function renderTranscript() {{
        var body = document.getElementById('transcript-body');
        var chunkSize = parseInt(document.getElementById('chunk-size').value);
        var html = '';
        var chunk = [];
        var chunkStart = 0;

        for (var i = 0; i < segments.length; i++) {{
            var s = segments[i];
            if (chunk.length === 0) chunkStart = s.start;

            if (mode === 'timestamps') {{
                var tsUrl = ytUrl + '&t=' + s.start;
                chunk.push('<a href="' + tsUrl + '" class="ts">[' + s.ts + ']</a>' + escapeHtml(s.text));
            }} else {{
                chunk.push(escapeHtml(s.text));
            }}

            if (chunk.length >= chunkSize) {{
                html += '<p>' + chunk.join(' ') + '</p>';
                chunk = [];
            }}
        }}
        if (chunk.length > 0) {{
            html += '<p>' + chunk.join(' ') + '</p>';
        }}
        body.innerHTML = html;
    }}

    function getPlainText() {{
        var chunkSize = parseInt(document.getElementById('chunk-size').value);
        var lines = [];
        var chunk = [];
        for (var i = 0; i < segments.length; i++) {{
            chunk.push(segments[i].text);
            if (chunk.length >= chunkSize) {{
                lines.push(chunk.join(' '));
                chunk = [];
            }}
        }}
        if (chunk.length > 0) lines.push(chunk.join(' '));
        return episodeTitle + '\\n\\n' + lines.join('\\n\\n');
    }}

    function exportText() {{
        var text = getPlainText();
        navigator.clipboard.writeText(text).then(function() {{
            var btn = event.target;
            var orig = btn.textContent;
            btn.textContent = 'Копирано!';
            btn.style.borderColor = 'var(--accent2)';
            btn.style.color = 'var(--accent2)';
            setTimeout(function() {{ btn.textContent = orig; btn.style.borderColor = ''; btn.style.color = ''; }}, 1500);
        }});
    }}

    function downloadText() {{
        var text = getPlainText();
        var blob = new Blob([text], {{ type: 'text/plain;charset=utf-8' }});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = episodeTitle.replace(/[^\\wа-яА-Я\\s-]/g, '').trim() + '.txt';
        a.click();
        URL.revokeObjectURL(a.href);
    }}

    function escapeHtml(t) {{
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(t));
        return d.innerHTML;
    }}

    var readerFontSize = 16;
    var readerFontFamily = 'sans';
    var fontFamilies = {{
        sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        serif: 'Georgia, "Times New Roman", serif',
        mono: '"SF Mono", Menlo, Consolas, monospace'
    }};

    function openReader() {{
        var overlay = document.getElementById('reader-overlay');
        var content = document.getElementById('reader-content');
        var srcHtml = document.getElementById('transcript-body').innerHTML;
        if (!srcHtml || srcHtml.trim().length === 0) {{
            // Transcript not yet rendered, render first
            renderTranscript();
            srcHtml = document.getElementById('transcript-body').innerHTML;
        }}
        content.innerHTML = srcHtml;
        content.style.fontSize = readerFontSize + 'px';
        content.style.fontFamily = fontFamilies[readerFontFamily];
        overlay.classList.add('active');
        overlay.scrollTop = 0;
        document.body.style.overflow = 'hidden';
        overlay.setAttribute('tabindex', '-1');
        overlay.focus();
        // Scroll to first highlighted term if any
        setTimeout(function() {{
            var firstHit = content.querySelector('.highlight-term, mark, em');
            if (firstHit) {{
                firstHit.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}, 100);
    }}

    function closeReader() {{
        document.getElementById('reader-overlay').classList.remove('active');
        document.body.style.overflow = '';
    }}

    function changeFontSize(delta) {{
        readerFontSize = Math.max(12, Math.min(28, readerFontSize + delta));
        document.getElementById('reader-content').style.fontSize = readerFontSize + 'px';
        document.getElementById('font-size-display').textContent = readerFontSize;
    }}

    function changeFontFamily(val) {{
        readerFontFamily = val;
        document.getElementById('reader-content').style.fontFamily = fontFamilies[val];
    }}

    document.addEventListener('keydown', function(e) {{
        var overlay = document.getElementById('reader-overlay');
        if (!overlay.classList.contains('active')) return;
        if (e.key === 'Escape') {{
            e.preventDefault();
            closeReader();
        }}
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {{
            e.preventDefault();
            overlay.scrollBy({{ top: e.key === 'ArrowDown' ? 150 : -150, behavior: 'smooth' }});
        }}
        if (e.key === '+' || e.key === '=') {{ changeFontSize(1); }}
        if (e.key === '-') {{ changeFontSize(-1); }}
    }});

    renderTranscript();
    </script>
</body>
</html>"""


_CUSTOM_404 = """<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 — Страницата не е намерена | Светоглед Архив</title>
<style>
  body { margin:0; background:#0a0a0e; color:#e8e4e0; font-family:system-ui,-apple-system,sans-serif;
         display:flex; align-items:center; justify-content:center; min-height:100vh; text-align:center;
         overflow:hidden; }
  .sacred-bg { position:fixed; top:0; left:0; right:0; bottom:0; z-index:0; pointer-events:none; }
  .sacred-bg img { position:absolute; filter:sepia(0.2) brightness(1.1) saturate(0.7);
                   opacity:0.45; object-fit:contain; }
  .icon-menas { left:3%; top:50%; transform:translateY(-50%); height:70vh; max-height:600px; }
  .icon-phanourios { left:50%; top:50%; transform:translate(-50%,-50%); height:80vh; max-height:700px; opacity:0.25 !important; }
  .icon-nicholas { right:3%; top:50%; transform:translateY(-50%); height:65vh; max-height:550px; }
  .sacred-bg .glow { position:absolute; top:0; left:0; right:0; bottom:0;
    background: radial-gradient(ellipse 600px 700px at 50% 40%, rgba(200,153,76,0.04) 0%, transparent 70%),
                radial-gradient(ellipse 400px 500px at 5% 60%, rgba(107,32,56,0.05) 0%, transparent 70%),
                radial-gradient(ellipse 400px 400px at 90% 80%, rgba(200,153,76,0.03) 0%, transparent 60%); }
  .wrap { position:relative; z-index:1; max-width:480px; padding:40px 20px; }
  h1 { font-size:72px; color:#c8994c; margin:0 0 8px; font-weight:300; }
  p { color:#b8b0a8; font-size:16px; line-height:1.6; margin:8px 0; }
  .saints-note { color:#8a8078; font-size:12px; margin-top:32px; line-height:1.7; }
  .saints-note strong { color:#b8b0a8; }
  a { color:#c8994c; text-decoration:none; transition:color 0.2s; }
  a:hover { color:#d4a853; }
  .home-link { display:inline-block; margin-top:24px; padding:10px 24px;
               border:1px solid rgba(200,153,76,0.3); border-radius:24px; font-size:14px; }
  .home-link:hover { background:rgba(200,153,76,0.1); }
  @media (max-width:900px) {
    .icon-menas { left:-5%; height:50vh; opacity:0.3 !important; }
    .icon-nicholas { right:-5%; height:45vh; opacity:0.3 !important; }
    .icon-phanourios { opacity:0.18 !important; }
  }
  @media (max-width:600px) {
    .icon-menas, .icon-nicholas { display:none; }
    .icon-phanourios { opacity:0.15 !important; height:70vh; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sacred-bg img { transition:none; }
  }
</style>
</head>
<body>
<div class="sacred-bg" aria-hidden="true">
  <img class="icon-menas" src="/static/saint-menas.webp" alt="Свети Мина — икона" loading="eager">
  <img class="icon-phanourios" src="/static/saint-phanourios.webp" alt="Свети Фанурий — икона" loading="eager">
  <img class="icon-nicholas" src="/static/saint-nicholas.webp" alt="Свети Николай Чудотворец — икона" loading="eager">
  <div class="glow"></div>
</div>
<div class="wrap">
  <h1>404</h1>
  <p>Страницата не е намерена.</p>
  <p style="color:#8a8078;font-size:14px">Може би адресът е грешен или страницата е преместена.</p>
  <a class="home-link" href="/">&#8592; Към началото</a>
  <div class="saints-note">
    Покровители при изгубени неща:<br>
    <strong>Св. Мина</strong> (11 ноември) &middot;
    <strong>Св. Фанурий</strong> (27 август) &middot;
    <strong>Св. Николай Чудотворец</strong> (6 декември)
  </div>
</div>
</body>
</html>"""


class SearchHandler(SimpleHTTPRequestHandler):
    def _accepts_gzip(self):
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def _send_404(self):
        """Send custom styled 404 page."""
        body = _CUSTOM_404.encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_body(self, body, content_type, extra_headers=None):
        """Send response body, gzip-compressed if client supports it."""
        headers = extra_headers or {}
        if self._accepts_gzip() and len(body) > 256:
            body = gzip.compress(body, compresslevel=6)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/" or parsed.path == "/index.html":
            content = _MINIFIED_HTML or HTML_FILE.read_bytes()
            self._send_body(content, "text/html; charset=utf-8", {
                "Cache-Control": "no-cache, no-store, must-revalidate",
            })

        elif parsed.path == "/api/transcript":
            video_id = params.get("id", [None])[0]
            if not video_id:
                self.send_error(400, "Missing id")
                return
            fpath = TRANSCRIPTS_DIR / f"{video_id}.json"
            if not fpath.exists():
                self.send_error(404, "Not found")
                return
            self._serve_json(json.loads(fpath.read_text(encoding="utf-8")))

        elif parsed.path == "/api/episodes":
            episodes = []
            for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
                data = json.loads(f.read_text(encoding="utf-8"))
                episodes.append({
                    "video_id": data["video_id"],
                    "title": data["title"],
                    "source": data.get("source", ""),
                    "segment_count": data.get("segment_count", 0),
                    "playlist_order": data.get("playlist_order", 9999),
                    "episode_number": data.get("episode_number", 0),
                    "_duration": _get_duration(data),
                })
            # Deduplicate re-uploads: same episode_number + similar duration
            # Keep the version with "(Беседа N)" in title
            seen = {}  # episode_number -> best episode
            unique = []
            for ep in episodes:
                n = ep["episode_number"]
                if n in seen:
                    prev = seen[n]
                    if _is_reupload(prev["_duration"], ep["_duration"]):
                        has_label = f"(Беседа {n})" in ep["title"]
                        prev_has = f"(Беседа {n})" in prev["title"]
                        if has_label and not prev_has:
                            unique[unique.index(prev)] = ep
                            seen[n] = ep
                        continue  # skip duplicate
                    # Different content sharing same number — keep both
                unique.append(ep)
                seen[n] = ep
            for ep in unique:
                del ep["_duration"]
            unique.sort(key=lambda x: x.get("episode_number", 0))
            self._serve_json(unique)

        elif parsed.path == "/api/topics":
            self._serve_json(build_topics())

        elif parsed.path.startswith("/episode/"):
            video_id = parsed.path[len("/episode/"):].strip("/")
            if not video_id or not re.match(r'^[\w-]+$', video_id):
                self._send_404()
                return
            fpath = TRANSCRIPTS_DIR / f"{video_id}.json"
            if not fpath.exists():
                self._send_404()
                return
            data = json.loads(fpath.read_text(encoding="utf-8"))
            content = _render_episode_page(data).encode("utf-8")
            self._send_body(content, "text/html; charset=utf-8")

        elif parsed.path == "/robots.txt":
            content = b"User-agent: *\nAllow: /\nSitemap: https://svetogled-arhiv.com/sitemap.xml\n"
            self._send_body(content, "text/plain; charset=utf-8")

        elif parsed.path == "/sitemap.xml":
            self._serve_sitemap()

        elif parsed.path.startswith("/meili/"):
            self._proxy_meili("GET")

        elif parsed.path.startswith("/static/"):
            safe_path = parsed.path.replace("..", "").lstrip("/")
            fpath = Path(__file__).parent / safe_path
            if fpath.exists() and fpath.is_file():
                content = fpath.read_bytes()
                ext = fpath.suffix.lower()
                ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}.get(ext, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_404()

        else:
            self._send_404()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/meili/"):
            self._proxy_meili("POST")
        else:
            self.send_error(404)

    def _proxy_meili(self, method):
        meili_path = self.path[len("/meili"):]
        meili_url = f"http://127.0.0.1:7700{meili_path}"

        headers = {
            "Authorization": "Bearer svetogled-search-key",
            "Content-Type": "application/json",
        }

        body = None
        if method == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)

        try:
            req = Request(meili_url, data=body, headers=headers, method=method)
            with urlopen(req, timeout=10) as resp:
                result = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)
        except Exception as e:
            error = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error)))
            self.end_headers()
            self.wfile.write(error)

    def _serve_sitemap(self):
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        xml += '  <url><loc>https://svetogled-arhiv.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
            vid = f.stem
            data = json.loads(f.read_text(encoding="utf-8"))
            lastmod = data.get("upload_date", "")
            xml += f'  <url><loc>https://svetogled-arhiv.com/episode/{vid}</loc>'
            if lastmod:
                xml += f'<lastmod>{lastmod}</lastmod>'
            xml += '<changefreq>monthly</changefreq><priority>0.8</priority></url>\n'
        xml += '</urlset>\n'
        body = xml.encode("utf-8")
        self._send_body(body, "application/xml; charset=utf-8")

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_body(body, "application/json; charset=utf-8", {
            "Access-Control-Allow-Origin": "*",
        })

    def log_message(self, format, *args):
        pass


def _update_meili_pagination():
    """Ensure Meilisearch allows enough results for full episode coverage."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:7700/indexes/segments/settings/pagination",
            data=json.dumps({"maxTotalHits": 20000}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer svetogled-search-key",
            },
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=5)
        print("Meilisearch pagination maxTotalHits set to 20000")
    except Exception as e:
        print(f"Note: Could not update Meilisearch pagination: {e}")


if __name__ == "__main__":
    _update_meili_pagination()
    server = HTTPServer(("0.0.0.0", PORT), SearchHandler)
    print(f"Светоглед Search running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
