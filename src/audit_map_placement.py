#!/usr/bin/env python3
"""
Audyt jakości umieszczenia ofert na mapie (2026-08-06).

Sprawdza, czy pinezka oferty faktycznie stoi pod adresem, który wyparsował
`address_parser` — bo mapa rysuje „kroplę" (adres dokładny) dla KAŻDEJ oferty
z `has_number=True`, niezależnie od tego, czy geokoder trafił w budynek, czy
tylko w środek ulicy.

Dwa niezależne źródła prawdy (OSM):
  1. Overpass — punkty adresowe (`addr:street` + `addr:housenumber`) w bboxie
     Lublina → dystans pinezki od realnego budynku o tym numerze.
  2. Nominatim reverse — co faktycznie stoi w punkcie, w którym jest pinezka
     (uzupełnia lukę: część budynków w OSM nie ma taga `addr:street`).

Werdykty:
  DOKLADNA        — pinezka na właściwym budynku (≤50 m / zgodny numer w reverse)
  PRZESUNIETA     — właściwa ulica, 50–150 m od budynku
  SASIEDNI_BUDYNEK— właściwa ulica, ale reverse zwraca inny numer
  SRODEK_ULICY    — pinezka na linii ulicy (geokoder cofnął się do samej ulicy)
  ZLA_LOKALIZACJA — >150 m od budynku o tym numerze
  ZLA_ULICA       — pinezka na zupełnie innej ulicy
  ADRES_WIDMO     — „ulica" z parsera nie istnieje w Lublinie (błąd parsera)
  BRAK_GPS        — brak współrzędnych (oferta ląduje w warstwie „bez lokacji")

Użycie:
    cd src && python audit_map_placement.py                 # pełny audyt (sieć)
    python audit_map_placement.py --offline                 # tylko z cache'ów
    python audit_map_placement.py --all                     # też nieaktywne
    python audit_map_placement.py --json /tmp/raport.json

Cache'e pobranych danych OSM trzymamy poza repo (domyślnie w katalogu
tymczasowym) — to dane pomocnicze audytu, nie źródło prawdy projektu.
"""
import argparse
import collections
import json
import math
import re
import statistics
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
from geocoder import LUBLIN_BBOX, to_nominative

USER_AGENT = 'sonar-mieszkaniowy-audit/1.0 (https://github.com/Bonaventura-EW/SONAR-MIESZKANIOWY)'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
NOMINATIM_REVERSE = 'https://nominatim.openstreetmap.org/reverse'
REVERSE_DELAY = 1.25          # s — polityka Nominatim: max 1 zapytanie/s
CACHE_DIR = Path(tempfile.gettempdir()) / 'sonar_map_audit'

# Progi dystansu pinezka ↔ budynek z OSM (metry)
DIST_OK = 50            # w obrębie budynku/podwórka — pinezka dobra
DIST_SHIFTED = 150      # ta sama ulica, ale widocznie obok

PREFIX_RE = re.compile(r'^(ul\.?|ulica|al\.?|aleja|aleje|pl\.?|plac|os\.?|osiedle|rondo|skwer)\s+', re.I)
PL_MAP = str.maketrans('ąćęłńóśźż', 'acelnoszz')

# Człony, które zmieniają tożsamość ulicy: „Boczna Lubomelskiej" ≠ „Lubomelska"
DISTINCT_PREFIXES = {'boczna', 'mala', 'maly', 'wielka', 'nowa', 'stara', 'krotka', 'dluga', 'gorna', 'dolna'}


# ---------------------------------------------------------------- normalizacja
def deacc(text: str) -> str:
    """Lowercase bez polskich znaków — 'Chodżki' i 'Chodźki' mają dać to samo."""
    low = text.lower().translate(PL_MAP)
    return ''.join(c for c in unicodedata.normalize('NFD', low) if unicodedata.category(c) != 'Mn')


