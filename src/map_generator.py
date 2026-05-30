#!/usr/bin/env python3
"""
Generator map_data.json dla SONAR MIESZKANIOWY
Przekształca data.json → map_data.json z formatem wymaganym przez frontend
"""

import json
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Import taggera ofert (B1)
from offer_tagger import build_tags, title_from_url, TAGS as OFFER_TAGS


def resolve_tags(offer):
    """Zwraca tagi oferty w kształcie dla frontendu.

    Preferuje tagi zapisane w offers.json (liczone raz w main.py). Dla starych
    ofert bez pola 'tags' liczy je w locie (fallback wsteczny).
    """
    tags = offer.get('tags')
    if isinstance(tags, dict) and 'primary' in tags:
        return {
            'primary': tags['primary'],
            'secondary': tags.get('secondary', []),
            'all': tags.get('all') or tags.get('all_tags') or [tags['primary']],
            'confidence': tags.get('confidence', 0),
        }
    return build_tags(title_from_url(offer.get('url', '')), offer.get('description', ''))

# Definicja zakresów cenowych - 12 przedziałów z gradientem
# DOSTOSOWANE DLA MIESZKAŃ (rynek wynajmu Lublin: kawalerki ~1500-2200, 2-pok ~2000-3500, 3-pok 2800-4500+)
# UWAGA: Po pierwszym skanie warto przeskalować na podstawie faktycznego rozkładu cen.
PRICE_RANGES = {
    'range_0_1500': {
        'label': '0-1500 zł',
        'min': 0,
        'max': 1500,
        'color': '#00c853'  # Zielony
    },
    'range_1501_1750': {
        'label': '1501-1750 zł',
        'min': 1501,
        'max': 1750,
        'color': '#64dd17'  # Zielony jasny
    },
    'range_1751_2000': {
        'label': '1751-2000 zł',
        'min': 1751,
        'max': 2000,
        'color': '#aeea00'  # Limonkowy
    },
    'range_2001_2250': {
        'label': '2001-2250 zł',
        'min': 2001,
        'max': 2250,
        'color': '#ffd600'  # Żółty
    },
    'range_2251_2500': {
        'label': '2251-2500 zł',
        'min': 2251,
        'max': 2500,
        'color': '#ffab00'  # Żółto-pomarańczowy
    },
    'range_2501_2750': {
        'label': '2501-2750 zł',
        'min': 2501,
        'max': 2750,
        'color': '#ff6f00'  # Pomarańczowy
    },
    'range_2751_3000': {
        'label': '2751-3000 zł',
        'min': 2751,
        'max': 3000,
        'color': '#ff3d00'  # Pomarańczowo-czerwony
    },
    'range_3001_3250': {
        'label': '3001-3250 zł',
        'min': 3001,
        'max': 3250,
        'color': '#d50000'  # Czerwony
    },
    'range_3251_3500': {
        'label': '3251-3500 zł',
        'min': 3251,
        'max': 3500,
        'color': '#c51162'  # Czerwono-różowy
    },
    'range_3501_4000': {
        'label': '3501-4000 zł',
        'min': 3501,
        'max': 4000,
        'color': '#aa00ff'  # Różowo-fioletowy
    },
    'range_4001_5000': {
        'label': '4001-5000 zł',
        'min': 4001,
        'max': 5000,
        'color': '#7c4dff'  # Fioletowy jasny
    },
    'range_5001_plus': {
        'label': '5001-7000 zł',
        'min': 5001,
        'max': 7000,
        'color': '#6200ea'  # Fioletowy ciemny
    },
    'range_7001_plus': {
        'label': '7001+ zł',
        'min': 7001,
        'max': 999999,
        'color': '#311b92'  # Najciemniejszy fiolet (premium)
    }
}

# Długość podglądu opisu w data.json. Pełne opisy (gdy dłuższe) trafiają do
# osobnego docs/descriptions.json i są doczytywane przez frontend dopiero po
# kliknięciu "Pokaż całość" — patrz punkt 6 audytu (data.json był w 59% opisami).
DESC_PREVIEW_LEN = 200


