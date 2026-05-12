"""
OLX Scraper - pobiera wszystkie oferty wynajmu mieszkań w Lublinie
Obsługuje paginację (wszystkie strony), opóźnienia anti-block
WERSJA 2.0: Równoległe pobieranie szczegółów (ThreadPoolExecutor)
"""

import requests
from bs4 import BeautifulSoup
import time
import random
import re
import json
from typing import List, Dict, Optional
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

class OLXScraper:
    BASE_URL = "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/lublin/"
    
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pl,en-US;q=0.7,en;q=0.3',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    def __init__(self, delay_range: tuple = (2, 4), max_workers: int = 5, existing_offers: dict = None):
        """
        Args:
            delay_range: Zakres opóźnień między requestami (min, max) w sekundach
            max_workers: Liczba równoległych wątków dla pobierania szczegółów
            existing_offers: Słownik istniejących ofert {id: {'price': X, ...}} do inteligentnego pomijania
        """
        self.delay_min, self.delay_max = delay_range
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        
        # Thread-safe rate limiter
        self._lock = threading.Lock()
        self._last_request_time = 0
        
        # Inteligentne pomijanie - istniejące oferty
        self.existing_offers = existing_offers or {}
        
        # Statystyki pomijania
        self.stats = {
            'skipped_same_price': 0,
            'fetched_new': 0,
            'fetched_price_changed': 0
        }
    
    def _extract_price_number(self, price_raw: str) -> Optional[int]:
        """
        Wyciąga samą liczbę z tekstu ceny.
        '850 zł' → 850
        'od 850 zł' → 850
        '1 200 zł' → 1200
        """
        if not price_raw:
            return None
        
        # Usuń "od", "do", "zł", "PLN" i białe znaki
        cleaned = re.sub(r'[^\d\s]', '', price_raw)
        # Połącz cyfry (usuń spacje z "1 200")
        cleaned = cleaned.replace(' ', '').strip()
        
        if cleaned.isdigit():
            return int(cleaned)
        return None
    
    def _random_delay(self):
        """Thread-safe losowe opóźnienie między requestami."""
        with self._lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            
            # Minimalne opóźnienie między requestami
            min_interval = self.delay_min
            if time_since_last < min_interval:
                sleep_time = min_interval - time_since_last
                time.sleep(sleep_time)
            
            # Dodatkowe losowe opóźnienie
            extra_delay = random.uniform(0, self.delay_max - self.delay_min)
            if extra_delay > 0:
                time.sleep(extra_delay)
            
            self._last_request_time = time.time()
    
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Pobiera stronę i zwraca BeautifulSoup object.
        """
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            # Użyj response.text (automatycznie zdekodowany) zamiast response.content
            return BeautifulSoup(response.text, 'lxml')
        except requests.RequestException as e:
            print(f"❌ Błąd pobierania {url}: {e}")
            return None
    
    def _extract_offers_from_page(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Wyciąga wszystkie oferty z pojedynczej strony.
        
        Returns:
            Lista Dict z kluczami: url, title, description_snippet, price_raw
        """
        offers = []
        seen_urls = set()  # Deduplikacja
        
        # Nowa strategia: znajdź wszystkie linki do /d/oferta/ i wyciągnij dane z kontekstu
        all_links = soup.find_all('a', href=lambda x: x and '/d/oferta/' in str(x))
        
        for link_tag in all_links:
            try:
                # URL ogłoszenia
                url = link_tag.get('href', '')
                if not url.startswith('http'):
                    url = urljoin(self.BASE_URL, url)
                
                # Deduplikacja - normalizuj URL (bez query params)
                clean_url = url.split('?')[0]
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)
                
                # Znajdź kontener ogłoszenia - idź w górę maksymalnie 6 poziomów
                container = None
                title_tag = None
                price_tag = None
                current = link_tag
                
                for _ in range(6):
                    current = current.find_parent()
                    if not current:
                        break
                    
                    # Sprawdź czy ten poziom ma tytuł i cenę
                    title_tag = current.find('h6') or current.find('h4') or current.find('h3')
                    price_tag = current.find('p', {'data-testid': 'ad-price'})
                    
                    if title_tag and price_tag:
                        container = current
                        break
                
                if not container or not title_tag or not price_tag:
                    continue
                
                # Wyciągnij dane
                title = title_tag.get_text(strip=True)
                price_raw = price_tag.get_text(strip=True)
                
                # Minimum validation - tytuł musi mieć >5 znaków
                if len(title) < 5:
                    continue
                
                offers.append({
                    'url': url,
                    'title': title,
                    'description_snippet': "",
                    'price_raw': price_raw
                })
                
            except (AttributeError, TypeError, KeyError) as e:
                print(f"⚠️ Błąd parsowania ogłoszenia: {e}")
                continue
        
        return offers
    
    def _get_next_page_url(self, soup: BeautifulSoup, current_page: int) -> Optional[str]:
        """
        Znajduje URL następnej strony.
        
        Returns:
            URL następnej strony lub None jeśli to ostatnia
        """
        # Szukamy linku "następna" lub page=X
        next_link = soup.find('a', {'data-testid': 'pagination-forward'})
        
        if next_link and next_link.get('href'):
            return urljoin(self.BASE_URL, next_link['href'])
        
        # Alternatywnie: próbujemy page=X+1
        next_page_num = current_page + 1
        
        # Sprawdzamy czy następna strona istnieje (nie róbmy requesta, tylko sprawdźmy czy jest link)
        pagination = soup.find('ul', {'data-testid': 'pagination-list'})
        if pagination:
            page_links = pagination.find_all('a')
            for link in page_links:
                if f"page={next_page_num}" in link.get('href', ''):
                    return urljoin(self.BASE_URL, link['href'])
        
        return None
    
    def scrape_all_pages(self, max_pages: int = 20) -> List[Dict]:
        """
        Scrapuje wszystkie strony z ofertami (z limitem max_pages).
        NOWE: Równoległe pobieranie szczegółów ofert.
        
        Args:
            max_pages: Maksymalna liczba stron do przejrzenia (zabezpieczenie)
            
        Returns:
            Lista wszystkich ofert ze wszystkich stron
        """
        all_offers = []
        current_url = self.BASE_URL
        page_num = 1
        
        print(f"🔍 Rozpoczynam scraping OLX Lublin - Mieszkania...")
        print(f"⚡ Tryb równoległy: {self.max_workers} wątków\n")
        
        # FAZA 1: Pobierz wszystkie podstawowe oferty ze stron listingowych
        while current_url and page_num <= max_pages:
            print(f"📄 Strona {page_num}: {current_url}")
            
            soup = self._fetch_page(current_url)
            if not soup:
                print(f"⚠️ Nie udało się pobrać strony {page_num}")
                break
            
            # Wyciągamy oferty z tej strony
            offers = self._extract_offers_from_page(soup)
            print(f"   Znaleziono {len(offers)} ofert")
            
            if not offers:
                print("   ⚠️ Brak ofert na stronie - koniec paginacji")
                break
            
            all_offers.extend(offers)
            
            # Sprawdzamy czy jest następna strona
            next_url = self._get_next_page_url(soup, page_num)
            
            if not next_url:
                print(f"✅ Osiągnięto ostatnią stronę")
                break
            
            current_url = next_url
            page_num += 1
            
            # Opóźnienie przed następną stroną
            if page_num <= max_pages:
                self._random_delay()
        
        print(f"\n✅ Faza 1: Pobrano {len(all_offers)} podstawowych ofert z {page_num} stron")
        
        # FAZA 2: Inteligentne pobieranie szczegółów (pomijamy oferty ze stałą ceną)
        if all_offers:
            # Rozdziel oferty na: do pobrania vs do pominięcia
            offers_to_fetch = []
            offers_to_skip = []
            
            for offer in all_offers:
                offer_id = offer['url'].split('/')[-1].split('.')[0]
                listing_price = self._extract_price_number(offer['price_raw'])
                
                # Sprawdź czy oferta istnieje w bazie
                if offer_id in self.existing_offers:
                    existing = self.existing_offers[offer_id]
                    existing_price = existing.get('price')
                    
                    # Porównaj ceny (tylko cyfry)
                    if listing_price and existing_price and listing_price == existing_price:
                        # Ta sama cena → pomiń pobieranie szczegółów
                        offers_to_skip.append({
                            'offer': offer,
                            'existing': existing,
                            'reason': 'same_price'
                        })
                        self.stats['skipped_same_price'] += 1
                    else:
                        # Cena się zmieniła → pobierz szczegóły
                        offers_to_fetch.append({
                            'offer': offer,
                            'old_price': existing_price,
                            'new_price': listing_price,
                            'reason': 'price_changed'
                        })
                        self.stats['fetched_price_changed'] += 1
                else:
                    # Nowa oferta → pobierz szczegóły
                    offers_to_fetch.append({
                        'offer': offer,
                        'reason': 'new'
                    })
                    self.stats['fetched_new'] += 1
            
            print(f"\n📊 Inteligentne pobieranie:")
            print(f"   ⏭️  Pominięto (ta sama cena): {len(offers_to_skip)}")
            print(f"   🆕 Nowe oferty do pobrania: {self.stats['fetched_new']}")
            print(f"   💰 Zmieniona cena: {self.stats['fetched_price_changed']}")
            
            # Uzupełnij oferty pominięte danymi z istniejącej bazy
            for item in offers_to_skip:
                offer = item['offer']
                existing = item['existing']
                offer['description'] = existing.get('description', offer['title'])
                offer['official_price'] = existing.get('price')
                offer['official_price_raw'] = f"{existing.get('price')} zł (cache)"
                offer['price_source'] = 'cache'
                offer['skipped'] = True  # Flaga że pominięto pobieranie
                
                # Dodaj adres i współrzędne z cache (dla reaktywacji nieaktywnych ofert)
                if existing.get('address'):
                    offer['cached_address'] = existing.get('address')
                if existing.get('coordinates'):
                    offer['cached_coordinates'] = existing.get('coordinates')
                # Oznacz czy oferta była nieaktywna (do potencjalnej reaktywacji)
                offer['was_inactive'] = not existing.get('was_active', True)
            
            # Pobierz szczegóły tylko dla ofert które tego wymagają
            if offers_to_fetch:
                print(f"\n⚡ Faza 2: Pobieranie szczegółów dla {len(offers_to_fetch)} ofert ({self.max_workers} wątków)...")
                start_time = time.time()
                
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    # Submit tylko oferty do pobrania
                    future_to_item = {
                        executor.submit(self._fetch_single_offer_details, item['offer']): item 
                        for item in offers_to_fetch
                    }
                    
                    # Zbierz wyniki
                    completed = 0
                    total = len(offers_to_fetch)
                    
                    for future in as_completed(future_to_item):
                        completed += 1
                        item = future_to_item[future]
                        try:
                            updated_offer = future.result()
                            # Dodaj info o poprzedniej cenie jeśli się zmieniła
                            if item.get('reason') == 'price_changed':
                                updated_offer['previous_price'] = item.get('old_price')
                            
                            # Zaktualizuj w all_offers
                            for i, o in enumerate(all_offers):
                                if o['url'] == updated_offer['url']:
                                    all_offers[i] = updated_offer
                                    break
                            
                            progress = (completed / total) * 100
                            print(f"\r   Postęp: [{completed}/{total}] {progress:.1f}%", end='', flush=True)
                        except (requests.RequestException, AttributeError, TypeError) as e:
                            print(f"\n   ⚠️ Błąd pobierania: {e}")
                
                elapsed = time.time() - start_time
                print(f"\n✅ Szczegóły pobrane w {elapsed:.1f}s (średnio {elapsed/len(offers_to_fetch):.2f}s/oferta)")
            else:
                print(f"\n✅ Wszystkie oferty pominięte (brak zmian cen)")
        
        print(f"\n✅ Scraping zakończony: {len(all_offers)} ofert z {page_num} stron")
        print(f"   📈 Zaoszczędzono {self.stats['skipped_same_price']} requestów!")
        return all_offers
    
    def fetch_offer_details(self, url: str) -> Optional[Dict]:
        """
        Pobiera pełne szczegóły ogłoszenia (pełny opis + oficjalna cena).
        
        STRATEGIA EKSTRAKCJI CENY (według priorytetu):
        1. JSON-LD schema.org (najbardziej niezawodne - OLX oficjalne dane)
        2. Fallback: HTML <h3> z ceną
        
        Args:
            url: URL ogłoszenia
            
        Returns:
            Dict z pełnym opisem, oficjalną ceną i innymi danymi
        """
        self._random_delay()
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        try:
            # NOWE: Pobierz tytuł z og:title (bardziej niezawodne niż h1)
            title_from_page = ""
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title_from_page = og_title.get('content', '').replace(' • OLX.pl', '').strip()
            
            # Pełny opis
            desc_div = soup.find('div', {'data-cy': 'ad_description'})
            if not desc_div:
                desc_div = soup.find('div', class_=lambda x: x and 'description' in str(x).lower())
            
            description = desc_div.get_text(strip=True) if desc_div else ""
            
            # Usuń prefix "Opis" który OLX dodaje
            if description.startswith('Opis'):
                description = description[4:]
            
            # Połącz tytuł z opisem dla lepszego parsowania adresu
            if title_from_page:
                description = title_from_page + ' ' + description
            
            # === PRIORYTET 1: JSON-LD (najbardziej niezawodne) ===
            official_price = None
            official_price_raw = None
            
            json_ld_script = soup.find('script', {'type': 'application/ld+json'})
            if json_ld_script:
                try:
                    json_data = json.loads(json_ld_script.string)
                    # Schema.org Product -> offers -> price
                    if json_data.get('@type') == 'Product' and 'offers' in json_data:
                        price = json_data['offers'].get('price')
                        if price and isinstance(price, (int, float)):
                            official_price = int(price)
                            official_price_raw = f"{official_price} zł (JSON-LD)"
                            
                            # Walidacja - sensowny zakres dla mieszkań w Lublinie
                            # FIX 2026-05: podniesiono z 5000 na 10000 (Spokojna 10 = 5500 zł, apartamenty premium 6-10k)
                            if 200 <= official_price <= 10000:
                                # Sukces - mamy niezawodną cenę z JSON-LD
                                return {
                                    'description': description,
                                    'official_price': official_price,
                                    'official_price_raw': official_price_raw,
                                    'price_source': 'json-ld'
                                }
                            else:
                                # Cena poza zakresem - odrzuć i użyj fallback
                                official_price = None
                                official_price_raw = None
                except (json.JSONDecodeError, KeyError, TypeError):
                    # JSON-LD nie zadziałało - przejdź do fallback
                    pass
            
            # === FALLBACK: HTML <h3> z ceną ===
            # Tylko jeśli JSON-LD nie zadziałało
            if not official_price:
                for h3 in soup.find_all('h3'):
                    text = h3.get_text(strip=True)
                    # Sprawdź czy zawiera cenę (cyfry + zł)
                    if 'zł' in text.lower() and any(char.isdigit() for char in text):
                        official_price_raw = text
                        # Wyciągnij liczbę - obsługa separatorów tysięcy
                        match = re.search(r'(\d[\d\s]*)', text)
                        if match:
                            price_str = match.group(1).replace(' ', '').replace('\xa0', '')
                            try:
                                price_candidate = int(price_str)
                                # Walidacja
                                # FIX 2026-05: podniesiono z 5000 na 10000 zł
                                if 200 <= price_candidate <= 10000:
                                    official_price = price_candidate
                                    break
                            except ValueError:
                                pass
            
            return {
                'description': description,
                'official_price': official_price,
                'official_price_raw': official_price_raw,
                'price_source': 'html-fallback' if official_price else None
            }
            
        except (AttributeError, TypeError, KeyError, json.JSONDecodeError) as e:
            print(f"⚠️ Błąd parsowania szczegółów ogłoszenia {url}: {e}")
            return None
    
    def _fetch_single_offer_details(self, offer: Dict) -> Dict:
        """
        Wrapper do równoległego pobierania szczegółów pojedynczej oferty.
        Zwraca ofertę z dodanymi szczegółami.
        """
        details = self.fetch_offer_details(offer['url'])
        if details:
            offer['description'] = details['description']
            if details.get('official_price'):
                offer['official_price'] = details['official_price']
                offer['official_price_raw'] = details['official_price_raw']
                offer['price_source'] = details['price_source']  # FIX: kopiuj price_source!
        else:
            # Fallback - użyj tytułu jako opisu
            offer['description'] = offer['title']
        
        return offer


# Testy jednostkowe
if __name__ == "__main__":
    scraper = OLXScraper(delay_range=(0.5, 1), max_workers=5)  # Szybsze dla testów
    
    print("🧪 Test scrapera równoległego - pierwsze 2 strony:\n")
    offers = scraper.scrape_all_pages(max_pages=2)
    
    print(f"\n📊 Podsumowanie:")
    print(f"   Łącznie ofert: {len(offers)}")
    
    if offers:
        print(f"\n📝 Przykładowa oferta:")
        sample = offers[0]
        print(f"   Tytuł: {sample['title'][:60]}...")
        print(f"   URL: {sample['url']}")
        print(f"   Cena: {sample.get('official_price', sample['price_raw'])}")
        print(f"   Opis (pierwsze 100 znaków): {sample.get('description', '')[:100]}...")