def norm_street(name: str) -> str:
    if not name:
        return ''
    cleaned = PREFIX_RE.sub('', name.strip().lower())
    cleaned = re.sub(r'[^\w\sąćęłńóśźż-]', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def street_variants(name: str) -> set:
    """Warianty nazwy ulicy: oryginał, mianownik, sam ostatni człon (nazwisko)."""
    base = norm_street(name)
    if not base:
        return set()
    out = {base, norm_street(to_nominative(base))}
    tokens = base.split()
    if len(tokens) > 1:
        out.add(norm_street(' '.join(to_nominative(t) for t in tokens)))
        out.add(tokens[-1])
        out.add(norm_street(to_nominative(tokens[-1])))
    return {deacc(v) for v in out if v}


def norm_number(num) -> str:
    return '' if num is None else str(num).strip().lower().replace(' ', '')


def numbers_match(offer_num: str, osm_num: str) -> bool:
    """'12' pasuje do '12', '12a' i do '12/14' (OSM lubi numery zbiorcze)."""
    if not offer_num or not osm_num:
        return False
    osm_num = osm_num.strip().lower().replace(' ', '')
    if offer_num == osm_num:
        return True
    return offer_num in [p.strip() for p in re.split(r'[\/,;-]', osm_num)]


def streets_match(offer_street: str, osm_street: str) -> bool:
    """Czy nazwa ulicy z oferty opisuje tę samą ulicę co nazwa z OSM."""
    if not offer_street or not osm_street:
        return False
    offer_vs = street_variants(offer_street)
    osm_norm = deacc(norm_street(osm_street))
    if osm_norm in offer_vs:
        return True
    osm_tokens = osm_norm.split()
    # 'Chodźki' ⊂ 'Doktora Witolda Chodźki' — ale 'Lubomelskiej' ⊄ 'Boczna Lubomelskiej'
    if osm_tokens and osm_tokens[0] in DISTINCT_PREFIXES:
        return False
    for variant in offer_vs:
        v_tokens = variant.split()
        n = len(v_tokens)
        if n and any(osm_tokens[i:i + n] == v_tokens for i in range(len(osm_tokens) - n + 1)):
            return True
    return deacc(to_nominative(osm_tokens[-1])) in offer_vs


def dist_m(lat1, lon1, lat2, lon2) -> float:
    return math.hypot((lat1 - lat2) * 111320.0,
                      (lon1 - lon2) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2)))


# Skąd parser mógł wziąć numer, jeśli w treści nie ma pary „ulica numer"
FAKE_NUMBER_SOURCES = [
    ('N-pokojowe', r'{n}\s*[- ]?\s*(pokojowe|pokojowa|pokoi|pokoje|pok\b)'),
    ('metraż', r'{n}\s*(m2|m²|mkw|m kw|metr)'),
    ('piętro', r'(pietro|pietrze)\s*{n}|{n}\s*(pietro|pietrze)'),
    ('data „od N"', r'(od|do)\s*{n}\b'),
]


def number_support(street: str, number: str, text: str):
    """Czy w treści ogłoszenia w ogóle stoi „ulica numer"?

    Parser składa adres z całego tekstu (tytuł + opis), więc numer bywa
    doklejany z zupełnie innego zdania („mieszkanie 2-pokojowe … ul. Zana"
    → „Zana 2"). Taka oferta dostaje na mapie kroplę „adres dokładny",
    choć numeru budynku nikt nie podał.

    Zwraca (potwierdzony: bool, domniemane_źródło_numeru: str|None).
    """
    if not street or not number or not text:
        return True, None                      # nie ma czego weryfikować
    flat = deacc(' '.join(text.split()))
    last = deacc(street.split()[-1])
    stem = last[:-3] if len(last) > 6 else last[:-2] if len(last) > 4 else last
    num = deacc(str(number))
    pair = re.compile(re.escape(stem) + r'[a-z]{0,4}[.,]?\s*(?:nr\.?\s*)?' + re.escape(num) + r'(?![0-9])')
    if pair.search(flat):
        return True, None
    bare = re.escape(num.rstrip('m'))
    for label, tpl in FAKE_NUMBER_SOURCES:
        if re.search(tpl.format(n=bare), flat):
            return False, label
    return False, 'nieznane'


