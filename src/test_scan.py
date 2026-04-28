#!/usr/bin/env python3
"""
Test scanu - tylko pierwsza strona (szybki test)
"""

import sys
sys.path.insert(0, '.')

from scraper import OLXScraper
from address_parser import AddressParser
from price_parser import PriceParser
from geocoder import Geocoder
import json

print("\n" + "="*60)
print("🧪 TEST SCANU - Pierwsza strona")
print("="*60 + "\n")

# Inicjalizacja
scraper = OLXScraper(delay_range=(1, 2))
address_parser = AddressParser()
price_parser = PriceParser()
geocoder = Geocoder(cache_file="../data/geocoding_cache.json")

# Pobierz tylko pierwszą stronę
print("📡 Pobieram pierwszą stronę OLX...")
soup = scraper._fetch_page(scraper.BASE_URL)
if not soup:
    print("❌ Błąd pobierania strony")
    sys.exit(1)

offers = scraper._extract_offers_from_page(soup)
print(f"✅ Znaleziono {len(offers)} ofert na stronie\n")

# Ogranicz do 5 ofert (test)
offers = offers[:5]

print(f"🔧 Testuję {len(offers)} ofert:\n")

results = []

for i, offer in enumerate(offers, 1):
    print(f"[{i}/{len(offers)}] {offer['title'][:60]}...")
    
    # Pobierz szczegóły
    print(f"   📥 Pobieram szczegóły...")
    details = scraper.fetch_offer_details(offer['url'])
    
    if details:
        offer['description'] = details['description']
        if details.get('official_price'):
            offer['official_price'] = details['official_price']
            offer['official_price_raw'] = details['official_price_raw']
    
    # Parsuj adres
    full_text = offer['title'] + " " + offer.get('description', '')
    address_data = address_parser.extract_address(full_text)
    
    if not address_data:
        print(f"   ⚠️ Brak adresu - pomijam")
        continue
    
    # Cena - NOWA LOGIKA
    if offer.get('official_price'):
        price = offer['official_price']
        source = "oficjalna (OLX)"
        print(f"   💰 Cena: {price} zł (źródło: {source})")
    else:
        price_data = price_parser.extract_price(full_text)
        if price_data:
            price = price_data['price']
            source = "parser treści"
            print(f"   💰 Cena: {price} zł (źródło: {source})")
        else:
            print(f"   ⚠️ Brak ceny - pomijam")
            continue
    
    # Geocoding
    coords = geocoder.geocode_address(address_data['full'])
    if not coords:
        print(f"   ⚠️ Nie można geocodować - pomijam")
        continue
    
    print(f"   ✅ {address_data['full']} - {price} zł - {coords}")
    
    results.append({
        'title': offer['title'],
        'url': offer['url'],
        'address': address_data['full'],
        'price': price,
        'price_source': source,
        'coords': coords
    })
    print()

print("\n" + "="*60)
print("📊 WYNIKI TESTU")
print("="*60)
print(f"Przetworzone pomyślnie: {len(results)}/{len(offers)}\n")

if results:
    print("🎯 Przykładowe wyniki:\n")
    for r in results[:3]:
        print(f"📍 {r['address']}")
        print(f"   💰 {r['price']} zł (źródło: {r['price_source']})")
        print(f"   🌍 {r['coords']}")
        print(f"   🔗 {r['url'][:70]}...")
        print()

# Zapisz wyniki do pliku testowego
with open('/tmp/test_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"💾 Wyniki zapisane: /tmp/test_results.json")
print("="*60 + "\n")
