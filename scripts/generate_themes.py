#!/usr/bin/env python3
"""
Generate themes.json — the curated theme map of the Светоглед archive.

Unlike the old TF-IDF topic extraction (noisy single words), this uses a
hand-curated taxonomy of themes, each with Bulgarian morphology-aware
regex patterns. Episodes are scored by match density; a theme is assigned
when the density clears its threshold (or the title mentions it directly).

The output feeds the "Карта на темите" visualization on the site:
  - themes: nodes (label, group, episodes with weights, description)
  - links:  theme co-occurrence edges (how often themes share episodes)
  - episodes: video_id -> {n, title, themes}

Run from the repo root (or anywhere):  python3 scripts/generate_themes.py
Deterministic, stdlib-only, no network access.
"""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "transcripts"
OUTPUT = ROOT / "themes.json"

# ── Taxonomy ─────────────────────────────────────────────────────────────
# Each theme: id, label, group, description, patterns (regex alternation,
# matched case-insensitively against full text and title), and optional
# overrides for min_hits / min_per10k when the vocabulary is very common.
#
# Pattern crafting notes:
#  - \b works for Cyrillic in Python 3 (\w is Unicode-aware).
#  - Watch for substring traps: "икона" must not catch "икономика",
#    "рок" must not catch "срок"/"барок" — anchored alternations avoid this.

GROUPS = {
    "vyara": "Вяра и богословие",
    "bulgaria": "България и Православието",
    "istoria": "История и цивилизации",
    "kultura": "Култура и слово",
    "savremennost": "Съвременният свят",
}