# ------------------------------------------------------------------- pobieranie
def _http_json(url, data=None, timeout=120, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except Exception as exc:                      # noqa: BLE001 — audyt, nie produkcja
            if attempt == retries - 1:
                raise
            print(f'   ⏳ retry {attempt + 1}/{retries - 1} ({type(exc).__name__})')
            time.sleep(4 * (attempt + 1))
    return None


def load_osm_addresses(offline: bool, refresh: bool) -> dict:
    """Punkty adresowe z OSM: {ulica_deacc: [(numer, lat, lon), ...]}."""
    cache = CACHE_DIR / 'osm_addresses.json'
    if refresh or not cache.exists():
        if offline:
            print('⚠️  Brak cache adresów OSM, a tryb --offline — pomijam warstwę Overpass')
            return {}
        bbox = f"{LUBLIN_BBOX['min_lat']},{LUBLIN_BBOX['min_lon']},{LUBLIN_BBOX['max_lat']},{LUBLIN_BBOX['max_lon']}"
        query = f'''[out:json][timeout:240];
(
  node["addr:housenumber"]["addr:street"]({bbox});
  way["addr:housenumber"]["addr:street"]({bbox});
  relation["addr:housenumber"]["addr:street"]({bbox});
);
out center tags;'''
        print('🌍 Overpass: pobieram punkty adresowe Lublina…')
        raw = _http_json(OVERPASS_URL, data=urllib.parse.urlencode({'data': query}).encode(), timeout=280)
        points = []
        for el in raw['elements']:
            lat = el.get('lat') or (el.get('center') or {}).get('lat')
            lon = el.get('lon') or (el.get('center') or {}).get('lon')
            tags = el.get('tags', {})
            if lat and lon:
                points.append({'street': tags.get('addr:street'), 'num': tags.get('addr:housenumber'),
                               'lat': lat, 'lon': lon})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(points, ensure_ascii=False), encoding='utf-8')
        print(f'   ✅ {len(points)} punktów adresowych')
    points = json.loads(cache.read_text(encoding='utf-8'))
    index = collections.defaultdict(list)
    for p in points:
        key = deacc(norm_street(p['street']))
        if key:
            index[key].append((norm_number(p['num']), p['lat'], p['lon']))
    return index


def load_osm_street_names(offline: bool, refresh: bool) -> list:
    """Nazwy ulic Lublina (do wykrywania adresów-widm z parsera)."""
    cache = CACHE_DIR / 'osm_street_names.json'
    if refresh or not cache.exists():
        if offline:
            print('⚠️  Brak cache nazw ulic, a tryb --offline — pomijam detekcję adresów-widm')
            return []
        bbox = f"{LUBLIN_BBOX['min_lat']},{LUBLIN_BBOX['min_lon']},{LUBLIN_BBOX['max_lat']},{LUBLIN_BBOX['max_lon']}"
        query = f'[out:json][timeout:180];way["highway"]["name"]({bbox});out tags;'
        print('🌍 Overpass: pobieram nazwy ulic…')
        raw = _http_json(OVERPASS_URL, data=urllib.parse.urlencode({'data': query}).encode(), timeout=280)
        names = sorted({el['tags']['name'] for el in raw['elements'] if el.get('tags', {}).get('name')})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(names, ensure_ascii=False), encoding='utf-8')
        print(f'   ✅ {len(names)} nazw ulic')
    return json.loads(cache.read_text(encoding='utf-8'))


class ReverseGeocoder:
    """Nominatim reverse z cache na dysku (1 zapytanie/s, ~1 zapytanie na punkt)."""

    def __init__(self, offline: bool):
        self.offline = offline
        self.path = CACHE_DIR / 'reverse_cache.json'
        self.cache = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.new_lookups = 0

    def lookup(self, lat, lon):
        key = f'{round(lat, 7)},{round(lon, 7)}'
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return None
        url = NOMINATIM_REVERSE + '?' + urllib.parse.urlencode({
            'lat': lat, 'lon': lon, 'format': 'jsonv2', 'zoom': 18,
            'addressdetails': 1, 'accept-language': 'pl'})
        raw = _http_json(url, timeout=25, retries=4)
        addr = raw.get('address', {})
        self.cache[key] = {'road': addr.get('road'), 'house': addr.get('house_number'),
                           'suburb': addr.get('suburb') or addr.get('city_district'),
                           'display': raw.get('display_name')}
        self.new_lookups += 1
        time.sleep(REVERSE_DELAY)
        return self.cache[key]

    def save(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding='utf-8')


# ------------------------------------------------------------------- klasyfikacja
def resolve_street_key(variants: set, index: dict) -> set:
    """Klucze ulic z indeksu OSM pasujące do wariantów nazwy z oferty."""
    hits = {v for v in variants if v in index}
    if hits:
        return hits
    for v in variants:
        last = v.split()[-1] if v else ''
        for cand in index:
            cand_tokens = cand.split()
            if cand_tokens[-1] == last and not (cand_tokens[0] in DISTINCT_PREFIXES and len(cand_tokens) > 1):
                hits.add(cand)
    return hits


