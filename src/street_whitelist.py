#!/usr/bin/env python3
"""
Whitelist realnych ulic i osiedli Lublina (snapshot z OpenStreetMap).

**Do czego to służy (i do czego NIE):**

Lista jest używana WYŁĄCZNIE do *wpuszczania* adresów ratunkowych — czyli tam,
gdzie alternatywą jest wyrzucenie całej oferty (`main._process_offer` →
`return None`). Nigdy nie odrzuca oferty ani nie kasuje adresu, który parser
znalazł normalną ścieżką.

Powód jest zmierzony: audyt z 2026-08-06 pokazał, że 114 aktywnych ofert (16%)
ma nazwę spoza tej listy, ale kilkadziesiąt z nich to **prawdziwe** adresy,
których OSM nie ma w formie użytej w ogłoszeniu („Osiedle Botanik", „Skłodowskiej",
„Aleja Racławickiej", „Wajdeloty"). Użycie whitelisty jako filtru odrzucającego
zdjęłoby te oferty z mapy. Jako lista akceptująca jest bezpieczna: im szersza,
tym więcej ofert ratujemy, a jej luki nikomu nie szkodzą.

Odświeżenie snapshotu (wymaga sieci, Overpass):
    cd src && python street_whitelist.py --update
"""
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

WHITELIST_JSON = str(Path(paths.DATA_DIR) / 'streets_lublin.json')
DISTRICTS_JSON = str(Path(paths.DATA_DIR) / 'districts_lublin.json')
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
USER_AGENT = 'sonar-mieszkaniowy/1.0 (https://github.com/Bonaventura-EW/SONAR-MIESZKANIOWY)'

PREFIX_RE = re.compile(r'^(ul\.?|ulica|ulicy|ulicą|al\.?|aleja|aleje|alei|pl\.?|plac|placu|os\.?|osiedle|osiedlu|rondo|skwer)\s+', re.I)
PL_MAP = str.maketrans('ąćęłńóśźż', 'acelnoszz')
# Numer domu („3", „12a", „4/2") — nigdy nie jest nazwą ani jej wariantem.
NUMBER_TOKEN_RE = re.compile(r'^\d+[a-z]?$', re.I)

# Te same reguły co w geocoder.to_nominative, ale importujemy leniwie —
# geocoder ciągnie geopy, a whitelist bywa używana w kontekstach bez sieci.
try:
    from geocoder import to_nominative, to_nominative_singular_feminine
except Exception:                                    # pragma: no cover
    def to_nominative(text):
        return text

    def to_nominative_singular_feminine(text):
        return ''


def deacc(text: str) -> str:
    """Lowercase bez polskich znaków — 'Chodżki' i 'Chodźki' mają dać to samo."""
    low = text.lower().translate(PL_MAP)
    return ''.join(c for c in unicodedata.normalize('NFD', low) if unicodedata.category(c) != 'Mn')