THEMES = [
    # ── Вяра и богословие ──
    {
        "id": "bogoslovie",
        "label": "Богословие и догмати",
        "group": "vyara",
        "description": "Догматите на вярата, Св. Троица, Боговъплъщението и богопознанието.",
        "patterns": r"богослов\w*|догмат\w*|света(та)? троица|боговъплъщени\w*|въплъщение(то)?|христологи\w*|благодат(та)?\b|обожени\w*|богопознани\w*|богочовек\w*|богочовешк\w*|човекобожи\w*|символ(ът|а)? на вярата|вероопределени\w*",
        "min_per10k": 7.0,
    },
    {
        "id": "bogorodica",
        "label": "Пресвета Богородица",
        "group": "vyara",
        "description": "Божията Майка — почитта, празниците и застъпничеството ѝ.",
        "patterns": r"богородица(та)?|богородичн\w*|богоматер\w*|божията майка|дева мария|пресвета(та)? дева|приснодева\w*|благовещени\w*",
        "min_hits": 4,
    },
    {
        "id": "svetci",
        "label": "Светци и жития",
        "group": "vyara",
        "description": "Житията на светците, мъченичеството, мощите и прославленията.",
        "patterns": r"светец(ът|а)?|светци(те)?|светица(та)?|жити(е|ето|я|ята)\b|мъченик\w*|мъченица\w*|мъченичеств\w*|великомъченик\w*|преподобн\w*|равноапостол\w*|чудотворец\w*|чудотворц\w*|мощи(те)?\b|канониза\w*|прославлени\w*|светост(та)?\b",
        "min_per10k": 8.0,
    },
    {
        "id": "ikona",
        "label": "Иконата и образът",
        "group": "vyara",
        "description": "Богословието на иконата, иконопис, иконоборство и свещеният образ.",
        "patterns": r"икона(та)?\b|икони(те)?\b|иконопис\w*|иконограф\w*|иконоборств\w*|иконоборц\w*|иконоборческ\w*|иконостас\w*|иконопочитани\w*|нерукотворн\w*|неръкотворн\w*|фреск\w*|стенопис\w*|мозайк\w*",
    },
    {
        "id": "liturgia",
        "label": "Богослужение и тайнства",
        "group": "vyara",
        "description": "Светата Литургия, Евхаристията и тайнствата на Църквата.",
        "patterns": r"литурги\w*|богослужени\w*|богослужебн\w*|евхаристи\w*|причасти\w*|причастява\w*|тайнств\w*|кръщени\w*|миропомазв\w*|венчавк\w*|всенощн\w*|вечерня(та)?|утреня(та)?|олтар\w*|престол(ът|а)? божи",
    },
    {
        "id": "monashestvo",
        "label": "Монашество и подвиг",
        "group": "vyara",
        "description": "Манастирите, монасите, старците и духовното подвижничество.",
        "patterns": r"монах\w*|монахин\w*|монашеств\w*|монашеск\w*|манастир\w*|монастир\w*|игумен\w*|старец(ът|а)?\b|старци(те)?\b|отшелник\w*|отшелниц\w*|подвижник\w*|подвижниц\w*|подвижничеств\w*|аскез\w*|аскетич\w*|исихаз\w*|исихаст\w*|света(та)? гора|атон\w*",
        "min_per10k": 6.5,
    },
    {
        "id": "molitva",
        "label": "Молитва и покаяние",
        "group": "vyara",
        "description": "Молитвеният живот, грехът, покаянието и борбата със страстите.",
        "patterns": r"молитва(та)?|молитви(те)?|молитвен\w*|покаяни\w*|покайн\w*|изповед(та)?\b|грях(ът|а)?\b|грехове(те)?|греховн\w*|съгреш\w*|изкушени\w*|смирение(то)?\b|гордост(та)?\b|тщеславие(то)?|добродетел\w*|целомъдри\w*",
        "min_per10k": 9.0,
    },
    {
        "id": "chudesa",
        "label": "Чудеса и знамения",
        "group": "vyara",
        "description": "Благодатният огън, Торинската плащаница, мироточенето и Божиите знамения.",
        "patterns": r"чудо(то)?\b|чудеса(та)?\b|чудес(ен|на|но|ни)\w*|благодат(ен|ния|ният) огън|плащаниц\w*|мироточ\w*|нетлен\w*|знамени(е|ето|я|ята)\b|изцелени\w*|чудотворн\w*",
    },
    {
        "id": "praznici",
        "label": "Празници и календарът",
        "group": "vyara",
        "description": "Църковните празници и спорът за календара — стар и нов стил.",
        "patterns": r"празник(ът|а)?\b|празници(те)?\b|празничн\w*|празнува\w*|рождество(то)?\b|богоявлени\w*|великден\w*|пасха(та)?\b|пасхалн\w*|коледа(та)?\b|календар\w*|нов(ия|ият)? стил|стар(ия|ият)? стил|новостилн\w*|старостилн\w*|юлианск\w*|григорианск\w*|литийн\w*|литий\w*",
    },
    {
        "id": "eshatologia",
        "label": "Последните времена",
        "group": "vyara",
        "description": "Есхатологията — антихристът, Страшният съд и знаците на края.",
        "patterns": r"есхатолог\w*|последни(те)? времена|предпоследни(те)? времена|антихрист\w*|второ(то)? пришествие|страшния(т)? съд|страшен съд|апокалипсис\w*|апокалиптичн\w*|краят? на света|свършек(ът|а)?\b|числото на звяра|осмия(т)? ден",
        "min_hits": 4,
    },
    {
        "id": "eresi",
        "label": "Ереси и разколи",
        "group": "vyara",
        "description": "Ересите, схизмите и разколите — от арианството и богомилите до днес.",
        "patterns": r"ерес(та)?\b|ереси(те)?\b|еретик\w*|еретичн\w*|еретическ\w*|разкол(ът|а)?\b|разколи(те)?\b|разколническ\w*|разколник\w*|схизма\w*|схизматиц\w*|гностиц\w*|гностич\w*|богомил\w*|манихе\w*|арианств\w*|ариан(и|ите|ство)\b|несториан\w*|монофизит\w*|сектантск\w*|секта(та)?\b|секти(те)?\b",
        "min_per10k": 6.0,
    },
    {
        "id": "ikumenizam",
        "label": "Икуменизъм и униите",
        "group": "vyara",
        "description": "Икуменизмът, униите с Рим и размиването на православната вяра.",
        "patterns": r"икумениз\w*|икуменическ\w*|икуменист\w*|обединение(то)? на църквите|уния(та)?\b|унии(те)?\b|униат\w*|интеркомунион\w*|съслужени\w*|съслужи\w*|филиокве|filioque|папизъм|папизма",
        "min_hits": 4,
    },
    {
        "id": "sabori",
        "label": "Съборите на Църквата",
        "group": "vyara",
        "description": "Вселенските и поместните събори — съборността на Православието.",
        "patterns": r"събор(ът|а)?\b|събори(те)?\b|съборн\w*|вселенски(те)? събор\w*|никейск\w*|никея|халкидон\w*|ефеск\w+ събор|критски(я|ят)? събор|всеправослав\w*",
        "min_per10k": 6.5,
    },
    {
        "id": "fener",
        "label": "Фенер и Вселенската патриаршия",
        "group": "vyara",
        "description": "Константинополската патриаршия, патриарх Вартоломей и претенциите на Фенер.",
        "patterns": r"фенер\w*|вартоломей\w*|вселенска(та)? патриаршия|вселенски(я|ят)? патриарх\w*|цариградска(та)? патриаршия|константинополска(та)? патриаршия|метаксакис|псевдо-?константинопол\w*|пръв без равни|първи без равни|томос\w*",
        "min_hits": 4,
    },
    {
        "id": "ateizam",
        "label": "Атеизъм и безбожие",
        "group": "vyara",
        "description": "Атеизмът като религия, материализмът и войната срещу вярата.",
        "patterns": r"атеиз\w*|атеист\w*|безбожи\w*|безбожн\w*|безвери\w*|материализ\w*|материалист\w*|дарвиниз\w*|еволюционизм\w*|секуляриз\w*|секулариз\w*|богоборч\w*|богоборств\w*|неверие(то)?\b",
    },

    # ── България и Православието ──
    {
        "id": "pokrastvane",
        "label": "Св. Борис и Покръстването",
        "group": "bulgaria",
        "description": "Покръстителят св. Борис-Михаил, Златният век и изворът на българщината.",
        "patterns": r"покръстван\w*|покръстител\w*|покръст\w*|свети борис|св\.? борис|княз(ът|а)? борис|борис[- ]михаил|борис i\b|борис първи|златен век|златни(я|ят)? век|плиска|плисковск\w*|преслав\b|преславск\w*|велика(та)? базилика",
    },
    {
        "id": "kirilometodievo",
        "label": "Кирил и Методий — словото",
        "group": "bulgaria",
        "description": "Светите братя, глаголицата, кирилицата и вселенската мисия на славянското слово.",
        "patterns": r"кирил и методий|св\.? св\.? кирил|солунски(те)? братя|глаголица(та)?|глаголическ\w*|кирилица(та)?|кирилск\w*|славянска(та)? писменост|славянобългарск\w*|климент охридски|наум охридски|седмочисленици(те)?|24 май|двадесет и четвърти май|равноапостолн\w*|славянств\w*|азбука(та)?\b",
        "min_hits": 4,
    },
    {
        "id": "bg_svetci",
        "label": "Български светци",
        "group": "bulgaria",
        "description": "Св. Йоан Рилски, св. Пимен Зографски, св. Патриарх Евтимий и небесните закрилници на България.",
        "patterns": r"йоан рилски|иван рилски|рилски(я|ят)? (светец|чудотворец|пустинник|манастир|монастир)|пимен зографски|зографск\w*|серафим соболев|соболев\w*|патриарх евтимий|евтимий търновски|паисий хилендарски|софроний врачански|злата мъгленска|българските? светци|небесни(те)? закрилници",
        "min_hits": 3,
    },
    {
        "id": "bg_curkva",
        "label": "Българската църква",
        "group": "bulgaria",
        "description": "Екзархията, Българската патриаршия, Синодът и пътят на поместната ни църква.",
        "patterns": r"екзархия(та)?|екзарх(ът|а)?\b|екзархийск\w*|българска(та)? православна църква|българска(та)? църква|българска(та)? патриаршия|български(я|ят)? патриарх\w*|светия(т)? синод|синод\w*|ферман(ът|а)?\b|фермана",
        "min_per10k": 5.0,
    },
    {
        "id": "bg_carstvo",
        "label": "Царство България",
        "group": "bulgaria",
        "description": "Царете и държавността — от Аспарух и Крум до Симеон, Калоян и Асеневци.",
        "patterns": r"цар симеон|симеон велики|симеонов\w*|калоян\w*|иван асен|асеневц\w*|цар петър|цар самуил|самуилов\w*|търновск\w*|велико търново|аспарух\w*|хан крум|кан крум|крумов\w*|омуртаг\w*|тервел\w*|първо(то)? българско царство|второ(то)? българско царство|държавност(та)?\b|престолнин\w*|столнин\w*",
        "min_hits": 4,
    },
    {
        "id": "katastrofi",
        "label": "Националните катастрофи",
        "group": "bulgaria",
        "description": "Съединението, войните, Ньой и Македония — уроците на националните катастрофи.",
        "patterns": r"национална(та)? катастрофа|национални(те)? катастрофи|съединение(то)?\b|санстефанск\w*|сан стефано|берлински(я|ят)? (конгрес|договор)|ньойск\w*|ньой\b|балканска(та)? война|балкански(те)? войни|междусъюзническ\w*|илинденск\w*|преображенск\w*|македони\w*|македонск\w*|одринска тракия|беломори\w*|добруджа(та)?",
    },
    {
        "id": "vazrazhdane",
        "label": "Възраждане и Освобождение",
        "group": "bulgaria",
        "description": "Възрожденците, Априлското въстание и Освобождението на България.",
        "patterns": r"възраждане(то)?\b|възрожденск\w*|възрожденц\w*|априлско(то)? въстание|левски\b|ботев\w*|раковски|бенковски|каравелов\w*|освобождение(то)?\b|освободител\w*|руско-турска(та)? война|игнатиев\w*|шипка|шипченск\w*|опълченц\w*|захарий? стоянов|батак\w*|баташк\w*",
    },
    {
        "id": "komunizam",
        "label": "Комунизмът и България",
        "group": "bulgaria",
        "description": "Девети септември, народната република и раните от комунистическата епоха.",
        "patterns": r"комунизъм|комунизма(та)?|комунист\w*|комунистическ\w*|тодор живков|живков\w*|девети септември|09\.09\.1944|народен съд|народния(т)? съд|белене|нрб\b|бкп\b|соцреализ\w*|деветосептемврийск\w*|десталинизаци\w*|колективизаци\w*",
    },
    {
        "id": "sofia_grad",
        "label": "София — свещеният град",
        "group": "bulgaria",
        "description": "Град Света София — сърцето и свещената столица на България.",
        "patterns": r"света софия|град софия|софийск\w*|сердика|средец\w*|софиинден|боянск\w*|александър невски",
        "min_per10k": 5.0,
        "min_hits": 4,
    },

    # ── История и цивилизации ──
    {
        "id": "vizantia",
        "label": "Византия и Константинопол",
        "group": "istoria",
        "description": "Ромейската империя, Константинопол и православната цивилизация.",
        "patterns": r"византи\w*|константинопол\w*|цариград\w*|юстиниан\w*|ромеи(те)?\b|ромейск\w*|василевс\w*|император(ът|а)? константин|света софия константинополска|православна(та)? цивилизация",
    },
    {
        "id": "rusia",
        "label": "Русия и Православието",
        "group": "istoria",
        "description": "Светата Рус, руската църква и сложният път на Русия.",
        "patterns": r"русия|руск\w*|руснац\w*|русофил\w*|русофоб\w*|москва|московск\w*|петербург\w*|киевск\w*|светата рус|петър първи|петър велики|романов\w*|путин\w*|съветски(я|ят)? съюз",
        "min_per10k": 8.0,
    },
    {
        "id": "revolucii",
        "label": "Революциите",
        "group": "istoria",
        "description": "Френската и руската революция — духът на бунта срещу Бога и реда.",
        "patterns": r"революци\w*|революционер\w*|болшевик\w*|болшевишк\w*|ленин\w*|троцк\w*|марксиз\w*|маркс\b|якобин\w*|робеспиер\w*|гилотин\w*|свобода(та)?, равенство|бунт(ът|а)?\b|бунтове(те)?\b|бунтовн\w*",
        "min_per10k": 7.0,
    },
    {
        "id": "zapad",
        "label": "Западът и папството",
        "group": "istoria",
        "description": "Римокатолицизмът, протестантството и духовният път на Запада.",
        "patterns": r"папа(та)?\b|папи(те)?\b|папств\w*|папск\w*|ватикан\w*|католиц\w*|католическ\w*|римокатол\w*|протестант\w*|реформаци\w*|лутер\w*|калвин\w*|кръстоносн\w*|кръстоносц\w*|инквизици\w*|индулгенци\w*|запад(ът|а)?\b|западна(та)? църква|западноевропейск\w*",
        "min_per10k": 9.0,
    },
    {
        "id": "osmansko",
        "label": "Османското владичество",
        "group": "istoria",
        "description": "Империята на султаните, робството и оцеляването на вярата под игото.",
        "patterns": r"османск\w*|османц\w*|султан\w*|еничар\w*|ислям\w*|мюсюлман\w*|мохамедан\w*|джихад\w*|турско(то)? робство|турци(те)?\b|турция|мидхат\w*|диарбекир\w*|потурч\w*|игото|под игото",
    },
    {
        "id": "imperii",
        "label": "Империи и хегемони",
        "group": "istoria",
        "description": "Империите, колониализмът и хегемоните на света — стари и нови.",
        "patterns": r"империя(та)?|империи(те)?|имперск\w*|империализ\w*|колониализ\w*|колониалн\w*|метаколониализ\w*|колонизаци\w*|хегемон\w*|васал\w*|великите сили|свръхсила\w*|англоезичн\w*|британск\w*|англия|лондон\w*|американск\w*|америка(та)?\b|сащ\b|вашингтон\w*",
        "min_per10k": 9.0,
    },
    {
        "id": "drevnost",
        "label": "Древният свят",
        "group": "istoria",
        "description": "Египет, Елада и езичеството — древните цивилизации и техните богове.",
        "patterns": r"египет\w*|египетск\w*|пирамид\w*|фараон\w*|ехнатон\w*|вавилон\w*|асирийц\w*|месопотами\w*|шумер\w*|античност(та)?|античн\w*|елинизъм|елинистич\w*|древна гърция|древногръцк\w*|платон\w*|аристотел\w*|сократ\w*|езичеств\w*|езическ\w*|езичниц\w*|митологи\w*|олимп\w*",
        "min_per10k": 5.0,
    },
    {
        "id": "svetovni_voini",
        "label": "Световните войни",
        "group": "istoria",
        "description": "Двете световни войни, Третият райх и войнотворците на XX век.",
        "patterns": r"световна(та)? война|световни(те)? войни|първата световна|втората световна|хитлер\w*|нацизъм|нацист\w*|нацистк\w*|трети(я|ят)? райх|фашиз\w*|фашист\w*|холокост\w*|войнотворц\w*|студена(та)? война|окупаци\w*|капитулаци\w*",
        "min_hits": 4,
    },

    # ── Култура и слово ──
    {
        "id": "dostoevski",
        "label": "Достоевски",
        "group": "kultura",
        "description": "Пророкът на романа — Достоевски, неговите бесове и неговата вяра.",
        "patterns": r"достоевск\w*|карамазов\w*|разколников|бесовете|записки от подземието|престъпление и наказание|пушкинска(та)? реч",
        "min_hits": 3,
    },
    {
        "id": "dante",
        "label": "Данте",
        "group": "kultura",
        "description": "Данте Алигиери — от Вита Нуова до Комедията и границите на човекобожието.",
        "patterns": r"данте\b|дантев\w*|алигиери|беатриче|вита нуова|божествена(та)? комедия|чистилище(то)?\b",
        "min_hits": 3,
    },
    {
        "id": "literatura",
        "label": "Литература и поезия",
        "group": "kultura",
        "description": "Големите книги и поети — от Шекспир и Пушкин до Вазов и Далчев.",
        "patterns": r"литератур\w*|поези\w*|поет(ът|а)?\b|поети(те)?\b|поетическ\w*|поема(та)?\b|роман(ът|а)?\b|романи(те)?\b|писател\w*|шекспир\w*|хамлет\w*|толстой\w*|пушкин\w*|гьоте|бодлер\w*|яворов\w*|вазов\w*|смирненски|далчев\w*|шели\b|байрон\w*|цветя(та)? на злото|стихотворени\w*|стихове(те)?\b",
        "min_per10k": 8.0,
    },
    {
        "id": "izkustvo",
        "label": "Изкуството и образите",
        "group": "kultura",
        "description": "Микеланджело, Леонардо, Ренесансът и смисълът на изкуството.",
        "patterns": r"изкуство(то)?\b|изкуства(та)?\b|художник\w*|художниц\w*|художествен\w*|картина(та)?\b|картини(те)?\b|микеланджело|леонардо|рафаело?\b|джото|ренесанс\w*|скулптур\w*|сикстинск\w*|галери\w*|естетик\w*|естетическ\w*|кондаков\w*|шедьов\w*",
        "min_per10k": 7.0,
    },
    {
        "id": "muzika",
        "label": "Музика и модерна сцена",
        "group": "kultura",
        "description": "Музиката, рок културата, екранът и новите идоли на сцената.",
        "patterns": r"музика(та)?\b|музикал\w*|музикант\w*|рок(ът|а)?\b|рок[- ]музик\w*|рок[- ]култур\w*|опера(та)?\b|концерт\w*|битълс\w*|елвис|пресли|уудсток|джулая|суперстар|мюзикъл\w*|кино(то)?\b|филм(ът|а)?\b|филми(те)?\b|холивуд\w*|екраниз\w*",
        "min_per10k": 8.0,
    },
    {
        "id": "ezik",
        "label": "Езикът на Църквата",
        "group": "kultura",
        "description": "Църковнославянският, старобългарският и съдбата на българския език.",
        "patterns": r"църковнославянск\w*|старобългарск\w*|новобългарск\w*|български(я|ят)? език|богослужебен\w* език|книжовен|книжовн\w*|книжнина(та)?|правопис\w*|езикова(та)? реформа|преводач\w*|превод(ът|а)?\b|преводи(те)?\b",
        "min_per10k": 5.0,
    },

    # ── Съвременният свят ──
    {
        "id": "demokracia",
        "label": "Демокрацията и властта",
        "group": "savremennost",
        "description": "Демокрацията, изборите и въпросът кой всъщност управлява.",
        "patterns": r"демокраци\w*|демократ\w*|демократическ\w*|псевдокраци\w*|демонокраци\w*|парламент\w*|избори(те)?\b|изборн\w*|вот(ът|а)?\b|гласуван\w*|гласопода\w*|референдум\w*|конституци\w*|разделение(то)? на властите|либерализ\w*|либералн\w*",
        "min_per10k": 10.0,
    },
    {
        "id": "medii",
        "label": "Медиите и пропагандата",
        "group": "savremennost",
        "description": "Медиите, пропагандата и производството на съгласие.",
        "patterns": r"меди(я|ия|ии|иите|йн\w*)\b|медии(те)?\b|пропаганд\w*|вестник\w*|вестниц\w*|телевизи\w*|журналист\w*|новинарск\w*|новини(те)?\b|цензур\w*|дезинформаци\w*|фалшиви(те)? новини|маклуън\w*|реклам\w*|социални(те)? мрежи",
        "min_per10k": 7.0,
    },
    {
        "id": "lazhata",
        "label": "Лъжата и подмяната",
        "group": "savremennost",
        "description": "Царството на лъжата — подмяната на истината, историята и светините.",
        "patterns": r"лъжа(та)?\b|лъжи(те)?\b|лъжлив\w*|лъжец\w*|лъжц\w*|излъгван\w*|излъга\w*|лъже-\w+|лъжеистор\w*|подмяна(та)?|подменен\w*|подменя\w*|измама(та)?\b|измами(те)?\b|измамн\w*|самоизмам\w*|фалшификаци\w*|фалшив\w*|манипулаци\w*|вместо-?истин\w*|неистин\w*|заблуда(та)?\b|заблуди(те)?\b",
        "min_per10k": 12.0,
    },
    {
        "id": "tehnika",
        "label": "Техниката и човекът",
        "group": "savremennost",
        "description": "Роботът, изкуственият интелект и човекът пред машината.",
        "patterns": r"робот\w*|изкуствен\w+ интелект|компютър\w*|компютр\w*|технологи\w*|техника(та)?\b|техническ\w*|машина(та)?\b|машини(те)?\b|дигитал\w*|интернет\w*|смартфон\w*|алгоритъм\w*|алгоритм\w*|киборг\w*|трансхуманиз\w*|deus ex machina|чатбот\w*|неврон\w+ мреж\w*",
        "min_hits": 4,
    },
    {
        "id": "semeystvo",
        "label": "Семейство и възпитание",
        "group": "savremennost",
        "description": "Семейството, децата, възпитанието и прагът на зрелостта.",
        "patterns": r"семейство(то)?\b|семейства(та)?\b|семеен|семейн\w*|брак(ът|а)?\b|бракове(те)?|деца(та)?\b|детето\b|детств\w*|възпитани\w*|възпитава\w*|родител\w*|майчинств\w*|бащинств\w*|младеж\w*|юношеск\w*|образовани\w*|училище(то)?\b|училища(та)?\b|вероучени\w*|зрелост(та)?\b|пълнолети\w*",
        "min_per10k": 8.0,
    },
    {
        "id": "globalizam",
        "label": "Глобализмът",
        "group": "savremennost",
        "description": "Новата нормалност, наднационалната власт и „европейските ценности“.",
        "patterns": r"глобализ\w*|глобалист\w*|глобалн\w*|новата нормалност|ковид\w*|пандеми\w*|локдаун\w*|ваксин\w*|велик\w+ рестарт|нов(ия|ият)? световен ред|наднационалн\w*|брюксел\w*|европейски(те)? ценности|евросъюз\w*|европейски(я|ят)? съюз|еврото\b|евроинтеграци\w*|давос\w*",
        "min_hits": 4,
    },
    {
        "id": "konspiracii",
        "label": "Конспирациите",
        "group": "savremennost",
        "description": "Теориите на конспирацията — между реалните заговори и духовната измама.",
        "patterns": r"конспираци\w*|конспиративн\w*|конспиратор\w*|заговор\w*|тайни(те)? общества|масон\w*|илюминат\w*|тамплиер\w*|мондиализ\w*|задкулиси\w*|дълбока(та)? държава",
        "min_hits": 3,
    },
]