def is_real_street(variants: set, known_tokens: list) -> bool:
    """Czy którykolwiek wariant nazwy występuje w nazwach ulic Lublina.

    Dopasowanie po ciągu członów, nie po całej nazwie — parser często zapisuje
    skrót ('Kompozytorów' zamiast 'Kompozytorów Polskich', 'Chodźki' zamiast
    'Doktora Witolda Chodźki').
    """
    for variant in variants:
        v_tokens = variant.split()
        n = len(v_tokens)
        for tokens in known_tokens:
            for i in range(len(tokens) - n + 1):
                if tokens[i:i + n] == v_tokens:
                    return True
    return False


def audit(offers, osm_index, street_names, reverse, cache_streets):
    known_tokens = [deacc(norm_street(n)).split() for n in street_names]
    rows = []
    for offer in offers:
        addr = offer.get('address') or {}
        coords = addr.get('coords')
        street, number = addr.get('street') or '', norm_number(addr.get('number'))
        # bywa, że parser zostawia puste `street`, a nazwa siedzi w `full`
        street_for_match = street or re.sub(r'\s+\d+\w*$', '', addr.get('full') or '')
        variants = street_variants(street_for_match)
        street_real = is_real_street(variants, known_tokens)
        row = {
            'id': offer.get('id'), 'url': offer.get('url'), 'full': addr.get('full'),
            'street': street, 'number': addr.get('number'),
            'price': (offer.get('price') or {}).get('current'),
            'first_seen': offer.get('first_seen'),
            'lat': coords['lat'] if coords else None,
            'lon': coords['lon'] if coords else None,
            'street_real': street_real,
            'street_centroid': False,
        }
        confirmed, guess = number_support(street, number, offer.get('description') or '')
        row['number_in_text'] = confirmed
        row['number_source_guess'] = guess
        if not coords:
            row['verdict'] = 'BRAK_GPS'
            rows.append(row)
            continue

        # czy geokoder zwrócił dokładnie ten sam punkt, co dla samej ulicy?
        for key in {street.strip().lower(), re.sub(r'\s+\S+$', '', addr.get('full') or '').strip().lower()}:
            cached = cache_streets.get(key)
            if cached and dist_m(coords['lat'], coords['lon'], cached['lat'], cached['lon']) < 5:
                row['street_centroid'] = True

        # 1) twarde dopasowanie: budynek o tym numerze w OSM
        best = None
        for key in resolve_street_key(variants, osm_index):
            for osm_num, lat, lon in osm_index[key]:
                if number and numbers_match(number, osm_num):
                    d = dist_m(coords['lat'], coords['lon'], lat, lon)
                    if best is None or d < best[0]:
                        best = (d, key, osm_num)
        if best:
            row['dist'] = round(best[0], 1)
            row['osm_match'] = f'{best[1]} {best[2]}'
            row['verdict'] = ('DOKLADNA' if best[0] <= DIST_OK else
                              'PRZESUNIETA' if best[0] <= DIST_SHIFTED else 'ZLA_LOKALIZACJA')
            rows.append(row)
            continue

        # 2) miękkie: co Nominatim widzi w punkcie pinezki
        rev = reverse.lookup(coords['lat'], coords['lon'])
        if rev:
            row['rev_road'], row['rev_house'] = rev.get('road'), rev.get('house')
            row['rev_suburb'] = rev.get('suburb')
        if not street_real:
            row['verdict'] = 'ADRES_WIDMO'
        elif not number:
            # has_number=True, a numeru nie ma — mapa i tak rysuje kroplę
            row['verdict'] = 'BRAK_NUMERU'
        elif not rev or not rev.get('road'):
            row['verdict'] = 'SRODEK_ULICY'
        elif streets_match(street_for_match, rev['road']):
            if rev.get('house') and numbers_match(number, rev['house']):
                row['verdict'] = 'DOKLADNA'
            elif rev.get('house'):
                row['verdict'] = 'SASIEDNI_BUDYNEK'
            else:
                row['verdict'] = 'SRODEK_ULICY'
        else:
            row['verdict'] = 'ZLA_ULICA'
        rows.append(row)
    return rows


ORDER = ['DOKLADNA', 'SASIEDNI_BUDYNEK', 'PRZESUNIETA', 'SRODEK_ULICY', 'BRAK_NUMERU',
         'ZLA_LOKALIZACJA', 'ZLA_ULICA', 'ADRES_WIDMO', 'BRAK_GPS']


