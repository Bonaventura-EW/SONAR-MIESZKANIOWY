#!/usr/bin/env python3
"""
Jednorazowa migracja adresów w bazie po poprawce parsera (FIX 2026-08-06).

Po co: parser dorabiał numery domów z innego zdania („ul. ZANA Mieszkanie
2 pokojowe" → „Zana 2"). Poprawka działa dla nowych parsowań, ale oferty już
zapisane w bazie zostałyby z błędnym numerem na zawsze — zwłaszcza **nieaktywne**,
bo tych scraper w ogóle nie odwiedza, więc `_update_existing_offer` nigdy się dla
nich nie uruchomi. Na 2026-08-06 dotyczyło to 84 nieaktywnych i 43 aktywnych ofert.

Jak to robi (bez sieci):
  - opis oferty jest w bazie, więc adres przeliczamy z zapisanego tekstu,
  - korektę stosujemy TYLKO gdy nowy parse daje **tę samą ulicę** bez numeru —
    nigdy nie przenosimy oferty na inny adres,
  - współrzędne: bierzemy punkt ulicy z `geocoding_cache.json`, a gdy go tam nie
    ma, zostawiamy dotychczasowe (to realny budynek przy tej samej ulicy) i tylko
    obniżamy `precision` do 'street'. Zero zapytań do Nominatim.

Bezpiecznik: gdy korekta miałaby dotknąć więcej niż MAX_RETRACTION_RATIO bazy,
migracja się nie wykonuje (to znaczy, że coś jest nie tak z parserem, a nie z bazą).

Uruchomienie ręczne (domyślnie sucha próba — NIE zapisuje):
    cd src && python address_migration.py
    cd src && python address_migration.py --apply

W skanie migracja odpala się sama raz, po zmianie `ADDRESS_PARSER_VERSION`.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
from address_parser import AddressParser
from atomic_json import atomic_write_json

# Wersja kontraktu parsera adresów. Bump = migracja przeliczy bazę raz jeszcze.
ADDRESS_PARSER_VERSION = '2026-08-06'

# Ile ofert może maksymalnie zmienić adres, zanim uznamy to za awarię parsera.
# (Na 2026-08-06: 127 z 1219 ofert z numerem, czyli 10,4% — próg ma spory zapas.)
MAX_RETRACTION_RATIO = 0.25
# Poniżej tylu ofert z numerem odsetek nic nie znaczy — bezpiecznik śpi.
MIN_OFFERS_FOR_RATIO_GUARD = 20


def _key(value: str) -> str:
    return (value or '').strip().lower()


def retract_fake_numbers(offers: list, parser: AddressParser = None, geocoding_cache: dict = None) -> dict:
    """Wycofuje zmyślone numery domów z listy ofert (in-place, gdy `apply`).

    Zwraca dict ze statystykami i listą zmian; przy przekroczeniu bezpiecznika
    zwraca `blocked` z powodem i NIE modyfikuje ofert.
    """
    parser = parser or AddressParser()
    cache = {_key(k): v for k, v in (geocoding_cache or {}).items() if v}

    planned = []          # (offer, new_address)
    considered = 0
    stats = {'kept': 0, 'other_street': 0, 'unparsable': 0}

    for offer in offers:
        address = offer.get('address')
        if not isinstance(address, dict) or not address.get('number'):
            continue
        considered += 1
        parsed = parser.extract_address(offer.get('description') or '')
        if not parsed:
            stats['unparsable'] += 1
            continue
        if parsed.get('number'):
            stats['kept'] += 1
            continue
        if _key(parsed.get('street')) != _key(address.get('street')):
            # Nowy parse wskazuje inną ulicę — to już nie jest „wycofanie numeru",
            # tylko zmiana adresu. Za ryzykowne dla migracji wsadowej.
            stats['other_street'] += 1
            continue

        new_address = dict(address)
        new_address.update({
            'full': parsed['full'],
            'street': parsed.get('street', ''),
            'number': None,
            'has_number': False,
            'precision': 'street' if address.get('coords') else 'none',
        })
        # Punkt ulicy z cache jest spójny z tym, co dałby świeży geokod;
        # bez niego zostają dotychczasowe coords (budynek przy tej samej ulicy).
        street_coords = cache.get(_key(parsed['full']))
        if street_coords:
            new_address['coords'] = dict(street_coords)
        planned.append((offer, new_address))

    result = {
        'considered': considered,
        'to_fix': len(planned),
        'active_to_fix': sum(1 for o, _ in planned if o.get('active')),
        'inactive_to_fix': sum(1 for o, _ in planned if not o.get('active')),
        'from_cache_coords': sum(1 for o, a in planned
                                 if a.get('coords') and a.get('coords') != (o.get('address') or {}).get('coords')),
        'changes': [((o.get('address') or {}).get('full'), a['full'], bool(o.get('active')))
                    for o, a in planned],
        'blocked': None,
        **stats,
    }

    if considered >= MIN_OFFERS_FOR_RATIO_GUARD and len(planned) > considered * MAX_RETRACTION_RATIO:
        result['blocked'] = (
            f"Migracja adresów chciała zmienić {len(planned)} z {considered} ofert z numerem "
            f"({len(planned) / considered * 100:.0f}%, próg: {MAX_RETRACTION_RATIO * 100:.0f}%) — "
            f"to wygląda na awarię parsera, nie na porządki. Nic nie zmieniono."
        )
        return result

    for offer, new_address in planned:
        offer['address'] = new_address
    return result


def main():
    ap = argparse.ArgumentParser(description='Migracja adresów po poprawce parsera (FIX 2026-08-06)')
    ap.add_argument('--apply', action='store_true', help='zapisz zmiany (domyślnie sucha próba)')
    ap.add_argument('--limit-preview', type=int, default=25, help='ile zmian wypisać')
    args = ap.parse_args()

    db = json.loads(Path(paths.OFFERS_JSON).read_text(encoding='utf-8'))
    cache = json.loads(Path(paths.GEOCODING_CACHE_JSON).read_text(encoding='utf-8'))

    result = retract_fake_numbers(db['offers'], geocoding_cache=cache)

    print(f"\n📋 Ofert z numerem domu: {result['considered']}")
    print(f"   ✅ numer potwierdzony przez parser:      {result['kept']}")
    print(f"   🔧 do wycofania numeru:                 {result['to_fix']} "
          f"(aktywne: {result['active_to_fix']}, nieaktywne: {result['inactive_to_fix']})")
    print(f"      … z tego coords wzięte z cache ulicy: {result['from_cache_coords']}")
    print(f"   ⏭️  inna ulica w nowym parsowaniu (pomijane): {result['other_street']}")
    print(f"   ⏭️  parser nic nie zwraca (pomijane):         {result['unparsable']}")

    if result['blocked']:
        print(f"\n⛔ {result['blocked']}")
        return 1

    print(f"\nPrzykłady zmian:")
    for old, new, active in result['changes'][:args.limit_preview]:
        print(f"   {'🟢' if active else '⚪'} {str(old)[:30]:31} → {new}")

    if not args.apply:
        print(f"\n🔍 Sucha próba — nic nie zapisano. Uruchom z --apply, żeby zastosować.")
        return 0

    db['address_parser_version'] = ADDRESS_PARSER_VERSION
    atomic_write_json(paths.OFFERS_JSON, db)
    print(f"\n💾 Zapisano {paths.OFFERS_JSON} ({result['to_fix']} poprawionych adresów)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