def norm_street(name: str) -> str:
    """Nazwa bez prefiksu (ul./al./os.) i bez interpunkcji, pojedyncze spacje."""
    if not name:
        return ''
    cleaned = PREFIX_RE.sub('', name.strip().lower())
    cleaned = re.sub(r'[^\w\sąćęłńóśźż-]', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def _tokens(name: str) -> list:
    """Człony nazwy; myślnik rozbijamy, bo 'Curie-Skłodowskiej' bywa pisane osobno."""
    return [t for t in re.split(r'[\s-]+', deacc(norm_street(name))) if t]


def name_variants(name: str, whole_only: bool = False) -> set:
    """Warianty ZAPYTANIA: oryginał, mianownik, sam ostatni człon.

    Celowo wąskie — nazwa z ogłoszenia jest tu tekstem podejrzanym i każde
    dodatkowe przekształcenie zwiększa ryzyko, że trafi w *inną* realną nazwę.
    Rozwijaniem form zajmuje się `index_variants`, po stronie snapshotu OSM.

    `whole_only` pomija wariant „sam ostatni człon" — używany tam, gdzie nazwa
    ma znaczyć całość, a nie swoją końcówkę (patrz `_district_variants`).
    """
    base = ' '.join(_tokens(name))
    if not base:
        return set()
    out = {base}
    tokens = base.split()
    out.add(' '.join(to_nominative(t) for t in tokens))
    # FIX 2026-08-08: sam numer nigdy nie jest wariantem nazwy. „Kwarcowa
    # Nowoczesne 3" wyglądało jak kompletna nazwa ulicy, bo człon „3" trafiał
    # w indeks (jest ulica z „3" w nazwie) — i sprzątanie etykiety odpuszczało,
    # uznając ją za poprawną.
    if len(tokens) > 1 and not whole_only and not NUMBER_TOKEN_RE.match(tokens[-1]):
        out.add(tokens[-1])
        out.add(to_nominative(tokens[-1]))
    return {deacc(v) for v in out if v}


def index_variants(name: str, whole_only: bool = False) -> set:
    """Warianty INDEKSU: jak wyżej + forma pojedyncza rodzaju żeńskiego.

    FIX 2026-08-08: bez niej „Racławickiej" nie łączyło się z „Aleje
    Racławickie" — mianownik zapytania daje „Racławicka", a OSM ma liczbę
    mnogą; realna ulica wyglądała przez to jak nie-ulica.

    Rozwijamy WYŁĄCZNIE stronę indeksu, bo l.mn.→l.poj. bywa dwuznaczne:
    dla zapytania „Piastowskie" (osiedle) dawało „Piastowska", czyli nazwę
    zupełnie innego, ale realnego miejsca — i osiedle zaczynało uchodzić za
    ulicę. Po stronie indeksu ten sam wariant tylko dokłada zapis nazwy, która
    i tak w OSM istnieje, więc nie może zmyśloną formą uwiarygodnić śmiecia.
    """
    out = set(name_variants(name, whole_only))
    if not out:
        return out
    tokens = ' '.join(_tokens(name)).split()
    forms = [to_nominative_singular_feminine(' '.join(tokens))]
    if len(tokens) > 1 and not whole_only:
        forms.append(to_nominative_singular_feminine(tokens[-1]))
    for form in forms:
        normalized = ' '.join(_tokens(form))
        if normalized:
            out.add(deacc(normalized))
    return out


@lru_cache(maxsize=2)
def _index(path: str = None, key: str = 'names'):
    """[(człony_nazwy, ...)] ze snapshotu — pusty, gdy pliku brak (fail-open).

    FIX 2026-08-08: każda nazwa wchodzi do indeksu we WSZYSTKICH swoich formach
    (`index_variants`), nie tylko w tej zapisanej w OSM. Bez tego „Racławickiej"
    nie trafiało w „Aleje Racławickie" i realna ulica uchodziła za nie-ulicę.
    Rozszerzamy tylko indeks — na 2890 ofertach dokłada to 2 rozpoznane ulice
    i zero nowych fałszywych, bo warianty opisują nazwy, które w OSM istnieją.
    """
    try:
        raw = json.loads(Path(path or WHITELIST_JSON).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return ()
    entries = set()
    for name in raw.get(key, []):
        if not name:
            continue
        for variant in index_variants(name):
            tokens = tuple(variant.split())
            if tokens:
                entries.add(tokens)
    return tuple(sorted(entries))


def is_street_name(name: str, path: str = None) -> bool:
    """Czy nazwa to ULICA (a nie osiedle, dzielnica czy teren).

    FIX 2026-08-08: `names` w snapshocie celowo obejmuje też osiedla i tereny —
    to dobre do *akceptowania* adresów ratunkowych, ale bezużyteczne, gdy trzeba
    rozstrzygnąć „czy ten adres w ogóle jest adresem ulicznym". `street_names`
    zawiera wyłącznie nazwy dróg (`highway` z OSM), więc „Botanik" czy
    „Osiedle Prestige" nie przejdą, a „Lipowa" i „Chodźki" tak.
    """
    return _matches(name, _index(path, 'street_names'))


@lru_cache(maxsize=1)
def _district_variants(path: str = None):
    """Warianty zapisu nazw dzielnic — dopasowanie musi być PEŁNE, nie po podciągu.

    `whole_only=True`: nazwa złożona liczy się tylko w całości. Sam ostatni człon
    to za mało — „Rury Jezuickie" robiło dzielnicę z ul. Jezuickiej, a „Osiedle
    Jagiellońskie" z ul. Jagiellońskiej. Dzielnice i tak są w liście pod swoimi
    krótkimi nazwami („Rury", „Czuby"), więc nic na tym nie tracimy.
    """
    try:
        raw = json.loads(Path(path or DISTRICTS_JSON).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    forms = set()
    for name in raw.get('names', []):
        forms |= index_variants(name, whole_only=True)
    return frozenset(forms)


def is_district_name(name: str, path: str = None) -> bool:
    """Czy nazwa to dzielnica/osiedle Lublina („Wrotków", „Czuby", „Osiedle Prestige").

    FIX 2026-08-08: takie adresy opisują OBSZAR, nie punkt — oferta z nimi nie
    dostaje pinezki, tylko trafia do warstwy „bez lokacji".

    W przeciwieństwie do `is_known_street` dopasowanie jest PEŁNE (wariant nazwy
    musi się zgadzać w całości), bo luźne dopasowanie po podciągu robiło z ulic
    dzielnice: „Racławickiej" trafiało w „Racławicka Dzielnica Mieszkaniowa"
    i realna ulica traciłaby pinezkę.
    """
    return bool(name_variants(name, whole_only=True) & _district_variants(path))


def is_known_street(name: str, path: str = None) -> bool:
    """Czy nazwa odpowiada realnej ulicy/osiedlu Lublina ze snapshotu OSM.

    Dopasowanie po ciągu członów, nie po całej nazwie — ogłoszenia skracają
    („Chodźki" zamiast „Doktora Witolda Chodźki") i odmieniają („Puławskiej").
    Brak snapshotu = False (funkcja tylko *wpuszcza*, więc brak listy oznacza
    po prostu brak dodatkowych ratunków, a nie utratę ofert).
    """
    return _matches(name, _index(path, 'names'))


@lru_cache(maxsize=1)
def _place_variants(path: str = None):
    """Warianty wszystkich nazw z szerokiej listy — do dopasowania PEŁNEGO."""
    try:
        raw = json.loads(Path(path or WHITELIST_JSON).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    forms = set()
    for name in raw.get('names', []):
        forms |= index_variants(name)
    return frozenset(forms)


def is_known_place(name: str, path: str = None) -> bool:
    """Czy nazwa w CAŁOŚCI odpowiada jakiejś nazwie z whitelisty.

    FIX 2026-08-08: `is_known_street` dopasowuje po podciągu, więc chroniło przed
    zdjęciem z mapy nawet śmieć „Nowe" (podciąg „Nowe Sady"). Tu wymagamy zgodności
    całego wariantu nazwy — to właściwe kryterium dla pytania „czy ta etykieta
    w ogóle jest czyimś adresem".
    """
    return bool(name_variants(name) & _place_variants(path))


def _matches(name: str, index) -> bool:
    """Czy którykolwiek wariant nazwy jest ciągiem członów którejś nazwy z indeksu."""
    if not index:
        return False
    for variant in name_variants(name):
        v_tokens = variant.split()
        n = len(v_tokens)
        if not n:
            continue
        for tokens in index:
            if any(tokens[i:i + n] == tuple(v_tokens) for i in range(len(tokens) - n + 1)):
                return True
    return False


def update_snapshot(path: str = None) -> int:
    """Pobiera świeżą listę nazw z Overpass i nadpisuje snapshot."""
    from datetime import date

    from atomic_json import atomic_write_json
    from geocoder import LUBLIN_BBOX

    bbox = (f"{LUBLIN_BBOX['min_lat']},{LUBLIN_BBOX['min_lon']},"
            f"{LUBLIN_BBOX['max_lat']},{LUBLIN_BBOX['max_lon']}")
    query = f'''[out:json][timeout:180];
(
  way["highway"]["name"]({bbox});
  relation["type"="associatedStreet"]["name"]({bbox});
  node["place"~"neighbourhood|suburb|quarter|city_block"]["name"]({bbox});
  way["landuse"="residential"]["name"]({bbox});
  way["place"~"neighbourhood|suburb|quarter"]["name"]({bbox});
);
out tags;'''
    req = urllib.request.Request(OVERPASS_URL,
                                 data=urllib.parse.urlencode({'data': query}).encode(),
                                 headers={'User-Agent': USER_AGENT})
    elements = json.loads(urllib.request.urlopen(req, timeout=280).read())['elements']
    names = sorted({e['tags']['name'] for e in elements if e.get('tags', {}).get('name')})
    if len(names) < 500:
        raise RuntimeError(f'Overpass zwrócił podejrzanie mało nazw ({len(names)}) — nie nadpisuję snapshotu')
    target = Path(path or WHITELIST_JSON)
    previous = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    atomic_write_json(str(target), {
        'generated_at': date.today().isoformat(),
        'source': 'OpenStreetMap / Overpass API (bbox = geocoder.LUBLIN_BBOX)',
        'query': 'highway+name, associatedStreet, place=neighbourhood|suburb|quarter|city_block, landuse=residential+name',
        'note': previous.get('note', 'Lista SŁUŻY WYŁĄCZNIE DO AKCEPTOWANIA adresów ratunkowych — nigdy do odrzucania ofert.'),
        'count': len(names),
        'names': names,
    })
    _index.cache_clear()
    return len(names)


if __name__ == '__main__':
    if '--update' in sys.argv:
        print(f'🌍 Pobieram nazwy ulic z Overpass…')
        print(f'✅ Zapisano {update_snapshot()} nazw do {WHITELIST_JSON}')
    else:
        data = json.loads(Path(WHITELIST_JSON).read_text(encoding='utf-8'))
        print(f'📋 Snapshot z {data["generated_at"]}: {data["count"]} nazw')
        for probe in ['Lipowa', 'Chodźki', 'Puławskiej', 'Osiedle Prestige', 'Wolne', 'Dostępne', 'Stokrotka']:
            print(f'   {probe:18} → {"✅ znana" if is_known_street(probe) else "❌ nieznana"}')