def report(rows):
    counts = collections.Counter(r['verdict'] for r in rows)
    total = len(rows)
    print(f'\n{"=" * 62}\n📍 AUDYT PINEZEK — {total} ofert z adresem „dokładnym" (has_number=True)\n{"=" * 62}')
    for verdict in ORDER:
        n = counts.get(verdict, 0)
        if n:
            print(f'  {verdict:17} {n:4}   {n / total * 100:5.1f}%')
    good = counts.get('DOKLADNA', 0)
    print(f'\n  ✅ pinezka pod właściwym budynkiem: {good}/{total} ({good / total * 100:.1f}%)')
    dists = [r['dist'] for r in rows if r.get('dist') is not None]
    if dists:
        print(f'  📏 dystans do budynku z OSM (n={len(dists)}): mediana {statistics.median(dists):.1f} m, '
              f'p90 {sorted(dists)[int(0.9 * len(dists))]:.1f} m, max {max(dists):.1f} m')
    print(f'  🏚️  „ulica" nieistniejąca w Lublinie: {sum(1 for r in rows if not r["street_real"])}')
    print(f'  🎯 pinezka = geokod samej ulicy:      {sum(1 for r in rows if r["street_centroid"])}')
    fake = [r for r in rows if not r['number_in_text']]
    print(f'  🃏 numer domu NIE występuje w treści: {len(fake)} '
          f'(z tego {sum(1 for r in fake if r["verdict"] == "DOKLADNA")} z werdyktem DOKLADNA)')

    if fake:
        sources = collections.Counter(r['number_source_guess'] for r in fake)
        print(f'\n--- FALSZYWA_PRECYZJA ({len(fake)}) — numer dorobiony z innego zdania ---')
        print(f'    źródła: {dict(sources)}')
        for r in sorted(fake, key=lambda x: (x['verdict'], x['full'] or '')):
            print(f"  {(r['full'] or '?')[:30]:31} | {r['verdict']:16} | numer z: "
                  f"{str(r['number_source_guess'])[:12]:13} | {r['id'][-14:]}")

    for verdict in ORDER:
        group = [r for r in rows if r['verdict'] == verdict and verdict != 'DOKLADNA']
        if not group:
            continue
        print(f'\n--- {verdict} ({len(group)}) ---')
        for r in sorted(group, key=lambda x: -(x.get('dist') or 0)):
            detail = f"{r['dist']} m od {r['osm_match']}" if r.get('dist') is not None else \
                     f"pinezka: {r.get('rev_road') or '?'} {r.get('rev_house') or ''}".strip()
            print(f"  {(r['full'] or '?')[:30]:31} | {detail[:44]:45} | {r['id'][-14:]}")


def main():
    ap = argparse.ArgumentParser(description='Audyt umieszczenia pinezek na mapie')
    ap.add_argument('--all', action='store_true', help='także oferty nieaktywne')
    ap.add_argument('--offline', action='store_true', help='tylko cache, zero zapytań do OSM')
    ap.add_argument('--refresh', action='store_true', help='odśwież cache danych OSM')
    ap.add_argument('--json', dest='json_out', help='zapisz pełny raport do pliku JSON')
    args = ap.parse_args()

    db = json.loads(Path(paths.OFFERS_JSON).read_text(encoding='utf-8'))
    offers = [o for o in db['offers']
              if (args.all or o.get('active')) and (o.get('address') or {}).get('has_number')]
    print(f'📥 Ofert do audytu: {len(offers)} ({"wszystkie" if args.all else "aktywne"})')

    osm_index = load_osm_addresses(args.offline, args.refresh)
    street_names = load_osm_street_names(args.offline, args.refresh)
    cache_raw = json.loads(Path(paths.GEOCODING_CACHE_JSON).read_text(encoding='utf-8'))
    cache_streets = {k.strip().lower(): v for k, v in cache_raw.items() if v}

    reverse = ReverseGeocoder(args.offline)
    try:
        rows = audit(offers, osm_index, street_names, reverse, cache_streets)
    finally:
        reverse.save()
    if reverse.new_lookups:
        print(f'🔎 Nowych zapytań reverse do Nominatim: {reverse.new_lookups}')

    report(rows)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'\n💾 Raport: {args.json_out}')


if __name__ == '__main__':
    main()
