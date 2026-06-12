"""
SONAR MIESZKANIOWY - Główny agent
Koordynuje: scraping → parsowanie → geokodowanie → wykrywanie duplikatów → zapis
WERSJA 2.0: Równoległy scraping + monitoring
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
import pytz
from typing import List, Dict
import time
import random

# Import lokalnych modułów
from scraper import OLXScraper
from address_parser import AddressParser
from price_parser import PriceParser
from geocoder import Geocoder
from duplicate_detector import DuplicateDetector
from scan_logger import ScanLogger

# Stabilny identyfikator oferty (CID3-IDxxxx). Współdzielony z scraper.py.
from cid import extract_cid
from offer_tagger import build_tags
from atomic_json import atomic_write_json
import paths


class SonarMieszkaniowy:
    # Ochrona przed masową dezaktywacją: scrape musi zwrócić co najmniej
    # 30% wcześniejszej liczby aktywnych ofert, inaczej nie dezaktywujemy.
    MIN_DEACTIVATION_RATIO = 0.3

    def __init__(self, data_file: str = paths.OFFERS_JSON, removed_file: str = paths.REMOVED_JSON):
        self.data_file = Path(data_file)
        self.removed_file = Path(removed_file)
        self.address_parser = AddressParser()
        self.price_parser = PriceParser()
        self.geocoder = Geocoder(cache_file=paths.GEOCODING_CACHE_JSON)
        self.duplicate_detector = DuplicateDetector(similarity_threshold=0.95)
        self.scan_logger = ScanLogger(log_file=paths.SCAN_HISTORY_JSON)
        
        # Strefa czasowa polska
        self.tz = pytz.timezone('Europe/Warsaw')
        
        # Wczytaj istniejącą bazę
        self.database = self._load_database()
        
        # Wczytaj listę usuniętych ogłoszeń
        self.removed_listings = self._load_removed_listings()
        
        # Inicjalizuj scraper Z istniejącymi ofertami (inteligentne pomijanie)
        existing_offers = self._build_existing_offers_index()
        # OPTYMALIZACJA 2026-05: zachowaj indeks jako pole klasy żeby
        # _process_offer mógł użyć coords z istniejących ofert (omija geokoder)
        self.existing_offers_index = existing_offers
        self.scraper = OLXScraper(delay_range=(0.2, 0.5), max_workers=10, existing_offers=existing_offers)
    
    def _build_existing_offers_index(self) -> Dict:
        """
        Buduje indeks istniejących ofert dla inteligentnego pomijania.
        Zawiera WSZYSTKIE oferty (aktywne + nieaktywne z ostatnich 30 dni)
        aby umożliwić reaktywację ofert które tymczasowo zniknęły.
        Returns: {offer_id: {'price': X, 'description': '...', 'was_active': bool}}
        """
        index = {}
        active_count = 0
        inactive_count = 0
        cutoff_date = datetime.now(self.tz) - timedelta(days=30)
        
        for offer in self.database.get('offers', []):
            is_active = offer.get('active', False)
            
            # Nieaktywne oferty: tylko te z ostatnich 30 dni
            if not is_active:
                try:
                    last_seen = datetime.fromisoformat(offer['last_seen'])
                    if last_seen < cutoff_date:
                        continue  # Pomiń stare nieaktywne oferty
                except (ValueError, KeyError):
                    continue
            
            # FIX 2026-05: coords są w address.coords, nie w 'coordinates' top-level.
            # Wcześniej zawsze zwracało {} → każde geocode_address robione od nowa.
            existing_addr = offer.get('address', {})
            existing_coords = existing_addr.get('coords') if isinstance(existing_addr, dict) else None
            
            # FIX: kluczem jest CID3-IDxxxx, nie pełny slug (sprzedawca może edytować tytuł)
            index[extract_cid(offer['id'])] = {
                'price': offer.get('price', {}).get('current'),
                'description': offer.get('description', ''),
                'previous_price': offer.get('price', {}).get('previous_price'),
                'was_active': is_active,
                'address': existing_addr,
                'address_full': existing_addr.get('full', '') if isinstance(existing_addr, dict) else '',
                'coordinates': existing_coords,
            }
            
            if is_active:
                active_count += 1
            else:
                inactive_count += 1
        
        print(f"📚 Zaindeksowano {len(index)} ofert do inteligentnego pomijania "
              f"({active_count} aktywnych, {inactive_count} nieaktywnych z ostatnich 30 dni)")
        return index
    
    def _load_database(self) -> Dict:
        """Wczytuje bazę danych z JSON.

        FIX 2026-06-12: uszkodzony plik = PRZERWIJ zamiast cicho startować od
        pustej bazy. Stare zachowanie groziło utratą całej historii (pusta baza
        zostałaby zapisana i scommitowana na main przez workflow). Brak pliku
        (pierwsze uruchomienie) nadal tworzy pustą bazę.
        """
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Uszkodzony plik bazy danych {self.data_file}: {e}. "
                    f"Przerywam skan żeby nie nadpisać historii pustą bazą — "
                    f"przywróć plik z gita (git checkout -- data/offers.json)."
                ) from e
        else:
            return self._create_empty_database()
    
    def _load_removed_listings(self) -> set:
        """Wczytuje listę usuniętych ogłoszeń."""
        if self.removed_file.exists():
            try:
                with open(self.removed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('removed_ids', []))
            except json.JSONDecodeError:
                print("⚠️ Uszkodzony plik usuniętych ogłoszeń, tworzę nowy")
                return set()
        else:
            return set()
    
    def _save_removed_listings(self):
        """Zapisuje listę usuniętych ogłoszeń (atomowo)."""
        atomic_write_json(self.removed_file, {
            'removed_ids': list(self.removed_listings),
            'last_updated': datetime.now(self.tz).isoformat()
        })
    
    def _create_empty_database(self) -> Dict:
        """Tworzy pustą strukturę bazy danych."""
        return {
            "last_scan": None,
            "next_scan": None,
            "offers": []
        }
    
    def _save_database(self):
        """Zapisuje bazę danych do JSON (atomowo — tmp + os.replace)."""
        atomic_write_json(self.data_file, self.database)
        print(f"💾 Baza zapisana: {self.data_file}")
    
    def _calculate_next_scan_time(self) -> str:
        """Oblicza czas następnego scanu (9:00, 15:00 lub 21:00)."""
        now = datetime.now(self.tz)
        scan_hours = [9, 15, 21]
        
        for hour in scan_hours:
            next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if next_time > now:
                return next_time.isoformat()
        
        # Jeśli po 21:00, to następny scan o 9:00 następnego dnia
        tomorrow = now + timedelta(days=1)
        next_time = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
        return next_time.isoformat()
    
    def _process_offer(self, raw_offer: Dict) -> Dict:
        """
        Przetwarza surowe ogłoszenie: parsuje adres, cenę, geokoduje.
        
        Returns:
            Dict z przetworzonymi danymi lub None jeśli oferta nieprawidłowa
        """
        # 1. Użyj pełnego opisu (scraper już go pobrał)
        full_text = raw_offer['title'] + " " + raw_offer.get('description', '')
        
        # FILTR: Wykluczamy ogłoszenia gdzie CAŁY DOM jest przedmiotem wynajmu.
        # NIE wykluczamy mieszkań/lokali w domach jednorodzinnych — "w domu jednorodzinnym"
        # to opis budynku, nie typ oferty.
        excluded_phrases = [
            'willa na wynajem',
            'dom na wynajem',
            'wynajmę dom',
            'wynajem domu',
            'dom do wynajęcia',
        ]
        
        full_text_lower = full_text.lower()
        for phrase in excluded_phrases:
            if phrase in full_text_lower:
                print(f"      ⚠️ Wykluczono (wynajem domu): {phrase}")
                return None
        
        # 2. Parsuj adres z pełnego tekstu (tytuł + opis)
        address_data = self.address_parser.extract_address(full_text)
        
        # Jeśli nie znaleziono adresu w tytule, spróbuj w samym opisie
        if not address_data and raw_offer.get('description'):
            print(f"      🔍 Brak adresu w tytule, szukam w opisie...")
            address_data = self.address_parser.extract_address(raw_offer['description'])
        
        # REAKTYWACJA: Jeśli brak adresu ale mamy cache (oferta była nieaktywna)
        use_cached_coords = False
        cached_coords = None
        if not address_data and raw_offer.get('cached_address'):
            cached_addr = raw_offer['cached_address']
            # cached_address może być dict (z indeksu) lub stringiem - obsłuż oba przypadki
            if isinstance(cached_addr, dict):
                addr_full = cached_addr.get('full', '')
                # Jeśli mamy coords bezpośrednio w cached_address, użyj ich
                if not raw_offer.get('cached_coordinates') and cached_addr.get('coords'):
                    cached_coords = cached_addr['coords']
                    use_cached_coords = True
            else:
                addr_full = str(cached_addr)
            print(f"      🔄 Brak adresu w tekście, używam z cache: {addr_full}")
            address_data = {'full': addr_full}
            # Jeśli mamy też współrzędne w cache, użyjemy ich zamiast geokodowania
            if raw_offer.get('cached_coordinates'):
                cached_coords = raw_offer['cached_coordinates']
                use_cached_coords = True
        
        if not address_data:
            return None  # Brak adresu → ignoruj
        
        # 3. Parsuj cenę - NOWA LOGIKA TRÓJPOZIOMOWA (2C)
        # PRIORYTET 1: JSON-LD z OLX (najbardziej niezawodne, oficjalne dane)
        # PRIORYTET 2: Cache (dane z poprzedniego skanu - równie niezawodne jak JSON-LD)
        # PRIORYTET 3: Parser ceny z treści (wyciąga czystą cenę mieszkania bez mediów)
        # PRIORYTET 4: Fallback HTML (jeśli JSON-LD i parser zawiodły)
        
        price = None
        media_info = "brak informacji"
        price_source = None
        
        # Sprawdź czy mamy JSON-LD z niezawodną ceną
        if raw_offer.get('official_price') and raw_offer.get('price_source') == 'json-ld':
            # PRIORYTET 1: JSON-LD - najbardziej niezawodne źródło
            price = raw_offer['official_price']
            price_source = "JSON-LD (OLX)"
            
            # Wykryj info o mediach używając parsera (BEZ parsowania ceny!)
            media_info = self.price_parser.detect_media_info_only(full_text)
            
            print(f"      💰 Użyto ceny JSON-LD: {price} zł ({media_info})")
        
        # PRIORYTET 2: Cache - dane z poprzedniego skanu (równie niezawodne)
        elif raw_offer.get('official_price') and raw_offer.get('price_source') == 'cache':
            # Cache - oferta pominięta w scraping bo cena się nie zmieniła
            price = raw_offer['official_price']
            price_source = "cache"
            
            # Wykryj info o mediach używając parsera (BEZ parsowania ceny!)
            media_info = self.price_parser.detect_media_info_only(full_text)
            
            print(f"      💰 Użyto ceny z cache (pominięto pobieranie): {price} zł ({media_info})")
        
        # PRIORYTET 3: Parser tekstowy - wyciąga czystą cenę mieszkania
        if not price:
            price_data = self.price_parser.extract_price(full_text)
            if price_data:
                price = price_data['price']
                media_info = price_data['media_info']
                price_source = "Parser tekstowy"
                print(f"      💰 Użyto parsera ceny z opisu: {price} zł ({media_info})")
        
        # PRIORYTET 4: Fallback - cena z HTML (jeśli JSON-LD i parser zawiodły)
        if not price and raw_offer.get('official_price'):
            price = raw_offer['official_price']
            media_info = self.price_parser.detect_media_info_only(full_text)
            price_source = "HTML fallback"
            print(f"      💰 Użyto ceny HTML (fallback): {price} zł ({media_info})")
        
        if not price:
            return None  # Brak ceny → ignoruj
        
        # 4. Geokoduj adres (lub użyj cache dla reaktywacji)
        if use_cached_coords and cached_coords:
            coords = cached_coords
            # Reaktywacja: address_data['full'] to ten sam adres jaki oferta miała w bazie,
            # więc nie próbujemy alternatyw — final_* = main
            final_street = address_data.get('street', '')
            final_number = address_data.get('number')
            final_full = address_data['full']
            print(f"      📍 Użyto współrzędnych z cache: {coords['lat']:.4f}, {coords['lon']:.4f}")
        else:
            # OPTYMALIZACJA 2026-05: jeśli oferta już istnieje w bazie i ma ten sam adres,
            # użyj jej coords zamiast wywoływać geokoder od nowa. To eliminuje ~70% wywołań
            # Nominatim (skan z 70 min → ~25 min).
            # FIX: stabilny identyfikator z CID3-IDxxxx (slug bywa edytowany)
            offer_id_temp = extract_cid(raw_offer['url'])
            reused_coords = None
            existing = self.existing_offers_index.get(offer_id_temp) if hasattr(self, 'existing_offers_index') else None
            if existing and existing.get('coordinates') and existing.get('address_full') == address_data['full']:
                reused_coords = existing['coordinates']
            
            if reused_coords:
                coords = reused_coords
                # Skipowy log - bez print, żeby nie zaśmiecać outputu (470x ten sam log)
                # final_* używamy z address_data bo cache hit oznacza ten sam adres co main
                final_street = address_data.get('street', '')
                final_number = address_data.get('number')
                final_full = address_data['full']
            else:
                # MIESZKANIOWY 2026-05-15: geocode_with_alternatives próbuje główny + alternatywy
                # (parser może zwrócić "Mieszkanie 3" jako main i "Narutowicza 38" w alternatives;
                # jeśli main nie geokoduje się do Lublina, próbujemy alternatyw)
                result = self.geocoder.geocode_with_alternatives(address_data)
                if result:
                    coords, used_address = result
                    final_street = used_address['street']
                    final_number = used_address['number']
                    final_full = used_address['full']
                else:
                    coords = None
                    final_street = address_data.get('street', '')
                    final_number = address_data.get('number')
                    final_full = address_data['full']
                    print(f"⚠️ Nie można geokodować: {final_full} (próbowano też {len(address_data.get('alternatives', []))} alt.) — trafi do warstwy bez lokacji")
        
        # 5. Stwórz ID z URL (unikalne)
        offer_id = raw_offer['url'].split('/')[-1].split('.')[0]
        
        # Buduj address dict (bez coords lub z coords=None jeśli nie znaleziono)
        # MIESZKANIOWY: zapisujemy KTÓRY adres faktycznie się zgeokodował (może być z alternatives)
        address_dict = {
            'full': final_full,
            'street': final_street,
            'number': final_number,
            'has_number': address_data.get('has_number', True),
        }
        if coords:
            address_dict['coords'] = coords
        # Brak coords → offer_id zapisze się do bazy BEZ coords → map_generator włączy do unlocalised
        
        return {
            'id': offer_id,
            'url': raw_offer['url'],
            'address': address_dict,
            'price': {
                'current': price,
                'history': [price],
                'media_info': media_info,
                'source': price_source  # Dodane: JSON-LD / Parser / HTML fallback
            },
            'description': full_text,
            # Tagi liczone RAZ tutaj (kawalerka/pokój/mieszkanie) i zapisywane w
            # offers.json — map_generator tylko je odczytuje zamiast liczyć regexy
            # na każdym opisie przy każdej generacji.
            'tags': build_tags(raw_offer.get('title', ''), full_text),
            'first_seen': datetime.now(self.tz).isoformat(),
            'last_seen': datetime.now(self.tz).isoformat(),
            'active': True,
            'days_active': 0
        }
    
    # FIX 2026-06-12: usunięto _find_existing_offer (liniowy skan bazy per oferta) —
    # run_scan używa teraz indeksu cid_index {CID3 → oferta} budowanego raz.

    def _update_existing_offer(self, existing: Dict, new_data: Dict):
        """Aktualizuje istniejące ogłoszenie z inteligentnym zarządzaniem ceną."""
        now = datetime.now(self.tz).isoformat()
        
        # Aktualizuj last_seen
        existing['last_seen'] = now
        
        # FIX 2026-05-24: jeśli slug w URL się zmienił (sprzedawca edytował tytuł),
        # zaktualizuj id i url na świeżą wersję, ale tylko gdy CID3 się zgadza.
        if new_data.get('id') and extract_cid(existing.get('id','')) == extract_cid(new_data['id']):
            if existing.get('id') != new_data['id']:
                old_slug = existing.get('id','')
                existing['id'] = new_data['id']
                if new_data.get('url'):
                    existing['url'] = new_data['url']
                print(f"      🔄 Slug zaktualizowany: {old_slug[:50]}... → {new_data['id'][:50]}...")
        
        # INTELIGENTNA AKTUALIZACJA CENY - priorytetyzuj źródła
        old_price = existing['price']['current']
        new_price = new_data['price']['current']
        old_source = existing['price'].get('source', 'unknown')
        new_source = new_data['price'].get('source', 'unknown')
        
        # Hierarchia źródeł (od najlepszego do najgorszego)
        source_priority = {
            'JSON-LD (OLX)': 3,
            'cache': 3,  # Cache ma ten sam priorytet co JSON-LD (bo pochodzi z niego)
            'HTML fallback': 2,
            'Parser tekstowy': 1,
            'unknown': 0
        }
        
        old_priority = source_priority.get(old_source, 0)
        new_priority = source_priority.get(new_source, 0)
        
        # SZCZEGÓŁOWE LOGOWANIE ZMIAN CEN
        print(f"      🔍 Analiza ceny dla oferty: {existing['id']}")
        print(f"         Stara cena: {old_price} zł (źródło: {old_source}, priorytet: {old_priority})")
        print(f"         Nowa cena: {new_price} zł (źródło: {new_source}, priorytet: {new_priority})")
        
        # DECYZJA: Aktualizuj cenę tylko jeśli:
        # 1. Nowe źródło ma wyższy priorytet, LUB
        # 2. Ten sam priorytet ale cena się zmieniła (realna zmiana ceny), LUB
        # 3. Różnica ceny jest mniejsza niż 50% (zabezpieczenie przed błędami parsera)
        
        should_update = False
        update_reason = None
        is_source_upgrade_correction = False

        if new_priority > old_priority:
            # Lepsze źródło - aktualizuj
            should_update = True
            update_reason = f"Upgrade źródła: {old_source} → {new_source}"
            print(f"      💰 {update_reason}")
            # FIX 2026-06-12: upgrade źródła omijał sanity-check 50%. Cena z lepszego
            # źródła nadal wygrywa, ale różnica >=50% to niemal na pewno KOREKTA
            # błędnej ceny ze słabszego źródła (np. parser tekstowy złapał kwotę
            # mediów), a nie realna zmiana ceny — nie zapisujemy jej jako
            # price_change (trend/previous_price/top5), tylko cicho poprawiamy.
            if old_price and new_price != old_price:
                upgrade_diff_percent = abs(new_price - old_price) / old_price * 100
                if upgrade_diff_percent >= 50:
                    is_source_upgrade_correction = True
                    print(f"      🔧 Różnica {upgrade_diff_percent:.0f}% przy upgrade źródła — "
                          f"traktuję jako korektę, nie zmianę ceny")
        elif new_priority == old_priority and old_price != new_price:
            # To samo źródło ale inna cena - sprawdź czy zmiana sensowna
            price_diff_percent = abs(new_price - old_price) / old_price * 100
            
            if price_diff_percent < 50:  # Max 50% zmiany
                should_update = True
                update_reason = f"Zmiana ceny (to samo źródło): {old_price} → {new_price} zł ({price_diff_percent:.1f}%)"
                print(f"      💰 {update_reason}")
            else:
                # Zbyt duża zmiana - podejrzane, nie aktualizuj
                print(f"      ⚠️ PODEJRZANA zmiana ceny: {old_price} → {new_price} zł ({price_diff_percent:.1f}%) - IGNORUJĘ")
        elif new_priority < old_priority:
            # Gorsze źródło - nie aktualizuj
            print(f"      ℹ️ Zachowano cenę z lepszego źródła: {old_source} ({old_price} zł)")
        else:
            # Ta sama cena, to samo źródło - brak zmian
            print(f"      ✓ Cena bez zmian: {old_price} zł")
        
        if should_update and old_price != new_price and is_source_upgrade_correction:
            # Korekta (upgrade źródła, różnica >=50%): aktualizuj cenę, ale bez
            # previous_price/price_trend/price_changes — to nie jest rynkowa zmiana
            # ceny tylko poprawa błędu parsera. W history NADPISUJEMY błędny wpis
            # zamiast dopisywać (top5 liczy diff z history[0] → current; dopisanie
            # sfabrykowałoby gigantyczną "zmianę ceny" na liście okazji).
            existing['price']['current'] = new_price
            existing['price']['source'] = new_source
            history = existing['price'].setdefault('history', [])
            if history and history[-1] == old_price:
                history[-1] = new_price
            else:
                history.append(new_price)
        elif should_update and old_price != new_price:
            # NOWE: Zapisz poprzednią cenę przed aktualizacją
            existing['price']['previous_price'] = old_price
            existing['price']['price_changed_at'] = now
            
            # Określ kierunek zmiany
            if new_price < old_price:
                existing['price']['price_trend'] = 'down'
                print(f"      📉 Cena SPADŁA: {old_price} → {new_price} zł (↓{old_price - new_price} zł)")
                print(f"      📝 Powód zmiany: {update_reason}")
            else:
                existing['price']['price_trend'] = 'up'
                print(f"      📈 Cena WZROSŁA: {old_price} → {new_price} zł (↑{new_price - old_price} zł)")
                print(f"      📝 Powód zmiany: {update_reason}")
            
            existing['price']['current'] = new_price
            existing['price']['source'] = new_source
            
            # Dodaj do historii
            existing['price']['history'].append(new_price)
            
            # NOWE (top5): dodaj wpis do price_changes z timestampem
            # Struktura: lista {old_price, new_price, changed_at, trend}
            if 'price_changes' not in existing['price']:
                existing['price']['price_changes'] = []
            existing['price']['price_changes'].append({
                'old_price': old_price,
                'new_price': new_price,
                'changed_at': now,
                'trend': 'down' if new_price < old_price else 'up'
            })
        
        # Zawsze aktualizuj media_info (może się zmienić niezależnie)
        existing['price']['media_info'] = new_data['price']['media_info']
        
        # Zaktualizuj coords jeśli nowe dane mają coords a stare nie
        new_coords = new_data.get('address', {}).get('coords')
        existing_coords = existing.get('address', {}).get('coords')
        if new_coords and not existing_coords:
            existing.setdefault('address', {})['coords'] = new_coords
            print(f"      📍 Uzupełniono brakujące coords dla oferty: {existing['id']}")

        # Zaktualizuj adres jeśli nowe parsowanie dało lepszy wynik
        # "Lepszy" = nowy adres wygląda jak ulica (not_garbage) a stary jest śmieciem z tytułu
        new_addr  = new_data.get('address', {})
        old_addr  = existing.get('address', {})
        new_full  = new_addr.get('full', '')
        old_full  = old_addr.get('full', '')
        new_has_num = new_addr.get('has_number', False)
        old_has_num = old_addr.get('has_number', False)

        # Wyznacznik "lepszości" — nowy ma numer którego stary nie miał, lub stary full
        # wygląda jak śmieć z tytułu (zaczyna się wielką literą i ma liczbę bez ul./al.)
        import re as _re
        _garbage_addr = _re.compile(
            r'^[A-ZŚĆŁĄĘÓŻŹŃ][a-z]+\s+\d+$',  # np. "Atrakcyjne 2", "Nowe 3"
            _re.UNICODE
        )
        old_looks_like_garbage = bool(_garbage_addr.match(old_full)) and not old_has_num
        new_looks_better = new_full and new_full != old_full and (
            (new_has_num and not old_has_num) or
            (old_looks_like_garbage and len(new_full) >= 5)
        )

        if new_looks_better:
            old_coords = old_addr.get('coords')  # zachowaj coords
            existing['address'] = dict(new_addr)
            if old_coords and not new_addr.get('coords'):
                existing['address']['coords'] = old_coords
            print(f"      🏠 Zaktualizowano adres: '{old_full}' → '{new_full}'")
        
        # Upewnij się że jest aktywne (REAKTYWACJA nieaktywnych ofert)
        was_inactive = not existing.get('active', True)
        existing['active'] = True
        
        if was_inactive:
            print(f"      🔄 REAKTYWOWANO ofertę: {existing['id']} (była nieaktywna)")
            existing['reactivated_at'] = now
            existing['reactivation_source'] = 'rescrape'  # oferta wróciła w listingu
    
    def _update_days_active(self):
        """
        Aktualizuje pole days_active dla WSZYSTKICH ofert (aktywnych i nieaktywnych).
        Oblicza różnicę w dniach między first_seen a last_seen.
        """
        for offer in self.database['offers']:
            try:
                first_seen = datetime.fromisoformat(offer['first_seen'])
                last_seen = datetime.fromisoformat(offer['last_seen'])
                offer['days_active'] = (last_seen - first_seen).days
            except (ValueError, KeyError) as e:
                print(f"⚠️ Błąd obliczania days_active dla oferty {offer.get('id')}: {e}")
                offer['days_active'] = 0
    
    def _mark_inactive_offers(self, current_offer_ids: List[str], skipped_offer_ids: List[str] = None):
        """
        Oznacza ogłoszenia jako nieaktywne jeśli nie ma ich w bieżącym scanie.
        Reaktywuje oferty które pojawiły się ponownie (w skipped_ids).
        
        Args:
            current_offer_ids: Lista ID ofert które zostały przetworzone (nowe + zaktualizowane)
            skipped_offer_ids: Lista ID ofert które zostały pominięte przez inteligentne skanowanie
        """
        if skipped_offer_ids is None:
            skipped_offer_ids = []
        
        # Wszystkie oferty które powinny być aktywne = przetworzone + pominięte
        # FIX 2026-05-24: porównanie po CID3-IDxxxx zamiast pełnego slugu
        # (slug może się zmienić gdy sprzedawca edytuje tytuł ogłoszenia)
        all_active_cids = set(extract_cid(i) for i in (current_offer_ids + skipped_offer_ids))
        skipped_cids = set(extract_cid(i) for i in skipped_offer_ids)
        
        now = datetime.now(self.tz).isoformat()
        deactivated_count = 0
        reactivated_from_skipped = 0
        
        for offer in self.database['offers']:
            offer_cid = extract_cid(offer.get('id',''))
            if offer_cid in all_active_cids:
                # Oferta jest aktywna - upewnij się że ma active=True
                # i zaktualizuj last_seen dla pominiętych ofert
                if offer_cid in skipped_cids:
                    if not offer.get('active', True):
                        # Reaktywacja oferty która była nieaktywna
                        offer['active'] = True
                        offer['reactivated_at'] = now
                        offer['reactivation_source'] = 'skipped'  # cena nie zmieniła się, scraper pominął detail
                        reactivated_from_skipped += 1
                    # Aktualizuj last_seen dla skipped ofert
                    offer['last_seen'] = now
            elif offer['active']:
                # Oferta nie jest w scanie - dezaktywuj
                offer['active'] = False
                deactivated_count += 1
        
        if deactivated_count > 0:
            print(f"   ⏸️  Oznaczono jako nieaktywne: {deactivated_count}")
        if reactivated_from_skipped > 0:
            print(f"   🔄 Reaktywowano (skipped): {reactivated_from_skipped}")
        
        return deactivated_count
    
    def _deactivation_block_reason(self, scraped_count: int, active_in_db: int):
        """
        Zwraca powód blokady dezaktywacji (ochrona przed blokadą OLX/Cloudflare)
        lub None gdy dezaktywacja jest bezpieczna.

        FIX 2026-06-12: logika wyciągnięta z run_scan do osobnej metody, żeby
        najważniejszy bezpiecznik systemu miał testy (tests/test_main_scan.py).
        Zachowanie identyczne jak wcześniej. NIE USUWAJ tej ochrony.
        """
        if scraped_count == 0 and active_in_db > 0:
            return (f"Scraper zwrócił 0 ofert (baza: {active_in_db} aktywnych) — "
                    f"prawdopodobna blokada OLX/Cloudflare. Dezaktywacja pominięta.")
        if active_in_db >= 10 and scraped_count < active_in_db * self.MIN_DEACTIVATION_RATIO:
            return (f"Scraper zwrócił tylko {scraped_count} ofert przy {active_in_db} aktywnych "
                    f"w bazie (próg: {int(active_in_db * self.MIN_DEACTIVATION_RATIO)}) — "
                    f"prawdopodobna blokada OLX. Dezaktywacja pominięta.")
        return None

    def _verify_inactive_offers(self, max_to_verify: int = 50) -> Dict:
        """
        Weryfikuje nieaktywne oferty sprawdzając bezpośrednio ich URL na OLX.
        Reaktywuje oferty które nadal istnieją na OLX.
        
        Args:
            max_to_verify: Maksymalna liczba ofert do zweryfikowania na jeden skan
            
        Returns:
            Dict ze statystykami: {'verified': N, 'reactivated': N, 'confirmed_inactive': N, 'errors': N}
        """
        import requests
        from bs4 import BeautifulSoup
        
        stats = {
            'verified': 0,
            'reactivated': 0,
            'confirmed_inactive': 0,
            'errors': 0,
            'skipped_recently_verified': 0
        }

        # FIX 2026-06-12: oferty potwierdzone jako nieaktywne dostają znacznik
        # verified_inactive_at i przez VERIFY_COOLDOWN_DAYS nie są sprawdzane
        # ponownie. Wcześniej te same 50 najnowszych nieaktywnych było odpytywane
        # przy KAŻDYM skanie (3×dziennie), w kółko potwierdzając to samo.
        VERIFY_COOLDOWN_DAYS = 7
        cooldown_cutoff = datetime.now(self.tz) - timedelta(days=VERIFY_COOLDOWN_DAYS)

        def _recently_verified(offer):
            ts = offer.get('verified_inactive_at')
            if not ts:
                return False
            try:
                return datetime.fromisoformat(ts) > cooldown_cutoff
            except (ValueError, TypeError):
                return False

        all_inactive = [
            offer for offer in self.database.get('offers', [])
            if not offer.get('active', True)
        ]
        inactive_offers = [o for o in all_inactive if not _recently_verified(o)]
        stats['skipped_recently_verified'] = len(all_inactive) - len(inactive_offers)
        if stats['skipped_recently_verified']:
            print(f"   ⏭️  Pominięto {stats['skipped_recently_verified']} ofert zweryfikowanych w ostatnich {VERIFY_COOLDOWN_DAYS} dniach")
        
        if not inactive_offers:
            print("   ℹ️  Brak nieaktywnych ofert do weryfikacji")
            return stats
        
        # Sortuj od najnowszych (last_seen malejąco)
        inactive_offers.sort(
            key=lambda x: x.get('last_seen', '1970-01-01'),
            reverse=True
        )
        
        # Ogranicz do max_to_verify
        to_verify = inactive_offers[:max_to_verify]
        
        print(f"   🔍 Weryfikuję {len(to_verify)} nieaktywnych ofert (z {len(inactive_offers)} łącznie)...")
        
        # Użyj sesji scrapera z odpowiednimi headerami
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'
        })
        
        now = datetime.now(self.tz).isoformat()
        
        for i, offer in enumerate(to_verify, 1):
            url = offer.get('url', '')
            offer_id = offer.get('id', 'unknown')
            
            if not url:
                continue
                
            try:
                # Opóźnienie między requestami (anti-throttling)
                if i > 1:
                    time.sleep(random.uniform(0.3, 0.7))
                
                response = session.get(url, timeout=15)
                stats['verified'] += 1
                
                # Sprawdź czy oferta istnieje
                if response.status_code in (404, 410):
                    # 404 = Not Found, 410 = Gone - oferta usunięta
                    stats['confirmed_inactive'] += 1
                    offer['verified_inactive_at'] = now
                    continue
                
                if response.status_code != 200:
                    stats['errors'] += 1
                    continue
                
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Sprawdź status oferty przez JSON-LD (najbardziej wiarygodne źródło)
                is_active = False
                
                scripts = soup.find_all('script', type='application/ld+json')
                for script in scripts:
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict) and data.get('@type') == 'Product':
                            availability = data.get('offers', {}).get('availability', '')
                            # InStock = aktywna oferta
                            if 'InStock' in availability:
                                is_active = True
                            break
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        continue
                
                # Jeśli nie ma JSON-LD, sprawdź elementy HTML
                if not is_active:
                    # Sprawdź czy jest cena (znak aktywnej oferty)
                    price_element = soup.select_one('[data-testid="ad-price-container"]')
                    # Sprawdź czy są przyciski kontaktu
                    contact_btns = soup.select('[data-testid*="phone"], [data-testid*="contact"]')
                    
                    if price_element and len(contact_btns) > 0:
                        is_active = True
                
                if is_active:
                    # Oferta AKTYWNA - reaktywuj!
                    offer['active'] = True
                    offer['last_seen'] = now
                    offer['reactivated_at'] = now
                    offer['reactivation_source'] = 'verification'
                    offer.pop('verified_inactive_at', None)  # znacznik nieaktualny
                    stats['reactivated'] += 1
                    print(f"      ✅ Reaktywowano: {offer_id[:50]}...")
                else:
                    # Oferta nieaktywna - potwierdzone
                    stats['confirmed_inactive'] += 1
                    offer['verified_inactive_at'] = now
                    
            except requests.RequestException as e:
                stats['errors'] += 1
            except Exception as e:
                stats['errors'] += 1
        
        # Podsumowanie
        print(f"   📊 Weryfikacja zakończona:")
        print(f"      Sprawdzono: {stats['verified']}")
        print(f"      Reaktywowano: {stats['reactivated']}")
        print(f"      Potwierdzone nieaktywne: {stats['confirmed_inactive']}")
        if stats['errors'] > 0:
            print(f"      Błędy: {stats['errors']}")
        
        return stats

    def _cleanup_old_offers(self, max_age_days: int = 548):
        """
        Usuwa oferty starsze niż 1.5 roku (548 dni).
        """
        cutoff_date = datetime.now(self.tz) - timedelta(days=max_age_days)
        
        original_count = len(self.database['offers'])
        
        self.database['offers'] = [
            offer for offer in self.database['offers']
            if datetime.fromisoformat(offer['first_seen']) > cutoff_date
        ]
        
        removed = original_count - len(self.database['offers'])
        if removed > 0:
            print(f"🗑️ Usunięto {removed} ofert starszych niż 1.5 roku")
    
    def run_scan(self):
        """Główny proces skanowania z logowaniem statystyk."""
        print("\n" + "="*60)
        print("🎯 SONAR MIESZKANIOWY - Scan Started")
        print("="*60 + "\n")
        
        scan_start_time = time.time()
        now = datetime.now(self.tz)
        print(f"⏰ Czas: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        
        # Rozpocznij logowanie
        self.scan_logger.start_scan()
        
        try:
            # 1. Scraping OLX
            print("📡 Krok 1: Scraping OLX...")
            scraping_start = time.time()
            
            raw_offers = self.scraper.scrape_all_pages(max_pages=50)
            
            scraping_duration = time.time() - scraping_start
            self.scan_logger.log_phase('scraping', scraping_duration, {
                'offers_found': len(raw_offers),
                'max_pages': 50
            })
            
            print(f"✅ Pobrano {len(raw_offers)} surowych ofert\n")
            
            # 2. Przetwarzanie ofert
            print("🔧 Krok 2: Przetwarzanie ofert...")
            processing_start = time.time()
            geocoding_time = 0  # Czas geokodowania
            
            processed_offers = []
            # Indeks {address_key: [oferty]} do deduplikacji w O(n·k) zamiast O(n²).
            # Duplikat wymaga identycznego adresu, więc porównujemy opisy tylko
            # w obrębie tego samego adresu (zwykle 1-2 oferty na adres).
            processed_by_address = {}
            skipped_no_address = 0
            skipped_no_price = 0
            skipped_no_coords = 0
            skipped_duplicate = 0
            skipped_removed = 0
            new_geocodes_count = 0      # Ile nowych geokodowań zrobiono w tym skanie
            MAX_NEW_GEOCODES = 150      # Limit geokodowań per skan (Nominatim rate limit)

            # Próbki odrzuconych ofert do analizy (max 50 per kategorię)
            skipped_samples = {
                'no_address': [],
                'no_price': [],
                'no_coords': [],
                'duplicate': []
            }
            SAMPLE_LIMIT = 50

            # FIX 2026-06-12 (perf): set CID-ów usuniętych liczony RAZ, nie w pętli
            # (wcześniej przeliczany od nowa dla każdej z ~530 ofert)
            removed_cids = {extract_cid(rid) for rid in self.removed_listings}

            for i, raw_offer in enumerate(raw_offers, 1):
                print(f"   [{i}/{len(raw_offers)}] Przetwarzam: {raw_offer['title'][:50]}...")

                # Stwórz ID z URL
                offer_id = raw_offer['url'].split('/')[-1].split('.')[0]

                # FILTR: Pomiń usunięte ogłoszenia (porównanie po CID3-IDxxxx)
                offer_cid_for_filter = extract_cid(raw_offer['url'])
                if offer_cid_for_filter in removed_cids or offer_id in self.removed_listings:
                    print(f"      🚫 Pominięto - ogłoszenie usunięte przez użytkownika")
                    skipped_removed += 1
                    continue
                
                # Pomiar czasu geokodowania
                geo_start = time.time()
                # Gdy limit geocodowań osiągnięty, wyłącz fallbacki (tylko cache)
                if new_geocodes_count >= MAX_NEW_GEOCODES:
                    self.geocoder._geocoding_limited = True
                else:
                    self.geocoder._geocoding_limited = False
                cache_before = len(self.geocoder.cache)
                processed = self._process_offer(raw_offer)
                # Zlicz nowe geokodowania (wpisy dodane do cache)
                new_geocodes_count += len(self.geocoder.cache) - cache_before
                geocoding_time += time.time() - geo_start
                
                if not processed:
                    # Zlicz powody odrzucenia + zachowaj próbkę do analizy
                    full_text = raw_offer['title'] + " " + raw_offer.get('description', '')
                    sample = {
                        'url': raw_offer.get('url', ''),
                        'title': raw_offer.get('title', '')[:200],
                        'description_preview': (raw_offer.get('description', '') or '')[:500]
                    }
                    if not self.address_parser.extract_address(full_text):
                        # Sprawdź czy parser znalazłby ulicę bez numeru
                        street_only = self.address_parser.extract_street_only(full_text)
                        if street_only:
                            sample['note'] = f"extract_street_only znalazłby: {street_only['full']}"
                        skipped_no_address += 1
                        if len(skipped_samples['no_address']) < SAMPLE_LIMIT:
                            skipped_samples['no_address'].append(sample)
                    elif not self.price_parser.extract_price(full_text) and not raw_offer.get('official_price'):
                        skipped_no_price += 1
                        if len(skipped_samples['no_price']) < SAMPLE_LIMIT:
                            skipped_samples['no_price'].append(sample)
                    else:
                        skipped_no_coords += 1
                        if len(skipped_samples['no_coords']) < SAMPLE_LIMIT:
                            addr = self.address_parser.extract_address(full_text)
                            sample['address_parsed'] = addr['full'] if addr else None
                            skipped_samples['no_coords'].append(sample)
                    continue
                
                # Sprawdź duplikaty — tylko wśród ofert pod tym samym adresem (indeks).
                original_dup = self.duplicate_detector.find_duplicate_indexed(processed, processed_by_address)
                if original_dup is not None:
                    skipped_duplicate += 1
                    print(f"      ⚠️ Duplikat - ignoruję")
                    if len(skipped_samples['duplicate']) < SAMPLE_LIMIT:
                        similarity = self.duplicate_detector.calculate_similarity(
                            processed.get('description', ''),
                            original_dup.get('description', '')
                        )
                        skipped_samples['duplicate'].append({
                            'url': raw_offer.get('url', ''),
                            'title': raw_offer.get('title', '')[:200],
                            'address_parsed': processed['address']['full'],
                            'price': processed.get('price', {}).get('current'),
                            'duplicate_of': {
                                'url': original_dup.get('url', ''),
                                'id': original_dup.get('id', ''),
                                'address': original_dup.get('address', {}).get('full', ''),
                                'price': original_dup.get('price', {}).get('current')
                            },
                            'similarity': round(similarity, 4)
                        })
                    continue
                
                processed_offers.append(processed)
                processed_by_address.setdefault(
                    self.duplicate_detector.address_key(processed), []
                ).append(processed)
                print(f"      ✅ {processed['address']['full']} - {processed['price']['current']} zł")

            # Zapisz próbki odrzuconych do analizy (nadpisuje przy każdym skanie)
            try:
                samples_path = self.data_file.parent / 'skipped_offers_sample.json'
                with open(samples_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'scan_timestamp': datetime.now(self.tz).isoformat(),
                        'counts': {
                            'no_address': skipped_no_address,
                            'no_price': skipped_no_price,
                            'no_coords': skipped_no_coords,
                            'duplicate': skipped_duplicate
                        },
                        'samples': skipped_samples
                    }, f, ensure_ascii=False, indent=2)
                print(f"   📊 Zapisano próbki odrzuconych do {samples_path.name}")
            except Exception as e:
                print(f"   ⚠️ Nie udało się zapisać skipped_offers_sample.json: {e}")

            processing_duration = time.time() - processing_start
            self.scan_logger.log_phase('processing', processing_duration, {
                'processed': len(processed_offers),
                'skipped_no_address': skipped_no_address,
                'skipped_no_price': skipped_no_price,
                'skipped_no_coords': skipped_no_coords,
                'skipped_duplicate': skipped_duplicate,
                'skipped_removed': skipped_removed
            })
            
            # Dodaj metryki geokodowania
            self.scan_logger.log_phase('geocoding', geocoding_time, {
                'geocoded_addresses': len(processed_offers)
            })
            
            print(f"\n✅ Przetworzone oferty: {len(processed_offers)}")
            print(f"   Pominięte - brak adresu: {skipped_no_address}")
            print(f"   Pominięte - brak ceny: {skipped_no_price}")
            # skipped_no_coords jest teraz 0 - oferty bez coords trafiają do bazy jako unlocalised
            unlocalised_count = sum(1 for o in processed_offers if not o.get('address', {}).get('coords'))
            print(f"   Bez lokacji GPS (warstwa dodatkowa): {unlocalised_count}")
            print(f"   Nowe geokodowania w tym skanie: {new_geocodes_count} (limit: {MAX_NEW_GEOCODES})")
            print(f"   Pominięte - duplikaty: {skipped_duplicate}")
            print(f"   Pominięte - usunięte przez użytkownika: {skipped_removed}\n")
            
            # 3. Aktualizacja bazy danych
            print("💾 Krok 3: Aktualizacja bazy danych...")
            
            current_offer_ids = []
            new_offers_count = 0
            updated_offers_count = 0
            reactivated_count = 0

            # FIX 2026-06-12 (perf): indeks CID → oferta zamiast liniowego skanu
            # całej bazy dla każdej przetworzonej oferty (~500 × 1375 porównań
            # z extract_cid per porównanie). setdefault zachowuje semantykę
            # "pierwsza pasująca" z _find_existing_offer.
            cid_index = {}
            for offer in self.database['offers']:
                cid_index.setdefault(extract_cid(offer.get('id', '')), offer)

            for processed in processed_offers:
                current_offer_ids.append(processed['id'])

                existing = cid_index.get(extract_cid(processed['id']))

                if existing:
                    was_inactive = not existing.get('active', True)
                    self._update_existing_offer(existing, processed)
                    updated_offers_count += 1
                    if was_inactive:
                        reactivated_count += 1
                else:
                    self.database['offers'].append(processed)
                    cid_index.setdefault(extract_cid(processed['id']), processed)
                    new_offers_count += 1
            
            # Oznacz nieaktywne (ale pominij oferty które były skipped - one są nadal aktywne)
            # UWAGA: raw_offers nie mają klucza 'id', trzeba go wyciągnąć z URL
            skipped_ids = [
                offer['url'].split('/')[-1].split('.')[0] 
                for offer in raw_offers 
                if offer.get('skipped', False)
            ]

            # ZABEZPIECZENIE: Ochrona przed masową dezaktywacją przy blokadzie OLX
            # (Cloudflare, rate limit, pusta odpowiedź, itp.)
            # Jeśli scraper zwrócił 0 ofert lub podejrzanie mało w stosunku do bazy,
            # NIE dezaktywuj niczego - to prawie na pewno problem ze scrapem, nie z ofertami.
            active_in_db = sum(1 for o in self.database['offers'] if o.get('active'))
            scraped_count = len(raw_offers)

            deactivated_count = 0
            # FIX 2026-06-12: blokada OLX była raportowana jako "✅ sukces, brak zmian"
            # (status completed, zero errors). Teraz logujemy błąd do scan_history —
            # api_generator zamieni go na uiStatus=warning i powiadomienie ⚠️.
            block_reason = self._deactivation_block_reason(scraped_count, active_in_db)
            scrape_blocked = block_reason is not None
            if scrape_blocked:
                print(f"   ⚠️  OCHRONA: {block_reason}")
                self.scan_logger.log_error(block_reason)
            else:
                deactivated_count = self._mark_inactive_offers(current_offer_ids, skipped_ids)
            
            # Aktualizuj days_active dla WSZYSTKICH ofert
            self._update_days_active()
            
            print(f"   Nowe oferty: {new_offers_count}")
            print(f"   Zaktualizowane: {updated_offers_count}")
            if reactivated_count > 0:
                print(f"   🔄 Reaktywowane: {reactivated_count}")
            
            # 4. Weryfikacja nieaktywnych ofert
            # FIX 2026-06-12: przy blokadzie OLX pomijamy weryfikację — 50 requestów
            # i tak skończyłoby się błędami (w skanach z 11-12.06 errors=50/50).
            print("\n🔍 Krok 4: Weryfikacja nieaktywnych ofert...")
            if scrape_blocked:
                print("   ⏭️  Pominięto (blokada OLX wykryta w tym skanie)")
                verification_stats = {'verified': 0, 'reactivated': 0, 'confirmed_inactive': 0, 'errors': 0, 'skipped_blocked': True}
            else:
                verification_stats = self._verify_inactive_offers(max_to_verify=50)
            reactivated_count += verification_stats.get('reactivated', 0)
            
            # 5. Czyszczenie starych ofert
            print("\n🗑️ Krok 5: Czyszczenie starych ofert...")
            self._cleanup_old_offers(max_age_days=548)
            
            # 6. Aktualizacja metadanych
            self.database['last_scan'] = now.isoformat()
            self.database['next_scan'] = self._calculate_next_scan_time()
            
            # 7. Zapisz bazę
            print("\n💾 Krok 6: Zapisywanie bazy danych...")
            self._save_database()
            
            # 8. Loguj statystyki
            total_duration = time.time() - scan_start_time
            
            active = sum(1 for o in self.database['offers'] if o['active'])
            inactive = len(self.database['offers']) - active
            
            self.scan_logger.log_stats({
                'raw_offers': len(raw_offers),
                'processed': len(processed_offers),
                'new': new_offers_count,
                'updated': updated_offers_count,
                'reactivated': reactivated_count,
                'total_in_db': len(self.database['offers']),
                'active': active,
                'inactive': inactive,
                'skipped_no_address': skipped_no_address,
                'skipped_no_price': skipped_no_price,
                'skipped_no_coords': skipped_no_coords,
                'skipped_duplicate': skipped_duplicate,
                'skipped_removed': skipped_removed,
                'disappeared': deactivated_count,
                'verification': verification_stats
            })
            
            self.scan_logger.end_scan('completed', total_duration)
            
            # 9. Podsumowanie
            print("\n" + "="*60)
            print("📊 PODSUMOWANIE SCANU")
            print("="*60)
            print(f"✅ Oferty aktywne: {active}")
            print(f"📁 Oferty nieaktywne (historia): {inactive}")
            print(f"📦 Łącznie w bazie: {len(self.database['offers'])}")
            print(f"⏱️ Czas wykonania: {total_duration:.1f}s")
            print(f"⏰ Następny scan: {datetime.fromisoformat(self.database['next_scan']).strftime('%Y-%m-%d %H:%M')}")
            print("="*60 + "\n")
            
        except Exception as e:
            # W przypadku błędu, zaloguj i zakończ jako failed
            print(f"\n❌ Błąd podczas skanowania: {e}")
            self.scan_logger.log_error(str(e))
            self.scan_logger.end_scan('failed', time.time() - scan_start_time)
            raise


if __name__ == "__main__":
    agent = SonarMieszkaniowy(data_file=paths.OFFERS_JSON)
    agent.run_scan()