def split_description(full_text):
    """Zwraca (podgląd, czy_obcięto) dla opisu oferty.

    Jeśli opis mieści się w DESC_PREVIEW_LEN, podglądem jest cały tekst i
    czy_obcięto=False (frontend nie pokazuje "Pokaż całość", nie ma czego doczytać).
    """
    full_text = full_text or ''
    if len(full_text) <= DESC_PREVIEW_LEN:
        return full_text, False
    return full_text[:DESC_PREVIEW_LEN].rstrip() + '…', True


def get_price_range(price):
    """Przypisz cenę do zakresu"""
    for key, range_info in PRICE_RANGES.items():
        if range_info['min'] <= price <= range_info['max']:
            return key
    return 'range_7001_plus'  # Fallback (musi pasować do ostatniego klucza w PRICE_RANGES)


def format_datetime(iso_string):
    """
    Konwertuj ISO datetime → format frontend 'DD.MM.RRRR HH:MM'
    Input: '2026-03-01T15:51:38.344630+01:00'
    Output: '01.03.2026 15:51'
    """
    if not iso_string:
        return ''
    try:
        # Parse ISO format (obsługa timezone)
        if '+' in iso_string:
            dt_str = iso_string.split('+')[0]  # Usuń timezone
        elif 'Z' in iso_string:
            dt_str = iso_string.replace('Z', '')
        else:
            dt_str = iso_string
        
        # Parse datetime
        if '.' in dt_str:
            dt = datetime.fromisoformat(dt_str)
        else:
            dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S')
        
        # Format do DD.MM.YYYY HH:MM
        return dt.strftime('%d.%m.%Y %H:%M')
    except (ValueError, AttributeError) as e:
        print(f"⚠️  Błąd parsowania daty '{iso_string}': {e}")
        return iso_string


def format_scan_datetime(iso_string):
    """
    Format dla scan info (z sekundami)
    Output: 'DD.MM.YYYY HH:MM:SS'
    """
    if not iso_string:
        return ''
    try:
        if '+' in iso_string:
            dt_str = iso_string.split('+')[0]
        elif 'Z' in iso_string:
            dt_str = iso_string.replace('Z', '')
        else:
            dt_str = iso_string
        
        if '.' in dt_str:
            dt = datetime.fromisoformat(dt_str)
        else:
            dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S')
        
        return dt.strftime('%d.%m.%Y %H:%M:%S')
    except (ValueError, AttributeError) as e:
        print(f"⚠️  Błąd parsowania daty skanu '{iso_string}': {e}")
        return iso_string


