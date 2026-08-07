#!/usr/bin/env python3
"""
Sprzątanie `data/geocoding_cache.json` ze śmieciowych kluczy (2026-08-07).

Po co: cache to nie tylko oszczędność zapytań do Nominatim — `AddressParser`
buduje z jego kluczy whitelistę `_known_streets` (trzeci fallback parsera).
Każdy śmieć, który raz się zgeokodował („pod nr 60", „Dostępne 15", „Duze
nowoczesne"), staje się więc „znaną ulicą" i uwiarygadnia kolejne takie
parsowania. To pętla sprzężenia zwrotnego, którą ten skrypt przerywa.

Bezpieczeństwo (dlatego można to puścić bez obaw o mapę):
  - klucz używany przez JAKĄKOLWIEK ofertę (jako `address.full` lub
    `address.street`) NIE jest usuwany — więc żadna pinezka się nie rusza,
  - klucz odpowiadający realnej ulicy Lublina (z uwzględnieniem odmiany,
    `street_whitelist`) też zostaje — to normalny, użyteczny cache,
  - usuwamy wyłącznie klucze, które są jednocześnie nieużywane i nie są ulicą.

Zmierzone 2026-08-07: 130 kluczy do usunięcia z 2022; parser po sprzątaniu
zwraca identyczne adresy dla wszystkich aktywnych ofert (0 utraconych, 0 zmian).

Użycie (domyślnie sucha próba — NIE zapisuje):
    cd src && python clean_geocoding_cache.py
    cd src && python clean_geocoding_cache.py --apply
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
from atomic_json import atomic_write_json
from street_whitelist import name_variants

NUMBER_SUFFIX_RE = re.compile(r'\s+\d+\S*$')


def _used_addresses(offers: list) -> set:
    """Adresy, na których stoją oferty — tych kluczy nie wolno ruszać."""
    used = set()
    for offer in offers:
        address = offer.get('address')
        if not isinstance(address, dict):
            continue
        for field in ('full', 'street'):
            value = (address.get(field) or '').strip().lower()
            if value:
                used.add(value)
    return used


def street_forms(whitelist_path: str = None) -> set:
    """Wszystkie warianty zapisu realnych nazw ulic (mianownik, odmiana, skrót)."""
    path = Path(whitelist_path or Path(paths.DATA_DIR) / 'streets_lublin.json')
    try:
        names = json.loads(path.read_text(encoding='utf-8')).get('names', [])
    except (OSError, json.JSONDecodeError):
        return set()
    forms = set()
    for name in names:
        forms |= name_variants(name)
    return forms


def find_junk_keys(cache: dict, offers: list, street_forms: set) -> list:
    """Klucze nieużywane przez żadną ofertę i nieodpowiadające realnej ulicy."""
    used = _used_addresses(offers)
    junk = []
    for key in cache:
        if key.strip().lower() in used:
            continue
        base = NUMBER_SUFFIX_RE.sub('', key).strip()
        if base and (name_variants(base) & street_forms):
            continue
        junk.append(key)
    return junk


def main():
    ap = argparse.ArgumentParser(description='Usuwa śmieciowe klucze z cache geokodera')
    ap.add_argument('--apply', action='store_true', help='zapisz zmiany (domyślnie sucha próba)')
    ap.add_argument('--limit-preview', type=int, default=30, help='ile kluczy wypisać')
    args = ap.parse_args()

    cache = json.loads(Path(paths.GEOCODING_CACHE_JSON).read_text(encoding='utf-8'))
    offers = json.loads(Path(paths.OFFERS_JSON).read_text(encoding='utf-8'))['offers']
    forms = street_forms()
    if not forms:
        print('⛔ Brak whitelisty ulic (data/streets_lublin.json) — bez niej nie da się '
              'bezpiecznie odróżnić śmiecia od ulicy. Przerywam.')
        return 1

    junk = find_junk_keys(cache, offers, forms)
    print(f'📋 Wpisów w cache: {len(cache)}')
    print(f'   🗑️  do usunięcia (nieużywane + nie-ulica): {len(junk)}')
    print(f'   ✅ zostaje: {len(cache) - len(junk)}')
    for key in sorted(junk)[:args.limit_preview]:
        print(f'      {key!r}')
    if len(junk) > args.limit_preview:
        print(f'      … i {len(junk) - args.limit_preview} więcej')

    if not junk:
        return 0
    if not args.apply:
        print('\n🔍 Sucha próba — nic nie zapisano. Uruchom z --apply, żeby usunąć.')
        return 0

    for key in junk:
        cache.pop(key, None)
    atomic_write_json(paths.GEOCODING_CACHE_JSON, cache)
    print(f'\n💾 Zapisano {paths.GEOCODING_CACHE_JSON} (usunięto {len(junk)} kluczy)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