# Search seed per theme — what the site's search box is fed when the user
# clicks "Търси в архива" from the theme panel. Curated for Meilisearch recall.
QUERIES = {
    "bogoslovie": "богословие догматите",
    "bogorodica": "Богородица",
    "svetci": "светците житията",
    "ikona": "иконата иконопис",
    "liturgia": "литургията тайнствата",
    "monashestvo": "манастирите монашеството",
    "molitva": "молитвата покаянието",
    "chudesa": "чудото благодатният огън",
    "praznici": "празникът календарът",
    "eshatologia": "последните времена антихристът",
    "eresi": "ерестите разколът",
    "ikumenizam": "икуменизмът унията",
    "sabori": "съборът вселенски",
    "fener": "Фенер Вартоломей",
    "ateizam": "атеизмът безбожието",
    "pokrastvane": "покръстването свети Борис",
    "kirilometodievo": "Кирил и Методий",
    "bg_svetci": "Йоан Рилски Пимен Зографски",
    "bg_curkva": "Екзархията българската църква",
    "bg_carstvo": "цар Симеон Калоян",
    "katastrofi": "националната катастрофа Македония",
    "vazrazhdane": "Възраждането Освобождението",
    "komunizam": "комунизмът девети септември",
    "sofia_grad": "София Средец",
    "vizantia": "Византия Константинопол",
    "rusia": "Русия руското православие",
    "revolucii": "революцията болшевиките",
    "zapad": "папата Ватикана католицизмът",
    "osmansko": "османската империя султанът",
    "imperii": "империята хегемонът",
    "drevnost": "Египет античността езичеството",
    "svetovni_voini": "световната война Хитлер",
    "dostoevski": "Достоевски",
    "dante": "Данте",
    "literatura": "литературата поезията",
    "izkustvo": "изкуството Ренесансът",
    "muzika": "музиката рок културата",
    "ezik": "църковнославянският българският език",
    "demokracia": "демокрацията изборите",
    "medii": "медиите пропагандата",
    "lazhata": "лъжата подмяната",
    "tehnika": "роботът изкуственият интелект",
    "semeystvo": "семейството възпитанието",
    "globalizam": "глобализмът европейските ценности",
    "konspiracii": "конспирацията задкулисието",
}

