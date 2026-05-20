#!/usr/bin/env python3
"""
Naprawia oferty w bazie które mają adres ale brak coords.
Uruchamiać ręcznie lub jako opcjonalny krok w Actions.

Użycie:
    cd src && python fix_missing_coords.py [--dry-run] [--active-only]
"""
import sys, json, time, argparse, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from geocoder import Geocoder

OFFERS_FILE = Path('../data/offers.json')
CACHE_FILE  = Path('../data/geocoding_cache.json')

# Sygnały że adres to efekt złego parsowania — nie ma sensu geocodować
GARBAGE_SIGNALS = [
    # Rzeczowniki opisowe (nie nazwy ulic)
    'kaucja', 'internet', 'zadzwoń', 'polecam', 'wynajm', 'najem',
    'możliwy', 'samodzielne', 'położone', 'to ok', 'metraż', 'siłownia',
    'cena ', 'dwupokojowe', 'mieszkni', 'apartament ', 'pokoj ',
    # Śmieci sklejone z HTML
    'zdjęcia', 'oferuję', 'telefon', 'do wynajęcia', 'w skład',
    'aneks kuchenny', 'odległości', 'spełni',
    # Imiona własne które nie są ulicami
    'sylwia', 'mateusz', 'magda',
    # Inne oczywiste niie-ulice
    'this ', 'plac zabaw', 'wyżynn', 'mieszknie',
]

# Ulice które wyglądają poprawnie — krótkie, bez śmieciowych sygnałów
LOOKS_LIKE_STREET = re.compile(
    r'^[A-ZŚĆŁĄĘÓŻŹŃ][a-ząćęłńóśźż]+(?: [A-ZŚĆŁĄĘÓŻŹŃ]?[a-ząćęłńóśźż]+)* \d+[a-zA-Z]?$'
    r'|'
    r'^[A-ZŚĆŁĄĘÓŻŹŃ][a-ząćęłńóśźż]{3,}$',  # sama ulica bez numeru
    re.UNICODE
)

def is_garbage(addr: str) -> bool:
    if len(addr) > 30:
        return True
    low = addr.lower()
    return any(s in low for s in GARBAGE_SIGNALS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--active-only', action='store_true', help='Tylko aktywne oferty')
    args = ap.parse_args()

    with open(OFFERS_FILE) as f:
        db = json.load(f)

    geocoder = Geocoder(cache_file=str(CACHE_FILE))

    candidates = [
        o for o in db['offers']
        if not o.get('address', {}).get('coords')
        and o.get('address', {}).get('full')
        and (not args.active_only or o.get('active'))
        and not is_garbage(o['address']['full'])
    ]

    print(f"Kandydatów: {len(candidates)} "
          f"({'tylko aktywne' if args.active_only else 'wszystkie'})")

    fixed = skipped = 0
    for o in candidates:
        addr_full = o['address']['full']
        address_data = {
            'street':     o['address'].get('street', addr_full),
            'number':     o['address'].get('number'),
            'full':       addr_full,
            'has_number': o['address'].get('has_number', False),
            'alternatives': [],
        }
        result = geocoder.geocode_with_alternatives(address_data)
        if result:
            coords, _ = result
            o['address']['coords'] = coords
            fixed += 1
            print(f"  ✅ {addr_full} → {coords['lat']:.4f}, {coords['lon']:.4f}")
        else:
            skipped += 1

        time.sleep(1.1)

    print(f"\nWynik: fixed={fixed}, no_result={skipped}")

    if fixed > 0 and not args.dry_run:
        with open(OFFERS_FILE, 'w') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        print(f"Zapisano {OFFERS_FILE}")
    elif args.dry_run:
        print("(dry-run — nie zapisano)")


if __name__ == '__main__':
    main()
