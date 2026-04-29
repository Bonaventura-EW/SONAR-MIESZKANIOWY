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

class SonarMieszkaniowy:
    def __init__(self, data_file: str = "../data/offers.json", removed_file: str = "../data/removed_listings.json"):
        self.data_file = Path(data_file)
        self.removed_file = Path(removed_file)
        self.address_parser = AddressParser()
        self.price_parser = PriceParser()
        self.geocoder = Geocoder(cache_file="../data/geocoding_cache.json")
        self.duplicate_detector = DuplicateDetector(similarity_threshold=0.95)
        self.scan_logger = ScanLogger(log_file="../data/scan_history.json")
        
        # Strefa czasowa polska
        self.tz = pytz.timezone('Europe/Warsaw')
        
        # Wczytaj istniejącą bazę
        self.database = self._load_database()
        
        # Wczytaj listę usuniętych ogłoszeń
        self.removed_listings = self._load_removed_listings()
        
        # Inicjalizuj scraper Z istniejącymi ofertami (inteligentne pomijanie)
        existing_offers = self._build_existing_offers_index()
        self.scraper = OLXScraper(delay_range=(0.5, 1), max_workers=5, existing_offers=existing_offers)
    
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
            
            index[offer['id']] = {
                'price': offer.get('price', {}).get('current'),
                'description': offer.get('description', ''),
                'previous_price': offer.get('price', {}).get('previous_price'),
                'was_active': is_active,
                'address': offer.get('address', ''),
                'coordinates': offer.get('coordinates', {})
            }
            
            if is_active:
                active_count += 1
            else:
                inactive_count += 1
        
        print(f"📚 Zaindeksowano {len(index)} ofert do inteligentnego pomijania "
              f"({active_count} aktywnych, {inactive_count} nieaktywnych z ostatnich 30 dni)")
        return index
    
    def _load_database(self) -> Dict:
        """Wczytuje bazę danych z JSON."""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Uszkodzony plik bazy danych, tworzę nowy")
                return self._create_empty_database()
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
        """Zapisuje listę usuniętych ogłoszeń."""
        self.removed_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.removed_file, 'w', encoding='utf-8') as f:
            json.dump({
                'removed_ids': list(self.removed_listings),
                'last_updated': datetime.now(self.tz).isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def _create_empty_database(self) -> Dict:
        """Tworzy pustą strukturę bazy danych."""
        return {
            "last_scan": None,
            "next_scan": None,
            "offers": []
        }
    
    def _save_database(self):
        """Zapisuje bazę danych do JSON."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.database, f, ensure_ascii=False, indent=2)
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
        
        # FILTR: Wykluczamy ogłoszenia które nie są pokojami w mieszkaniach
        excluded_phrases = [
            'dom jednorodzinny',
            'w domu jednorodzinnym',
            'domek jednorodzinny',
            'willa',
            'domek',
            'dom w zabudowie',
            'segment',
            'bliźniak'
        ]
        
        full_text_lower = full_text.lower()
        for phrase in excluded_phrases:
            if phrase in full_text_lower:
                print(f"      ⚠️ Wykluczono: {phrase}")
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
            print(f"      📍 Użyto współrzędnych z cache: {coords['lat']:.4f}, {coords['lon']:.4f}")
        else:
            coords = self.geocoder.geocode_address(address_data['full'])
            if not coords:
                print(f"⚠️ Nie można geokodować: {address_data['full']}")
                return None  # Nie znaleziono współrzędnych → ignoruj
        
        # 5. Stwórz ID z URL (unikalne)
        offer_id = raw_offer['url'].split('/')[-1].split('.')[0]
        
        return {
            'id': offer_id,
            'url': raw_offer['url'],
            'address': {
                'full': address_data['full'],
                'street': address_data.get('street', ''),
                'number': address_data.get('number'),
                'has_number': address_data.get('has_number', True),
                'coords': coords
            },
            'price': {
                'current': price,
                'history': [price],
                'media_info': media_info,
                'source': price_source  # Dodane: JSON-LD / Parser / HTML fallback
            },
            'description': full_text,
            'first_seen': datetime.now(self.tz).isoformat(),
            'last_seen': datetime.now(self.tz).isoformat(),
            'active': True,
            'days_active': 0
        }
    
    def _find_existing_offer(self, offer_id: str) -> Dict:
        """Znajduje istniejące ogłoszenie po ID."""
        for offer in self.database['offers']:
            if offer['id'] == offer_id:
                return offer
        return None
    
    def _update_existing_offer(self, existing: Dict, new_data: Dict):
        """Aktualizuje istniejące ogłoszenie z inteligentnym zarządzaniem ceną."""
        now = datetime.now(self.tz).isoformat()
        
        # Aktualizuj last_seen
        existing['last_seen'] = now
        
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
        
        if new_priority > old_priority:
            # Lepsze źródło - aktualizuj
            should_update = True
            update_reason = f"Upgrade źródła: {old_source} → {new_source}"
            print(f"      💰 {update_reason}")
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
        
        if should_update and old_price != new_price:
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
        
        # Zawsze aktualizuj media_info (może się zmienić niezależnie)
        existing['price']['media_info'] = new_data['price']['media_info']
        
        # Upewnij się że jest aktywne (REAKTYWACJA nieaktywnych ofert)
        was_inactive = not existing.get('active', True)
        existing['active'] = True
        
        if was_inactive:
            print(f"      🔄 REAKTYWOWANO ofertę: {existing['id']} (była nieaktywna)")
            existing['reactivated_at'] = now
    
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
        all_active_ids = set(current_offer_ids + skipped_offer_ids)
        skipped_set = set(skipped_offer_ids)
        
        now = datetime.now(self.tz).isoformat()
        deactivated_count = 0
        reactivated_from_skipped = 0
        
        for offer in self.database['offers']:
            if offer['id'] in all_active_ids:
                # Oferta jest aktywna - upewnij się że ma active=True
                # i zaktualizuj last_seen dla pominiętych ofert
                if offer['id'] in skipped_set:
                    if not offer.get('active', True):
                        # Reaktywacja oferty która była nieaktywna
                        offer['active'] = True
                        offer['reactivated_at'] = now
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
            'errors': 0
        }
        
        # Pobierz nieaktywne oferty, posortowane od najnowszych (ostatnio dezaktywowane)
        inactive_offers = [
            offer for offer in self.database.get('offers', [])
            if not offer.get('active', True)
        ]
        
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
                    except:
                        pass
                
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
                    stats['reactivated'] += 1
                    print(f"      ✅ Reaktywowano: {offer_id[:50]}...")
                else:
                    # Oferta nieaktywna - potwierdzone
                    stats['confirmed_inactive'] += 1
                    
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
            skipped_no_address = 0
            skipped_no_price = 0
            skipped_no_coords = 0
            skipped_duplicate = 0
            skipped_removed = 0
            
            for i, raw_offer in enumerate(raw_offers, 1):
                print(f"   [{i}/{len(raw_offers)}] Przetwarzam: {raw_offer['title'][:50]}...")
                
                # Stwórz ID z URL
                offer_id = raw_offer['url'].split('/')[-1].split('.')[0]
                
                # FILTR: Pomiń usunięte ogłoszenia
                if offer_id in self.removed_listings:
                    print(f"      🚫 Pominięto - ogłoszenie usunięte przez użytkownika")
                    skipped_removed += 1
                    continue
                
                # Pomiar czasu geokodowania
                geo_start = time.time()
                processed = self._process_offer(raw_offer)
                geocoding_time += time.time() - geo_start
                
                if not processed:
                    # Zlicz powody odrzucenia
                    full_text = raw_offer['title'] + " " + raw_offer.get('description', '')
                    if not self.address_parser.extract_address(full_text):
                        skipped_no_address += 1
                    elif not self.price_parser.extract_price(full_text) and not raw_offer.get('official_price'):
                        skipped_no_price += 1
                    else:
                        skipped_no_coords += 1
                    continue
                
                # Sprawdź duplikaty
                if self.duplicate_detector.filter_duplicates(processed, processed_offers):
                    skipped_duplicate += 1
                    print(f"      ⚠️ Duplikat - ignoruję")
                    continue
                
                processed_offers.append(processed)
                print(f"      ✅ {processed['address']['full']} - {processed['price']['current']} zł")
            
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
            print(f"   Pominięte - brak współrzędnych: {skipped_no_coords}")
            print(f"   Pominięte - duplikaty: {skipped_duplicate}")
            print(f"   Pominięte - usunięte przez użytkownika: {skipped_removed}\n")
            
            # 3. Aktualizacja bazy danych
            print("💾 Krok 3: Aktualizacja bazy danych...")
            
            current_offer_ids = []
            new_offers_count = 0
            updated_offers_count = 0
            reactivated_count = 0
            
            for processed in processed_offers:
                current_offer_ids.append(processed['id'])
                
                existing = self._find_existing_offer(processed['id'])
                
                if existing:
                    was_inactive = not existing.get('active', True)
                    self._update_existing_offer(existing, processed)
                    updated_offers_count += 1
                    if was_inactive:
                        reactivated_count += 1
                else:
                    self.database['offers'].append(processed)
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
            MIN_RATIO = 0.3  # Scrape musi zwrócić co najmniej 30% wcześniejszej liczby aktywnych
            scraped_count = len(raw_offers)

            if scraped_count == 0 and active_in_db > 0:
                print(f"   ⚠️  OCHRONA: Scraper zwrócił 0 ofert a baza ma {active_in_db} aktywnych.")
                print(f"       Pomijam dezaktywację (prawdopodobna blokada OLX).")
            elif active_in_db >= 10 and scraped_count < active_in_db * MIN_RATIO:
                print(f"   ⚠️  OCHRONA: Scraper zwrócił tylko {scraped_count} ofert, w bazie jest {active_in_db} aktywnych.")
                print(f"       Próg bezpieczeństwa: {int(active_in_db * MIN_RATIO)}. Pomijam dezaktywację.")
                print(f"       Prawdopodobna blokada OLX lub częściowa awaria scrapera.")
            else:
                self._mark_inactive_offers(current_offer_ids, skipped_ids)
            
            # Aktualizuj days_active dla WSZYSTKICH ofert
            self._update_days_active()
            
            print(f"   Nowe oferty: {new_offers_count}")
            print(f"   Zaktualizowane: {updated_offers_count}")
            if reactivated_count > 0:
                print(f"   🔄 Reaktywowane: {reactivated_count}")
            
            # 4. Weryfikacja nieaktywnych ofert
            print("\n🔍 Krok 4: Weryfikacja nieaktywnych ofert...")
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
    agent = SonarMieszkaniowy(data_file="../data/offers.json")
    agent.run_scan()