# ── Scoring defaults ─────────────────────────────────────────────────────
DEFAULT_MIN_HITS = 5       # minimum raw pattern hits in an episode
DEFAULT_MIN_PER10K = 4.5   # minimum hits per 10 000 words
TITLE_WEIGHT = 0.9         # weight floor when the title names the theme
MAX_THEMES_PER_EPISODE = 6

# Edges: keep pairs sharing enough episodes, then prune to the strongest
EDGE_MIN_SHARED = 4
EDGE_MIN_OVERLAP = 0.3
EDGE_TOP_PER_NODE = 4


def _get_duration(data):
    snippets = data.get("snippets") or data.get("segments", [])
    return snippets[-1].get("start", 0) if snippets else 0


def _is_reupload(dur_a, dur_b):
    if dur_a == 0 or dur_b == 0:
        return False
    return abs(dur_a - dur_b) / max(dur_a, dur_b) < 0.05


def load_episodes():
    """Load transcripts, deduplicating re-uploads (same number, ~same length).
    Prefers the version whose title carries the (Беседа N) label."""
    episodes = []
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        episodes.append(
            {
                "video_id": data["video_id"],
                "title": data.get("title", ""),
                "episode_number": data.get("episode_number", 0),
                "text": data.get("full_text", ""),
                "_duration": _get_duration(data),
            }
        )

    seen = {}
    unique = []
    for ep in episodes:
        n = ep["episode_number"]
        if n in seen and _is_reupload(seen[n]["_duration"], ep["_duration"]):
            prev = seen[n]
            has_label = f"(Беседа {n})" in ep["title"]
            prev_has = f"(Беседа {n})" in prev["title"]
            if has_label and not prev_has:
                unique[unique.index(prev)] = ep
                seen[n] = ep
            continue
        unique.append(ep)
        seen[n] = ep
    return unique