def generate_map_data(input_file, output_file):
    """Główna funkcja generująca map_data.json"""
    
    print("🔄 Generowanie map_data.json...")
    
    # 1. Wczytaj data.json
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    offers = data.get('offers', [])
    print(f"📥 Wczytano {len(offers)} ofert z data.json")
    
    # Pobierz aktualną datę w strefie czasowej polskiej
    from datetime import datetime
    import pytz
    tz = pytz.timezone('Europe/Warsaw')
    now = datetime.now(tz)
    today_date = now.date()  # Tylko data (bez godziny)
    
    # 2. Grupuj oferty według adresów
    markers_dict = defaultdict(list)
    unlocalised_offers = []  # Oferty bez precyzyjnej lokacji GPS
    full_descriptions = {}   # {offer_id: pełny_opis} — tylko dla obciętych (lazy-load)
    
    for offer in offers:
        address_full = offer.get('address', {}).get('full', 'Nieznany adres')
        coords = offer.get('address', {}).get('coords', {})
        
        # Sprawdź czy są współrzędne
        if not coords.get('lat') or not coords.get('lon'):
            print(f"📍 Brak współrzędnych dla oferty {offer.get('id')} — trafi do warstwy 'bez lokacji'")
            # Zbierz do osobnej warstwy zamiast pomijać
            price_data = offer.get('price', {})
            current_price = price_data.get('current', 0)
            first_seen_str = offer.get('first_seen', '')
            is_new = False
            if first_seen_str:
                try:
                    first_seen_dt = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
                    if first_seen_dt.tzinfo is None:
                        first_seen_dt = tz.localize(first_seen_dt)
                    else:
                        first_seen_dt = first_seen_dt.astimezone(tz)
                    is_new = (first_seen_dt.date() == today_date)
                except (ValueError, AttributeError):
                    pass
            full_desc = offer.get('description', '')
            tags = resolve_tags(offer)
            desc_preview, desc_truncated = split_description(full_desc)
            if desc_truncated:
                full_descriptions[offer.get('id')] = full_desc
            unlocalised_offers.append({
                'id': offer.get('id'),
                'url': offer.get('url'),
                'address': address_full,
                'price': current_price,
                'price_range': get_price_range(current_price),
                'media_info': price_data.get('media_info', 'brak informacji'),
                'first_seen': format_datetime(offer.get('first_seen', '')),
                'last_seen': format_datetime(offer.get('last_seen', '')),
                'days_active': offer.get('days_active', 0),
                'active': offer.get('active', True),
                'is_new': is_new,
                'description': desc_preview,
                'desc_truncated': desc_truncated,
                'tags': tags
            })
            continue
        
        # Klucz grupowania: pełen adres
        key = address_full
        
        # Przygotuj ofertę do frontendu
        price_data = offer.get('price', {})
        
        # Oblicz czy oferta jest nowa (first_seen dzisiaj)
        first_seen_str = offer.get('first_seen', '')
        is_new = False
        if first_seen_str:
            try:
                # Parse ISO datetime
                first_seen_dt = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
                # Konwertuj na polską strefę czasową
                if first_seen_dt.tzinfo is None:
                    first_seen_dt = tz.localize(first_seen_dt)
                else:
                    first_seen_dt = first_seen_dt.astimezone(tz)
                
                first_seen_date = first_seen_dt.date()
                is_new = (first_seen_date == today_date)  # Porównaj tylko daty
            except (ValueError, AttributeError) as e:
                print(f"⚠️  Błąd parsowania first_seen dla {offer.get('id')}: {e}")
                is_new = False
        
        # Pobierz cenę i oblicz price_range dla tej konkretnej oferty
        current_price = price_data.get('current', 0)
        offer_price_range = get_price_range(current_price)
        
        # B1: Tagi oferty (kawalerka/pokój/mieszkanie) — z offers.json lub fallback
        description_text = offer.get('description', '')
        tags = resolve_tags(offer)

        desc_preview, desc_truncated = split_description(description_text)
        if desc_truncated:
            full_descriptions[offer.get('id')] = description_text

        offer_data = {
            'id': offer.get('id'),
            'url': offer.get('url'),
            'price': current_price,
            'price_range': offer_price_range,  # ✅ Zakres cenowy dla tej konkretnej oferty
            'price_history': price_data.get('history', []),  # Historia cen
            'previous_price': price_data.get('previous_price'),  # Poprzednia cena (jeśli się zmieniła)
            'price_trend': price_data.get('price_trend'),  # 'up' lub 'down'
            'price_changed_at': format_datetime(price_data.get('price_changed_at', '')) if price_data.get('price_changed_at') else None,
            'media_info': price_data.get('media_info', 'brak informacji'),  # Info o mediach
            'first_seen': format_datetime(offer.get('first_seen', '')),
            'last_seen': format_datetime(offer.get('last_seen', '')),
            'days_active': offer.get('days_active', 0),  # Dni aktywności
            'active': offer.get('active', True),
            'is_new': is_new,  # ✅ Obliczone na podstawie daty
            'has_number': offer.get('address', {}).get('has_number', True),  # ✅ Czy znany numer domu
            'description': desc_preview,        # Podgląd; pełny opis w descriptions.json
            'desc_truncated': desc_truncated,   # True → frontend doczytuje pełny opis na żądanie
            'reactivated': offer.get('reactivated_at') is not None,  # Czy była reaktywowana
            'reactivated_at': format_datetime(offer.get('reactivated_at', '')) if offer.get('reactivated_at') else None,
            # B1: Tagi oferty (liczone raz w main.py, tu tylko odczyt)
            'tags': tags
        }
        
        markers_dict[key].append({
            'coords': coords,
            'address': address_full,
            'offer': offer_data
        })
    
    print(f"📍 Pogrupowano na {len(markers_dict)} unikalnych adresów")
    print(f"🔍 Oferty bez lokacji GPS: {len(unlocalised_offers)}")
    
    # 3. Stwórz listę markerów
    markers = []
    
    for address, items in markers_dict.items():
        # Weź współrzędne z pierwszej oferty
        coords = items[0]['coords']
        
        # Zbierz wszystkie oferty dla tego adresu
        offers_list = [item['offer'] for item in items]
        
        # Sprawdź czy są aktywne oferty
        has_active = any(o['active'] for o in offers_list)
        
        markers.append({
            'coords': coords,
            'address': address,
            'offers': offers_list,
            'has_active': has_active
        })
    
    # 4. Oblicz statystyki (tylko dla aktywnych ofert)
    active_offers_all = [o for marker in markers for o in marker['offers'] if o['active']]
    
    if active_offers_all:
        prices = [o['price'] for o in active_offers_all]
        stats = {
            'active_count': len(active_offers_all),
            'avg_price': round(sum(prices) / len(prices)),
            'min_price': min(prices),
            'max_price': max(prices),
            'unlocalised_count': len([o for o in unlocalised_offers if o['active']])
        }
    else:
        stats = {
            'active_count': 0,
            'avg_price': 0,
            'min_price': 0,
            'max_price': 0,
            'unlocalised_count': len([o for o in unlocalised_offers if o['active']])
        }
    
    print(f"📊 Statystyki: {stats['active_count']} aktywnych, średnia {stats['avg_price']} zł")
    
    # 5. Formatuj informacje o skanach
    scan_info = {
        'last': format_scan_datetime(data.get('last_scan', '')),
        'next': format_scan_datetime(data.get('next_scan', ''))
    }
    
    # 6. Stwórz finalny plik map_data.json
    map_data = {
        'markers': markers,
        'unlocalised_offers': unlocalised_offers,  # Osobna warstwa: oferty bez GPS
        'stats': stats,
        'scan_info': scan_info,
        'price_ranges': PRICE_RANGES,
        'offer_tags': OFFER_TAGS  # B1: Definicje tagów dla frontendu
    }
    
    # 7. Zapisz do pliku
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(map_data, f, ensure_ascii=False, indent=2)

    # 8. Zapisz pełne opisy do osobnego pliku (lazy-load przez frontend).
    #    Tylko opisy obcięte w podglądzie — reszta i tak jest w całości w data.json.
    descriptions_file = Path(output_file).parent / 'descriptions.json'
    with open(descriptions_file, 'w', encoding='utf-8') as f:
        json.dump(full_descriptions, f, ensure_ascii=False)

    data_mb = Path(output_file).stat().st_size / 1e6
    desc_mb = descriptions_file.stat().st_size / 1e6
    print(f"✅ Zapisano map_data.json ({len(markers)} markerów, {stats['active_count']} aktywnych ofert, {len(unlocalised_offers)} bez lokacji)")
    print(f"   data.json: {data_mb:.2f} MB | descriptions.json: {desc_mb:.2f} MB ({len(full_descriptions)} pełnych opisów)")
    print(f"   Ostatni scan: {scan_info['last']}")
    print(f"   Następny scan: {scan_info['next']}")


if __name__ == '__main__':
    # Ścieżki plików
    base_dir = Path(__file__).parent.parent
    input_file = base_dir / 'data' / 'offers.json'
    output_file = base_dir / 'docs' / 'data.json'
    
    # Sprawdź czy plik wejściowy istnieje
    if not input_file.exists():
        print(f"❌ Plik {input_file} nie istnieje!")
        exit(1)
    
    # Generuj
    generate_map_data(input_file, output_file)
    
    # Wygeneruj także dane monitoringu
    print("\n📊 Generowanie danych monitoringu...")
    from monitoring_generator import generate_monitoring_data
    generate_monitoring_data()

    # Wygeneruj stronę debug z pominiętymi ofertami
    print("\n🐛 Generowanie strony debug pominiętych ofert...")
    try:
        from skipped_debug_generator import generate_skipped_debug_page
        generate_skipped_debug_page()
    except Exception as e:
        print(f"⚠️  skipped_debug_generator nie powiódł się: {e}")
