#!/usr/bin/env python3
"""
Светоглед Transcript Search — full-featured research tool.

Usage:
    python search_app.py
    Then open http://localhost:8080
"""

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


def build_topics():
    """Analyze transcripts for meaningful names and concepts."""
    # Track in how many episodes each term appears (not total count)
    name_episode_count = Counter()
    concept_episode_count = Counter()

    for f in TRANSCRIPTS_DIR.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        text = data.get("full_text", "")

        # Names: capitalized multi-word patterns for better detection
        # Single capitalized words that are real proper nouns
        cap_words = set(re.findall(r'[А-ЯA-Z][а-яa-z]{2,}', text))
        for w in cap_words:
            if (w.lower() not in STOP_WORDS
                    and w not in STOP_NAMES
                    and len(w) > 3):  # Min 4 chars to skip "Ама", "Ето" etc
                name_episode_count[w] += 1

        # Concepts: look for domain-specific words
        words = set(re.findall(r'[а-я]{5,}', text.lower()))
        for w in words:
            if (w not in STOP_WORDS
                    and w not in STOP_CONCEPTS
                    and len(w) > 5):  # Min 6 chars
                concept_episode_count[w] += 1

    total_episodes = max(1, sum(1 for _ in TRANSCRIPTS_DIR.glob("*.json")))

    # Names: must appear in 3-70% of episodes (too common = not a specific name)
    names = [(w, c) for w, c in name_episode_count.most_common(300)
             if 3 <= c <= total_episodes * 0.7
             and w not in STOP_NAMES]
    names.sort(key=lambda x: -x[1])

    # Concepts: appear in 3+ episodes but not in >50% (those are too generic)
    name_lower = {w.lower() for w, _ in names}
    concepts = [(w, c) for w, c in concept_episode_count.most_common(500)
                if 3 <= c <= total_episodes * 0.5
                and w not in name_lower
                and w not in STOP_WORDS
                and w not in STOP_CONCEPTS]
    concepts.sort(key=lambda x: -x[1])

    return [
        {"category": "Имена и лица",
         "items": [{"term": w, "count": c} for w, c in names[:60]]},
        {"category": "Понятия и теми",
         "items": [{"term": w, "count": c} for w, c in concepts[:60]]},
    ]


class SearchHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/" or parsed.path == "/index.html":
            content = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

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
                })
            episodes.sort(key=lambda x: x["title"])
            self._serve_json(episodes)

        elif parsed.path == "/api/topics":
            self._serve_json(build_topics())

        elif parsed.path.startswith("/meili/"):
            self._proxy_meili("GET")

        else:
            self.send_error(404)

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

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), SearchHandler)
    print(f"Светоглед Search running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