def main():
    themes = []
    for t in THEMES:
        themes.append(
            {
                **t,
                "regex": re.compile(r"\b(?:" + t["patterns"] + r")", re.IGNORECASE),
                "min_hits": t.get("min_hits", DEFAULT_MIN_HITS),
                "min_per10k": t.get("min_per10k", DEFAULT_MIN_PER10K),
                "episodes": [],  # [video_id, per10k, title_hit]
            }
        )

    episodes = load_episodes()
    ep_meta = {}

    for ep in episodes:
        text = ep["text"].lower()
        title = ep["title"].lower()
        words = max(1, len(text.split()))
        ep_meta[ep["video_id"]] = {
            "n": ep["episode_number"],
            "title": ep["title"],
            "themes": [],
        }

        candidates = []
        for t in themes:
            hits = sum(1 for _ in t["regex"].finditer(text))
            per10k = hits * 10000.0 / words
            title_hit = bool(t["regex"].search(title))
            if title_hit or (hits >= t["min_hits"] and per10k >= t["min_per10k"]):
                candidates.append((t, per10k, title_hit))

        # Keep the strongest themes per episode: title matches always stay
        candidates.sort(key=lambda c: (not c[2], -c[1]))
        for t, per10k, title_hit in candidates[:MAX_THEMES_PER_EPISODE]:
            t["episodes"].append((ep["video_id"], per10k, title_hit))

    # Normalize weights within each theme (log-scaled against the theme max)
    out_themes = []
    for t in themes:
        if not t["episodes"]:
            continue
        max_per10k = max(p for _, p, _ in t["episodes"]) or 1.0
        rows = []
        for vid, per10k, title_hit in t["episodes"]:
            w = math.log1p(per10k) / math.log1p(max_per10k)
            if title_hit:
                w = max(w, TITLE_WEIGHT)
            rows.append((vid, round(min(1.0, w), 3)))
            ep_meta[vid]["themes"].append(t["id"])
        rows.sort(key=lambda r: -r[1])
        out_themes.append(
            {
                "id": t["id"],
                "label": t["label"],
                "group": t["group"],
                "description": t["description"],
                "query": QUERIES.get(t["id"], t["label"]),
                "count": len(rows),
                "episodes": rows,
            }
        )

    # Co-occurrence edges
    sets = {t["id"]: {vid for vid, _ in t["episodes"]} for t in out_themes}
    raw_edges = []
    ids = [t["id"] for t in out_themes]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            shared = len(sets[a] & sets[b])
            if shared < EDGE_MIN_SHARED:
                continue
            overlap = shared / min(len(sets[a]), len(sets[b]))
            if overlap < EDGE_MIN_OVERLAP:
                continue
            raw_edges.append(
                {
                    "source": a,
                    "target": b,
                    "shared": shared,
                    "weight": round(overlap, 3),
                    "_score": overlap * math.sqrt(shared),
                }
            )

    # Prune to each node's strongest edges (union), keeping the map legible
    by_node = {}
    for e in raw_edges:
        by_node.setdefault(e["source"], []).append(e)
        by_node.setdefault(e["target"], []).append(e)
    kept = set()
    for node, edges in by_node.items():
        edges.sort(key=lambda e: -e["_score"])
        for e in edges[:EDGE_TOP_PER_NODE]:
            kept.add(id(e))
    edges = [
        {k: v for k, v in e.items() if not k.startswith("_")}
        for e in raw_edges
        if id(e) in kept
    ]

    # Ensure no theme node floats disconnected if it has any relation at all
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    for t in out_themes:
        if t["id"] in connected:
            continue
        best, best_score = None, 0.0
        for other in out_themes:
            if other["id"] == t["id"]:
                continue
            shared = len(sets[t["id"]] & sets[other["id"]])
            if shared < 2:
                continue
            overlap = shared / min(len(sets[t["id"]]), len(sets[other["id"]]))
            score = overlap * math.sqrt(shared)
            if score > best_score:
                best, best_score = other, score
        if best:
            shared = len(sets[t["id"]] & sets[best["id"]])
            edges.append(
                {
                    "source": t["id"],
                    "target": best["id"],
                    "shared": shared,
                    "weight": round(shared / min(len(sets[t["id"]]), len(sets[best["id"]])), 3),
                }
            )

    result = {
        "version": 1,
        "groups": GROUPS,
        "themes": out_themes,
        "links": edges,
        "episodes": ep_meta,
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    # ── Console report for review ──
    print(f"Episodes analyzed: {len(episodes)}")
    print(f"Themes with episodes: {len(out_themes)} / {len(THEMES)}")
    print(f"Edges: {len(edges)}")
    print(f"Output: {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)\n")
    for t in sorted(out_themes, key=lambda x: -x["count"]):
        print(f"  {t['count']:4d}  {t['label']}")
    untagged = [m for m in ep_meta.values() if not m["themes"]]
    print(f"\nEpisodes with no theme: {len(untagged)}")
    for m in sorted(untagged, key=lambda m: m["n"])[:20]:
        print(f"  ({m['n']}) {m['title']}")


if __name__ == "__main__":
    main()
