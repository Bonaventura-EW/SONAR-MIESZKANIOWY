# 📐 BLUEPRINT — SONAR (system monitorowania ogłoszeń OLX)

> **Cel dokumentu:** Kompletny opis architektury, logiki i decyzji projektowych systemu **SONAR-POKOJOWY** w formie umożliwiającej zbudowanie identycznego systemu dla innej kategorii ogłoszeń (np. **SONAR-MIESZKANIOWY**) bez powtarzania błędów.
>
> **Sposób użycia:** Czytaj sekcje 1–3 (kontekst), potem sekcję 11 (lista podmian) — to wystarczy, żeby zacząć. Sekcje 4–9 są referencyjne, sekcja 10 (lessons learned) jest **OBOWIĄZKOWA** do przeczytania przed pisaniem kodu.

---

## 🔑 PLACEHOLDER — JEDYNA RZECZ DO PODMIANY ŻEBY URUCHOMIĆ NOWY PROJEKT

W pliku `src/scraper.py` znajduje się stała `BASE_URL`. To **jedyne** zewnętrzne źródło danych systemu. Dla nowego projektu należy podmienić ją na URL listingu OLX dla docelowej kategorii:

```python
class OLXScraper:
    BASE_URL = "[INSERT_OLX_URL_HERE]"
    # Przykład SONAR-POKOJOWY: "https://www.olx.pl/nieruchomosci/stancje-pokoje/lublin/"
    # Przykład SONAR-MIESZKANIOWY: "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/lublin/"
```

**Wymagania URL-a:**
- Musi to być strona listingowa OLX (nie pojedyncza oferta).
- Musi obsługiwać paginację (parametr `?page=N`).
- Powinna zwracać linki w formacie `/d/oferta/...` (standardowy format OLX) — w przeciwnym razie selektor w `_extract_offers_from_page()` nie zadziała.
- Kategoria musi mieć ceny (parser zakłada obecność `<p data-testid="ad-price">`).

Wszystkie pozostałe komponenty (parser adresów, geocoder, mapa, monitoring) są **agnostyczne** względem typu ogłoszenia — działają tak samo dla pokoi, mieszkań, biur czy działek, o ile struktura strony OLX jest standardowa.

---

## 1. Wprowadzenie

### 1.1. Cel projektu

SONAR to **statyczny, zero-cost** system monitorowania ogłoszeń jednej kategorii w jednym mieście. Działa w pełni na infrastrukturze GitHub (Actions + Pages), nie wymaga serwera, bazy danych ani API.

**Co robi:**
1. Co kilka godzin scrapuje OLX (cron 3×/dzień).
2. Parsuje adresy z opisów (regex, bo OLX maskuje adresy w meta-danych).
3. Geokoduje adresy do współrzędnych GPS (Nominatim/OpenStreetMap).
4. Wykrywa duplikaty (Levenshtein 95%).
5. Zapisuje do `data/offers.json` (źródło prawdy).
6. Generuje warstwy widokowe: `docs/data.json` (mapa), `docs/monitoring_data.json`, `docs/api/*.json`.
7. Pushuje zmiany do gałęzi `main` — GitHub Pages serwuje frontend (Leaflet.js + Chart.js).

**Co NIE robi (świadomie):**
- Nie używa Selenium / Playwright (OLX renderuje listę server-side, więc wystarczy `requests` + `BeautifulSoup`).
- Nie ma bazy danych — wszystko w plikach JSON commitowanych do repo (history out-of-the-box).
- Nie ma backendu API — endpointy mobilne to statyczne pliki JSON regenerowane przy każdym skanie.
- Nie wysyła powiadomień (planowane w Etap A — patrz sekcja 12).

### 1.2. Stack technologiczny

| Warstwa | Technologia | Wersja | Po co |
|---|---|---|---|
| Scraping | `requests` + `beautifulsoup4` + `lxml` | 2.31 / 4.12 / 5.1 | Pobieranie i parsowanie HTML OLX |
| Geokodowanie | `geopy` (Nominatim) | 2.4.1 | Adres → lat/lon |
| Fuzzy match | `python-Levenshtein` | 0.25.0 | Wykrywanie duplikatów |
| Strefa czasu | `pytz` | 2024.1 | CET/CEST poprawnie |
| Frontend mapa | Leaflet.js (CDN) | 1.9.4 | Mapa interaktywna |
| Frontend wykresy | Chart.js (CDN) | — | Analityka |
| CI/CD | GitHub Actions | — | Cron 3×/dzień |
| Hosting | GitHub Pages | — | Frontend statyczny |
| Język | Python 3.11+ | — | Backend |

---

## 2. Architektura wysokopoziomowa

### 2.1. Przepływ danych (jeden cykl skanu)

```
                    ┌──────────────────┐
                    │  OLX [BASE_URL]  │
                    └────────┬─────────┘
                             │ HTTP GET (paginacja)
                             ▼
            ┌────────────────────────────────┐
            │       src/scraper.py           │
            │  - listing pages (max 50)      │
            │  - detail pages (równolegle)   │
            │  - inteligentne pomijanie      │
            │    (cena bez zmian → skip)     │
            └────────────────┬───────────────┘
                             │ raw_offers (List[Dict])
                             ▼
            ┌────────────────────────────────┐
            │       src/main.py              │
            │  Dla każdej oferty:            │
            │  - address_parser.py (regex)   │
            │  - price_parser.py (JSON-LD)   │
            │  - geocoder.py (Nominatim)     │
            │  - duplicate_detector.py       │
            └────────────────┬───────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   ┌─────────────┐   ┌──────────────────┐   ┌──────────────┐
   │ data/       │   │ data/            │   │ data/        │
   │ offers.json │   │ scan_history.json│   │ geocoding_   │
   │ (źródło)    │   │ (monitoring)     │   │ cache.json   │
   └──────┬──────┘   └────────┬─────────┘   └──────────────┘
          │                   │
          │ map_generator.py  │ monitoring_generator.py
          │                   │ api_generator.py
          ▼                   ▼
   ┌─────────────┐   ┌──────────────────────┐
   │ docs/       │   │ docs/                │
   │ data.json   │   │ monitoring_data.json │
   │ (markers[]  │   │ docs/api/*.json      │
   │  .offers[]) │   │                      │
   └──────┬──────┘   └──────────────────────┘
          │
          ▼
   ┌─────────────┐
   │ GitHub Pages│
   │ (Leaflet,   │
   │  Chart.js)  │
   └─────────────┘
```

### 2.2. Cykl wdrożeniowy (GitHub Actions)

Plik `.github/workflows/scanner.yml` uruchamia się 3×/dzień (cron) lub ręcznie (`workflow_dispatch`).

Sekwencja:
1. `git checkout` z `fetch-depth: 0` (pełna historia).
2. Setup Python 3.11.
3. `pip install -r requirements.txt`.
4. `cd src && python main.py` — pełny skan + zapis do `data/offers.json`.
5. `cd src && python map_generator.py` — generuje `docs/data.json` + `docs/monitoring_data.json`.
6. `cd src && python api_generator.py` — generuje `docs/api/*.json`.
7. `git add data/ docs/data.json docs/monitoring_data.json docs/api/`.
8. Jeśli są zmiany → commit z timestampem CET → push.

**Krytyczne flagi w workflow:**
```yaml
permissions:
  contents: write       # bez tego push nie przejdzie
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true   # wymuszone od deprecation Node 20
continue-on-error: true # każdy krok osobno → częściowe niepowodzenie nie blokuje pozostałych
```

---

## 3. Struktura katalogów

```
SONAR-{POKOJOWY|MIESZKANIOWY}/
├── .github/
│   └── workflows/
│       └── scanner.yml              # Cron 3×/dzień + manual dispatch
│
├── src/
│   ├── main.py                      # Orchestrator (~800 linii)
│   ├── scraper.py                   # OLX scraping (~500 linii) — TU JEST BASE_URL
│   ├── address_parser.py            # Regex adresów (~330 linii)
│   ├── price_parser.py              # Parser cen (JSON-LD priorytet)
│   ├── geocoder.py                  # Nominatim + bbox Lublina
│   ├── duplicate_detector.py        # Levenshtein 95%
│   ├── offer_tagger.py              # Tagi: pokoj/mieszkanie/kawalerka
│   ├── map_generator.py             # data/offers.json → docs/data.json
│   ├── monitoring_generator.py      # → docs/monitoring_data.json
│   ├── api_generator.py             # → docs/api/{status,history,health}.json
│   ├── scan_logger.py               # Zapis statystyk skanu
│   ├── quick_scan.py                # Szybki test (mniej stron)
│   └── remove_listing.py            # Manualne usuwanie z bazy
│
├── data/                            # Źródło prawdy (commitowane)
│   ├── offers.json                  # FLAT lista ofert {offers: [...]}
│   ├── scan_history.json            # 100 ostatnich skanów
│   ├── geocoding_cache.json         # Adres → coords (oszczędza Nominatim)
│   └── removed_listings.json        # Ręcznie usunięte (czarna lista)
│
├── docs/                            # GitHub Pages (publiczne)
│   ├── index.html                   # Mapa Leaflet
│   ├── analytics.html               # Wykresy Chart.js
│   ├── monitoring.html              # Dashboard skanów
│   ├── market_analysis.html         # Lifespan / survival curve
│   ├── data.json                    # NESTED: markers[].offers[]
│   ├── monitoring_data.json
│   ├── api/
│   │   ├── status.json
│   │   ├── history.json
│   │   └── health.json
│   ├── assets/
│   │   ├── style.css
│   │   └── script.js                # Główna logika frontendu
│   └── favicon.svg
│
├── requirements.txt
├── README.md
└── BLUEPRINT.md                     # ← ten plik
```

---

## 4. Backend Python — moduły

### 4.1. `scraper.py` — OLX Scraper

**Jedyny plik z URL-em źródłowym.** Pobiera listing OLX (paginacja) + szczegóły każdej oferty (równolegle).

```python
class OLXScraper:
    BASE_URL = "[INSERT_OLX_URL_HERE]"   # ← TU PODMIANA

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...',
        'Accept-Language': 'pl,en-US;q=0.7,en;q=0.3',
    }

    def __init__(self, delay_range=(0.5, 1), max_workers=5, existing_offers=None):
        self.delay_min, self.delay_max = delay_range
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._lock = threading.Lock()           # rate limiter thread-safe
        self.existing_offers = existing_offers or {}
```

**Inteligentne pomijanie:** Jeśli `existing_offers` zawiera ID i cena na liście jest taka sama jak ostatnio, scraper **nie pobiera szczegółów** (oszczędność ~70% requestów). To krytyczne — bez tego skan trwa 15+ minut zamiast 5.

**Selektor ofert na liście (kluczowy fragment):**

```python
def _extract_offers_from_page(self, soup):
    offers = []
    seen_urls = set()
    # Szukamy wszystkich linków do /d/oferta/
    all_links = soup.find_all('a', href=lambda x: x and '/d/oferta/' in str(x))

    for link_tag in all_links:
        url = link_tag.get('href', '')
        if not url.startswith('http'):
            url = urljoin(self.BASE_URL, url)
        clean_url = url.split('?')[0]
        if clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)

        # Idziemy w górę DOM aż znajdziemy <h6/h4/h3> + <p data-testid="ad-price">
        container = None; title_tag = None; price_tag = None
        current = link_tag
        for _ in range(6):
            current = current.find_parent()
            if not current: break
            title_tag = current.find('h6') or current.find('h4') or current.find('h3')
            price_tag = current.find('p', {'data-testid': 'ad-price'})
            if title_tag and price_tag:
                container = current
                break
        if not container or not title_tag or not price_tag:
            continue
        offers.append({
            'url': url,
            'title': title_tag.get_text(strip=True),
            'description_snippet': "",
            'price_raw': price_tag.get_text(strip=True),
        })
    return offers
```

**Wykrywanie aktywności oferty (na stronie szczegółowej):**

OLX zwraca HTTP 200 nawet dla nieaktywnych ofert (renderuje stronę z komunikatem "ogłoszenie zostało zarchiwizowane"). Jedyny niezawodny sposób to JSON-LD:

```python
def is_offer_active(self, soup):
    """Patrzymy na schema.org JSON-LD: availability='InStock' = aktywne."""
    json_ld_tags = soup.find_all('script', {'type': 'application/ld+json'})
    for tag in json_ld_tags:
        try:
            data = json.loads(tag.string)
            offers = data.get('offers', {})
            if isinstance(offers, dict):
                availability = offers.get('availability', '')
                if 'InStock' in availability:
                    return True
                if 'OutOfStock' in availability or 'SoldOut' in availability:
                    return False
        except (json.JSONDecodeError, AttributeError):
            continue
    return None  # niepewne — nie zmieniaj statusu
```

> ⚠️ **NIE używaj** match po stringach typu `"Ogłoszenie zostało zarchiwizowane"` — OLX serwuje tłumaczenia tego w bundle i25n na **każdej** stronie, więc match daje false positive.

**HTTP 410:** OLX zwraca `410 Gone` dla trwale usuniętych ofert (rzadziej 404). Trzeba obsłużyć obie:

```python
if response.status_code in (404, 410):
    return {'active': False, 'reason': 'removed_permanently'}
```

### 4.2. `address_parser.py` — Parser adresów

OLX **nie udostępnia** strukturalnego adresu — trzeba wyciągać z opisu regex-em. Klucz: kolejność prefiksów (longer first).

```python
class AddressParser:
    # ⚠️ KRYTYCZNE: Dłuższe prefiksy MUSZĄ być przed krótszymi.
    # Inaczej "ulica Narutowicza" zostanie zmatchowana jako "ul" + "ica Narutowicza".
    PREFIX_PATTERN = r'(ulica|ul\.|ul|aleja|aleje|al\.|al|plac|pl\.|pl|osiedle|os\.|os)?\s*'

    ADDRESS_PATTERN = re.compile(
        rf'(ulica|ul\.|ul|aleja|aleje|al\.|al|plac|pl\.|pl|osiedle|os\.|os)?\s*'
        rf'([A-ZŚĆŁĄĘÓŻŹŃ][a-zśćłąęóżźń]+(?:\s+[A-ZŚĆŁĄĘÓŻŹŃ]?[a-zśćłąęóżźń]+)?)\s+'
        rf'(\d+[a-zA-Z]?(?:/\d+)?(?:\s+lok\.\s+\d+)?)',
        re.UNICODE | re.IGNORECASE
    )

    # Polskie nazwiska w dopełniaczu jako nazwy ulic (Langiewicza, Słowackiego, Czuby)
    POLISH_SURNAME_PATTERN = re.compile(
        r'\b([A-ZŚĆŁĄĘÓŻŹŃ][a-zśćłąęóżźń]*'
        r'(?:cza|sza|ego|iego|owej|skiej|skiego|ckiego|nej|nego|wej|wego|ej|a))\s+'
        r'(\d+[a-zA-Z]?(?:/\d+)?)\b',
        re.UNICODE
    )

    PREFIX_MAP = {
        'ul.': '', 'ulica': '',
        'al.': 'Aleja', 'aleja': 'Aleja', 'aleje': 'Aleje',
        'pl.': 'Plac', 'plac': 'Plac',
        'os.': 'Osiedle', 'osiedle': 'Osiedle',
    }
```

**Zwracana struktura:**
```python
{
  'street': 'Narutowicza',
  'number': '5',
  'full': 'Narutowicza 5',          # do geokodowania i grupowania
}
```

### 4.3. `price_parser.py` — Parser cen

**Priorytet źródeł** (zatwierdzone empirycznie):
1. **JSON-LD** (`schema.org/Offer.price`) — najdokładniejsze, 99.9% poprawnych.
2. **Description parser** (regex po opisie: `"850 zł"`, `"od 1 200 PLN"`).
3. **HTML fallback** (`<p data-testid="ad-price">`) — czasem zawiera "od X" lub zakres.

```python
def extract_price(self, soup, description=''):
    # 1. JSON-LD
    for tag in soup.find_all('script', {'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string)
            offer = data.get('offers', {})
            if isinstance(offer, dict):
                price = offer.get('price')
                if price and float(price) > 0:
                    return int(float(price))
        except (json.JSONDecodeError, ValueError, AttributeError):
            continue
    # 2. Description regex
    match = re.search(r'(\d{3,5})\s*(?:zł|PLN)', description)
    if match:
        return int(match.group(1))
    # 3. HTML fallback
    price_tag = soup.find('p', {'data-testid': 'ad-price'})
    if price_tag:
        return self._parse_raw_price(price_tag.get_text())
    return None
```

### 4.4. `geocoder.py` — Geokodowanie + walidacja Lublina

Nominatim ma **rate limit 1 req/s** + wymaga `User-Agent`. Cache jest **obowiązkowy** — jedna pełna baza ofert to ~150 unikalnych adresów, ale przy ponownym geokodowaniu wszystkich na świeżo (np. cache cleanup) bez cache trwa to 2.5 min.

```python
LUBLIN_BBOX = {
    'min_lat': 51.18,   # południe (~3km od skraju)
    'max_lat': 51.30,   # północ (~3km zapasu)
    'min_lon': 22.42,   # zachód
    'max_lon': 22.68,   # wschód
}

class Geocoder:
    def __init__(self, cache_file="data/geocoding_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache = self._load_cache()
        self.geolocator = Nominatim(user_agent="sonar-pokojowy-lublin/1.0")
        # ⚠️ Dla nowego projektu zmień user_agent — Nominatim śledzi nadużycia per UA

    def is_in_lublin(self, coords):
        """Walidacja bbox — bez tego Nominatim wraca z 'Narutowicza' w Białystoku."""
        if not coords: return False
        return (LUBLIN_BBOX['min_lat'] <= coords['lat'] <= LUBLIN_BBOX['max_lat']
                and LUBLIN_BBOX['min_lon'] <= coords['lon'] <= LUBLIN_BBOX['max_lon'])

    def geocode_address(self, address, max_retries=3):
        if not address: return None
        if address in self.cache: return self.cache[address]
        full_address = f"{address}, Lublin, Poland"

        for attempt in range(max_retries):
            try:
                location = self.geolocator.geocode(full_address, timeout=10, language='pl')
                if location:
                    coords = {'lat': location.latitude, 'lon': location.longitude}
                    if not self.is_in_lublin(coords):
                        self.cache[address] = None        # zapisz negatyw
                        self._save_cache()
                        return None
                    self.cache[address] = coords
                    self._save_cache()
                    return coords
                else:
                    self.cache[address] = None
                    self._save_cache()
                    return None
            except GeocoderTimedOut:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
            except GeocoderServiceError:
                return None
        return None
```

### 4.5. `duplicate_detector.py` — Wykrywanie duplikatów

Próg `0.95` (Levenshtein ratio) działa dobrze. Niżej (0.90) → zlepia różne mieszkania na tej samej ulicy. Wyżej (0.98) → przepuszcza spamerskie repostowanie z drobnymi zmianami w opisie.

```python
from Levenshtein import ratio

class DuplicateDetector:
    def __init__(self, similarity_threshold=0.95):
        self.threshold = similarity_threshold

    def is_duplicate(self, offer_a, offer_b):
        # Porównujemy: adres + cena + pierwsze 200 znaków opisu
        if offer_a['address']['full'] != offer_b['address']['full']: return False
        if abs(offer_a['price']['current'] - offer_b['price']['current']) > 50: return False
        desc_a = offer_a.get('description', '')[:200]
        desc_b = offer_b.get('description', '')[:200]
        return ratio(desc_a, desc_b) >= self.threshold
```

### 4.6. `main.py` — Orchestrator

Pełny cykl skanu (uproszczony):

```python
class SonarPokojowy:
    def __init__(self, data_file="../data/offers.json", removed_file="../data/removed_listings.json"):
        self.data_file = Path(data_file)
        self.removed_file = Path(removed_file)
        self.address_parser = AddressParser()
        self.price_parser = PriceParser()
        self.geocoder = Geocoder(cache_file="../data/geocoding_cache.json")
        self.duplicate_detector = DuplicateDetector(similarity_threshold=0.95)
        self.scan_logger = ScanLogger(log_file="../data/scan_history.json")
        self.tz = pytz.timezone('Europe/Warsaw')
        self.database = self._load_database()
        self.removed_listings = self._load_removed_listings()
        existing_offers = self._build_existing_offers_index()
        self.scraper = OLXScraper(delay_range=(0.5, 1), max_workers=5,
                                  existing_offers=existing_offers)

    def run_full_scan(self):
        self.scan_logger.start_scan()
        # 1. SCRAPING
        raw_offers = self.scraper.scrape_all_pages(max_pages=50)
        # 2. PROCESSING (parsowanie + geokodowanie + duplikaty)
        processed_offers = []
        skipped_offer_ids = set()      # ⚠️ MUSI być przekazane do _mark_inactive_offers
        for raw in raw_offers:
            offer_id = raw['url'].split('/')[-1].split('.')[0]
            if offer_id in self.removed_listings:
                continue
            if raw.get('skipped_by_intelligent_skip'):
                skipped_offer_ids.add(offer_id)         # KRYTYCZNE — patrz lessons learned
                continue
            processed = self._process_offer(raw)
            if not processed: continue
            if self.duplicate_detector.filter_duplicates(processed, processed_offers):
                continue
            processed_offers.append(processed)
        # 3. UPDATE BAZY
        self._update_database(processed_offers)
        # 4. ⚠️ MARK INACTIVE — przekaż skipped_offer_ids!
        self._mark_inactive_offers(processed_offers, skipped_offer_ids)
        # 5. SAVE
        self._save_database()
        self.scan_logger.finish_scan()
```

### 4.7. `map_generator.py` — Transformacja do warstwy widoku

To **ostatni krok przed frontendem**. Bierze `data/offers.json` (flat) i tworzy `docs/data.json` (NESTED: markers[].offers[]).

**12-stopniowy gradient cen** (kluczowy element wizualny):

```python
PRICE_RANGES = {
    'range_0_500':     {'label': '0-500 zł',     'min': 0,    'max': 500,    'color': '#00c853'},  # zielony
    'range_501_600':   {'label': '501-600 zł',   'min': 501,  'max': 600,    'color': '#64dd17'},
    'range_601_700':   {'label': '601-700 zł',   'min': 601,  'max': 700,    'color': '#aeea00'},
    'range_701_800':   {'label': '701-800 zł',   'min': 701,  'max': 800,    'color': '#ffd600'},  # żółty
    'range_801_900':   {'label': '801-900 zł',   'min': 801,  'max': 900,    'color': '#ffab00'},
    'range_901_1000':  {'label': '901-1000 zł',  'min': 901,  'max': 1000,   'color': '#ff6f00'},
    'range_1001_1100': {'label': '1001-1100 zł', 'min': 1001, 'max': 1100,   'color': '#ff3d00'},
    'range_1101_1200': {'label': '1101-1200 zł', 'min': 1101, 'max': 1200,   'color': '#d50000'},  # czerwony
    'range_1201_1300': {'label': '1201-1300 zł', 'min': 1201, 'max': 1300,   'color': '#c51162'},
    'range_1301_1400': {'label': '1301-1400 zł', 'min': 1301, 'max': 1400,   'color': '#aa00ff'},
    'range_1401_1500': {'label': '1401-1500 zł', 'min': 1401, 'max': 1500,   'color': '#7c4dff'},
    'range_1501_plus': {'label': '1501+ zł',     'min': 1501, 'max': 999999, 'color': '#6200ea'},  # fioletowy
}

def get_price_range(price):
    for key, r in PRICE_RANGES.items():
        if r['min'] <= price <= r['max']:
            return key
    return 'range_1501_plus'   # ⚠️ FALLBACK MUSI BYĆ OSTATNIM KLUCZEM W PRICE_RANGES
```

> ⚠️ Dla SONAR-MIESZKANIOWY zakresy będą wyższe (mieszkania ~2000-5000 zł). Trzeba przeskalować całe `PRICE_RANGES`. Sugerowane zakresy: 0-1500 / 1501-1750 / ... / co 250 zł / 3501+. Dokładne wartości lepiej dobrać po pierwszym skanie próbnym.

**Format daty (CRITICAL):**

Wewnątrz JSON-ów `data/offers.json` są ISO 8601 z timezone, ale frontend wymaga polskiego formatu. `map_generator.py` konwertuje:

```python
def format_datetime(iso_string):
    """ISO '2026-03-01T15:51:38.344+01:00' → 'DD.MM.YYYY HH:MM' (Polski format)."""
    if '+' in iso_string:
        dt_str = iso_string.split('+')[0]
    elif 'Z' in iso_string:
        dt_str = iso_string.replace('Z', '')
    else:
        dt_str = iso_string
    dt = datetime.fromisoformat(dt_str)
    return dt.strftime('%d.%m.%Y %H:%M')
```

> ⚠️ **PUŁAPKA:** JavaScript `new Date("06.03.2026 17:00")` zwraca `Invalid Date`. Frontend ma własny parser — patrz sekcja 5.2.

### 4.8. `api_generator.py` — Statyczne API

Generuje 3 pliki JSON w `docs/api/`:

```
GET /api/status.json   — status systemu + ostatni skan
GET /api/history.json  — 20 ostatnich skanów
GET /api/health.json   — health check (dla aplikacji mobilnej)
```

`status.json` przykład:
```json
{
  "system": "sonar",
  "status": {"current": "operational", "isHealthy": true, "hasErrors": false},
  "lastScan": {
    "timestamp": "2026-04-28T11:14:08+02:00",
    "durationFormatted": "4m 53s",
    "uiStatus": "success",
    "offers": {"found": 459, "processed": 88, "new": 0, "active": 109}
  },
  "schedule": {"times": ["09:00", "15:00", "21:00"], "nextScanAt": "2026-04-28T15:00:00+02:00"}
}
```

---

## 5. Struktury danych

### 5.1. `data/offers.json` — Źródło prawdy (FLAT)

```json
{
  "last_scan": "2026-04-28T11:14:08.131548+02:00",
  "next_scan": "2026-04-28T15:00:00+02:00",
  "offers": [
    {
      "id": "wynajme-pokoj-lublin-ul-zelazowej-woli-7-CID3-ID19vkwb",
      "url": "https://www.olx.pl/d/oferta/...",
      "address": {
        "full": "Żelazowej Woli 7",
        "street": "Żelazowej Woli",
        "number": "7",
        "coords": {"lat": 51.2697261, "lon": 22.5505625}
      },
      "price": {
        "current": 800,
        "history": [800],
        "media_info": "sprawdź w opisie",
        "previous_price": null,
        "price_trend": null,
        "price_changed_at": null
      },
      "description": "...",
      "first_seen": "2026-02-28T20:46:40.981903+01:00",
      "last_seen": "2026-03-06T17:00:03.362007+01:00",
      "active": false,
      "days_active": 5,
      "reactivated_at": null
    }
  ]
}
```

### 5.2. `docs/data.json` — Warstwa widoku (NESTED)

> ⚠️ **NIE jest** to płaska lista — to drzewo `markers[].offers[]`. Frontend operuje na markerach (jeden marker = jeden adres = N ofert pod tym samym budynkiem).

```json
{
  "markers": [
    {
      "coords": {"lat": 51.2697261, "lon": 22.5505625},
      "address": "Żelazowej Woli 7",
      "has_active": false,
      "offers": [
        {
          "id": "wynajme-pokoj-lublin-ul-zelazowej-woli-7-CID3-ID19vkwb",
          "url": "https://www.olx.pl/...",
          "price": 800,
          "price_range": "range_701_800",   // KAŻDA oferta ma swój zakres (NIE marker)
          "price_history": [800],
          "first_seen": "28.02.2026 20:46",  // Polski format DD.MM.YYYY HH:MM
          "last_seen":  "06.03.2026 17:00",
          "days_active": 5,
          "active": false,
          "is_new": false,
          "description": "...",
          "tags": {"primary": "pokoj", "secondary": ["mieszkanie"], "confidence": 0.95}
        }
      ]
    }
  ],
  "stats": {"active_count": 109, "avg_price": 850, "min_price": 400, "max_price": 1800},
  "scan_info": {"last": "28.04.2026 11:14:08", "next": "28.04.2026 15:00:00"},
  "price_ranges": {/* skopiowane z map_generator.py */},
  "offer_tags": {/* definicje tagów dla frontendu */}
}
```

### 5.3. Format daty — pułapka JS

`docs/data.json` używa formatu `"DD.MM.YYYY HH:MM"` (np. `"28.02.2026 20:46"`). To **nie parsuje się przez `new Date()`** w JavaScript. Frontend ma własny parser:

```javascript
// docs/assets/script.js
function parsePolishDate(str) {
    // "28.02.2026 20:46" → Date
    if (!str || typeof str !== 'string') return null;
    const m = str.match(/^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/);
    if (!m) return null;
    return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]);
}
```

---

## 6. Frontend (GitHub Pages)

### 6.1. `index.html` — Mapa Leaflet

Struktura:
- Header z linkami do innych podstron
- Pasek filtra daty (suwak dni od dodania)
- Kontener mapy `#map` (Leaflet, OSM tiles)
- Sidebar z listą ofert (synchronizowany z mapą)
- Kontrolki filtrów: cena, aktywne/nieaktywne, tagi, warstwy uniwersytetów

CDN-y używane (wszystkie pinowane wersje):
```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

### 6.2. `analytics.html` + `market_analysis.html`

- **analytics.html:** średnie ceny w czasie, rozkład cenowy, trendy nowe vs wygasłe — Chart.js.
- **market_analysis.html:** lifespan/survival curve (jak długo oferty żyją na rynku) — kluczowy wskaźnik dla użytkownika ("czy to oferta wartościowa, czy odbicie?").

### 6.3. `monitoring.html`

Dashboard skanów: success rate, czasy wykonania, błędy, performance charts (czas scrapingu vs liczba ofert).

### 6.4. Spiral offset (overlapping markers)

Jeden adres → wiele ofert → markery na siebie nachodzą. Rozwiązanie: spirala wokół środkowej współrzędnej.

```javascript
function spiralOffset(idx, total, baseLat, baseLon) {
    if (total === 1) return [baseLat, baseLon];
    const angle = (idx / total) * 2 * Math.PI;
    const radius = 0.0001 * Math.ceil(idx / 8);   // ~10m offset, rośnie co 8 ofert
    return [baseLat + radius * Math.cos(angle), baseLon + radius * Math.sin(angle)];
}
```

---

## 7. CI/CD — `.github/workflows/scanner.yml`

```yaml
name: SONAR Scanner

on:
  schedule:
    # 3 skany dziennie. Letni czas (CEST = UTC+2): 7:00, 13:00, 19:00 UTC = 9:00, 15:00, 21:00 CEST
    - cron: '0 7,13,19 * * *'
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true   # od deprecation Node 20

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run scanner
        continue-on-error: true
        id: scanner
        run: |
          cd src
          python main.py || echo "::warning::Scanner failed but continuing..."

      - name: Generate map data
        if: success() || steps.scanner.outcome == 'failure'
        continue-on-error: true
        run: |
          cd src
          python map_generator.py || echo "::warning::Map generator failed but continuing..."

      - name: Generate mobile API
        if: always()
        continue-on-error: true
        run: |
          cd src
          python api_generator.py || echo "::warning::API generator failed but continuing..."

      - name: Commit and push changes
        if: always()
        run: |
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git config --global user.name "github-actions[bot]"
          git add data/ docs/data.json docs/monitoring_data.json docs/api/ || true
          if git diff --staged --quiet; then
            echo "No changes to commit"
          else
            git commit -m "🤖 Automatyczny scan: $(TZ='Europe/Warsaw' date +'%Y-%m-%d %H:%M')" || true
            git push || echo "::warning::Push failed"
          fi
```

**Decyzje świadome:**
- `continue-on-error: true` na każdym kroku — częściowe niepowodzenie (np. timeout Nominatim) nie blokuje generowania mapy.
- `if: always()` na commit — nawet jeśli scan się wykrzaczył, push świeżego monitoring_data.json.
- `fetch-depth: 0` — bez tego git history za płytkie do wykrywania zmian.

---

## 8. Konfiguracja parametrów

| Parametr | Plik | Wartość domyślna | Opis |
|---|---|---|---|
| `BASE_URL` | `scraper.py` | (do podmiany) | URL listingu OLX |
| `delay_range` | `main.py` (init Scrapera) | `(0.5, 1)` | Min/max sekund między requestami |
| `max_workers` | `main.py` | `5` | Wątki ThreadPool dla detali ofert |
| `max_pages` | `main.py` (`scrape_all_pages`) | `50` | Maks. stron listingu |
| `similarity_threshold` | `main.py` (DuplicateDetector) | `0.95` | Próg Levenshtein |
| `LUBLIN_BBOX` | `geocoder.py` | (lat 51.18-51.30, lon 22.42-22.68) | Walidacja geokodowania |
| `PRICE_RANGES` | `map_generator.py` | 12 zakresów 0–1501+ | Gradient kolorów |
| `SCAN_SCHEDULE` | `api_generator.py` | `["09:00", "15:00", "21:00"]` | Tylko do wyświetlania |
| Cron | `scanner.yml` | `0 7,13,19 * * *` (UTC) | Faktyczny harmonogram |
| `user_agent` | `geocoder.py` | `"sonar-pokojowy-lublin/1.0"` | **MUSI być unikalny per projekt** |

---

## 9. Lessons Learned — KRYTYCZNE (przeczytać przed kodowaniem!)

### 9.1. Struktura danych

1. **`docs/data.json` to drzewo, nie lista.** Ma `markers[].offers[]`, NIE płaską listę. Frontend iteruje po markerach, nie po ofertach. Przy dodawaniu funkcji frontendowej zawsze pamiętaj o tym poziomie zagnieżdżenia.

2. **`data/offers.json` ≠ `docs/data.json`.** Modyfikacja źródła nie propaguje się sama. Po każdej zmianie w `data/offers.json` (np. usunięcie wpisów, naprawa adresów) trzeba **ręcznie** uruchomić:
   ```bash
   cd src && python map_generator.py
   ```

3. **`data/geocoding_cache.json` trzeba czyścić razem z `offers.json`.** Jeśli usuwasz oferty z błędnymi adresami z `offers.json`, ale zostawiasz złe wpisy w cache, przy następnym skanie te same złe adresy znów się dostaną do bazy z cache.

4. **Daty w `docs/data.json` to format `"DD.MM.YYYY HH:MM"`** — `new Date()` w JS tego nie parsuje. Frontend ma własny `parsePolishDate()`. Przy dodawaniu nowych pól datowych do `map_generator.py` używaj `format_datetime()`.

### 9.2. OLX-specific

5. **HTTP 410 dla trwale usuniętych ofert** (nie tylko 404). Obsługa obu w response handler.

6. **Aktywność oferty: `availability: InStock` w JSON-LD.** NIE używaj match po stringu komunikatu o archiwizacji — OLX serwuje te stringi w bundle i18n na każdej stronie (false positive). JSON-LD jest w `<script type="application/ld+json">`.

7. **Priorytet źródeł ceny:** `JSON-LD → description regex → HTML fallback`. JSON-LD ma 99.9% accuracy, regex 95%, HTML często zawiera "od X" i myli się.

8. **Inteligentne pomijanie wymaga listy ID.** `_mark_inactive_offers()` MUSI dostać `skipped_offer_ids` jako parametr, inaczej oferty pominięte przez intelligent skip zostaną oznaczone jako nieaktywne (false deactivation). Pełna sygnatura:
   ```python
   def _mark_inactive_offers(self, processed_offers, skipped_offer_ids):
   ```

### 9.3. Parsery / regex

9. **Kolejność prefiksów w regex adresów: dłuższe przed krótszymi.** `ulica` przed `ul`, `aleja` przed `al`, `osiedle` przed `os`. Inaczej `ulica Narutowicza` matchnie się jako `ul + ica Narutowicza`.

10. **`get_price_range()` fallback musi pasować do ostatniego klucza w `PRICE_RANGES`.** Inaczej oferty powyżej max trafią do `range_1501_plus` którego nie ma w słowniku → KeyError w frontendzie.

11. **Marker-level `price_range` jest redundantny.** Każda oferta niesie własny `price_range`. NIE dodawaj go do markera (różne oferty pod tym samym adresem mogą być w różnych zakresach).

### 9.4. Geokodowanie

12. **Bez walidacji bbox Nominatim wraca z śmietnik.** `Narutowicza 5` bez `, Lublin, Poland` daje wyniki w Białymstoku, Warszawie itd. Walidacja bbox jest obowiązkowa.

13. **User-Agent Nominatim per-projekt.** OSM blokuje za nadużycia. Dla nowego projektu **zmień** `user_agent="sonar-pokojowy-lublin/1.0"` na np. `"sonar-mieszkaniowy-lublin/1.0"`.

14. **Cache zapisuje też negatywy** (None). To nie błąd — to zabezpieczenie przed retryowaniem niemożliwych do zgeokodowania adresów ("Tajemnicza ulica 999").

### 9.5. Środowisko / git

15. **`pip install --break-system-packages` w lokalnym środowisku** dla `pytz`, `python-Levenshtein`. W GitHub Actions (Ubuntu runner) nie jest potrzebne.

16. **PAT w remote URL:**
    ```bash
    git remote set-url origin https://[TOKEN]@github.com/USER/REPO.git
    ```

17. **Git config wymagany przed commitami:**
    ```bash
    git config user.email "..."
    git config user.name "..."
    ```

18. **Sekwencja konfliktów rebase:**
    ```bash
    git pull --rebase
    git checkout --theirs data/offers.json docs/data.json   # remote wygrywa
    cd src && python map_generator.py                       # regeneruj derived
    cd ..
    git add data/ docs/
    GIT_EDITOR=true git rebase --continue
    ```

19. **GitHub Actions API — workflow dispatch:**
    ```bash
    curl -X POST -H "Authorization: token $PAT" \
      "https://api.github.com/repos/USER/REPO/actions/workflows/scanner.yml/dispatches" \
      -d '{"ref":"main"}'
    ```

### 9.6. Frontend

20. **Spiral offset zaczyna się od 2. oferty** (`if (total === 1) return [baseLat, baseLon]`). Inaczej pojedyncze markery są przesunięte i nie zgadzają się z adresem.

21. **Toggle warstw uniwersytetów** używa `L.layerGroup()` + `map.addLayer/removeLayer` — NIE niszcz warstwy, tylko ją odpinaj. Inaczej tracisz state.

22. **`script.js` musi czytać `docs/data.json` z buster-em cache:**
    ```html
    <link rel="stylesheet" href="assets/style.css?v=2">
    ```
    GitHub Pages CDN cache ~10 min. Po zmianach incrementuj `v=N`.

---

## 10. Pierwsze uruchomienie nowego projektu (od zera)

### Krok 0 — Wymagania
- Python 3.11+
- Konto GitHub z włączonymi Pages + Actions
- Lokalny dostęp do GitHub przez PAT lub SSH

### Krok 1 — Klonowanie i setup

```bash
git clone https://github.com/[USER]/SONAR-MIESZKANIOWY.git
cd SONAR-MIESZKANIOWY
pip install -r requirements.txt
```

### Krok 2 — Lista podmian (CHECKLIST)

| # | Plik | Linia / fragment | Stara wartość | Nowa wartość |
|---|---|---|---|---|
| 1 | `src/scraper.py` | `BASE_URL` | OLX URL pokoi | **[INSERT_OLX_URL_HERE]** |
| 2 | `src/geocoder.py` | `Nominatim(user_agent=...)` | `sonar-pokojowy-lublin/1.0` | `sonar-mieszkaniowy-lublin/1.0` |
| 3 | `src/map_generator.py` | `PRICE_RANGES` | 0–1501+ co 100 zł | dostosować do mieszkań (np. 0–4000+ co 250 zł) |
| 4 | `README.md` | wszędzie | "POKOJOWY", "pokoi" | "MIESZKANIOWY", "mieszkań" |
| 5 | `docs/index.html` | `<title>`, `<h1>` | "Mapa pokoi Lublin" | "Mapa mieszkań Lublin" |
| 6 | `docs/analytics.html`, `monitoring.html`, `market_analysis.html` | tytuły, nagłówki | jw. | jw. |
| 7 | `.github/workflows/scanner.yml` | `name:` | `SONAR POKOJOWY Scanner` | `SONAR MIESZKANIOWY Scanner` |
| 8 | `src/api_generator.py` | `system: "sonar"` | (zostaje) | (zostaje — uniwersalne) |

> **Co NIE wymaga zmian (Lublin = ten sam region):**
> - `src/geocoder.py` `LUBLIN_BBOX` — jeśli zmieniasz miasto, dostosuj.
> - `src/address_parser.py` — uniwersalny.
> - Cron w workflow — 9:00/15:00/21:00 jest sensowne dla każdej kategorii.

### Krok 3 — Wyczyść dane testowe

```bash
echo '{"last_scan": null, "next_scan": null, "offers": []}' > data/offers.json
echo '{}' > data/geocoding_cache.json
echo '[]' > data/scan_history.json
echo '{}' > data/removed_listings.json
```

### Krok 4 — Test lokalny

```bash
cd src
python main.py                    # pełny skan (5–10 min)
python map_generator.py           # generuje docs/data.json
python api_generator.py           # generuje docs/api/*.json
cd ../docs
python -m http.server 8000        # http://localhost:8000
```

Otwórz mapę. Jeśli widzisz pinezki w Lublinie — działa.

### Krok 5 — GitHub Pages

`Settings → Pages → Source: Deploy from a branch → main → /docs → Save`

URL: `https://[USER].github.io/SONAR-MIESZKANIOWY/`

### Krok 6 — Pierwszy ręczny scan w Actions

`Actions → SONAR Scanner → Run workflow → main`

Pierwszy scan trwa ~10 min (cache geokodowania pusty). Następne ~5 min.

### Krok 7 — Weryfikacja produkcji

- `https://[USER].github.io/SONAR-MIESZKANIOWY/api/status.json` — powinien zwracać świeży scan.
- Mapa: pinezki kolorowe, popup z opisem, filtry działają.
- Monitoring: ostatni skan = success.

---

## 11. Roadmap (planowane Etapy A–E)

> Te etapy NIE są jeszcze zaimplementowane w SONAR-POKOJOWY. Dla nowego projektu można zacząć od MVP (kroki 1–7 z sekcji 10) i dodawać Etapy w miarę potrzeb.

| Etap | Funkcja | Trudność | Zależność |
|---|---|---|---|
| **A** | Powiadomienia email z filtrami (cena, dzielnica, słowa kluczowe) | średnia | SMTP / Brevo |
| **B** | Kategoryzacja + detekcja podejrzanych ofert + historia cen z wykresami | średnia | — |
| **C** | Heatmap cen + indeks wartości oferty + analiza trendów | wysoka | — |
| **D** | Filtry słów kluczowych + porównywanie ofert + ulubione (localStorage) | niska | — |
| **E** | Dodatkowe źródła (Otodom, Gratka), PWA push, panel admina | wysoka | nowe scrapery |
| **SZPERACZ** | Aplikacja Flutter/Android konsumująca `docs/api/` | średnia | mobile API |

---

## 12. FAQ implementacyjne

**Q: Czy mogę użyć Selenium/Playwright dla bardziej dynamicznych stron?**  
A: OLX renderuje listę server-side, więc requests + BS4 wystarczą. Jeśli celujesz w stronę typu Otodom (SPA), będzie potrzebne Playwright + zmiany w `_fetch_page()`. Architektura przyjmie to bez zmian w innych modułach.

**Q: Jak dodać nowe miasto?**  
A: Zmień `LUBLIN_BBOX` w `geocoder.py` na bbox nowego miasta + zaktualizuj `BASE_URL` (OLX ma URL per miasto). Reszta systemu jest agnostyczna.

**Q: Jak dodać drugą kategorię w tym samym projekcie?**  
A: NIE. Każda kategoria = osobne repo (osobne `data/offers.json`, osobne GitHub Pages). To celowa decyzja — łatwiejsza obsługa, brak konfliktów w price_ranges.

**Q: Limit GitHub Actions?**  
A: Free tier: 2000 min/miesiąc dla repo prywatnych. Public repo = unlimited. Skan ~5 min × 3/dzień × 30 = 450 min/miesiąc — z dużym zapasem.

**Q: Limit GitHub Pages?**  
A: 1 GB repo, 100 GB transferu/miesiąc, 10 buildów/godz. `docs/data.json` ~500 KB → bez problemu nawet przy intensywnym ruchu.

**Q: Co jeśli OLX zmieni HTML?**  
A: Krytyczne selektory są w `_extract_offers_from_page()` (klasy/data-testid) i parserze JSON-LD. Monitoring (success rate < 50%) sygnalizuje problem. Plan B: fallback selektory już są zaimplementowane (`h6 || h4 || h3`).

---

## 13. Inwentarz funkcji obecnie działających w SONAR-POKOJOWY

Lista do zaimportowania 1:1 (każda funkcja jest gotowa i przetestowana):

- ✅ Scraping z paginacją (max 50 stron) + wątki (5 workerów)
- ✅ Inteligentne pomijanie ofert bez zmiany ceny (~70% mniej requestów)
- ✅ Parsowanie JSON-LD (cena, availability)
- ✅ Regex adresów (ulice + polskie nazwiska w dopełniaczu)
- ✅ Geokodowanie z cache + walidacją bbox
- ✅ Wykrywanie duplikatów (Levenshtein 95%)
- ✅ Reaktywacja ofert (ofera "wraca do żywych" jeśli znów widoczna na OLX)
- ✅ HTTP 410 handling
- ✅ Tagowanie ofert (pokoj/mieszkanie/kawalerka — `offer_tagger.py`)
- ✅ Mapa Leaflet z 12-stopniowym gradientem cen
- ✅ Spiral offset dla nakładających się markerów
- ✅ Suwak filtra dat dodania
- ✅ Filtr aktywne/nieaktywne
- ✅ Wyszukiwarka po adresie
- ✅ Warstwy uniwersytetów (UMCS, KUL, PL, UM)
- ✅ Historia cen z trendem (up/down)
- ✅ Dashboard analityki (Chart.js)
- ✅ Dashboard monitoringu (success rate, czasy)
- ✅ Lifespan / survival curve ofert
- ✅ Statyczne API dla aplikacji mobilnej (3 endpointy)
- ✅ Czarna lista oferty (`removed_listings.json`)

---

## 14. Wnioski końcowe

System jest **świadomie minimalistyczny**: brak bazy danych, brak backend serwera, brak buildów frontendowych. To zaleta — działa zerowym kosztem na infrastrukturze GitHub i jest deterministyczny (każdy commit reproducible).

Kluczowy insight z 6 miesięcy iteracji: **frontend działa tym lepiej, im więcej logiki przesuniesz do backendu (Python).** Dane już zformatowane (Polski format daty, `price_range` na poziomie oferty, `is_new` obliczone przy generowaniu) eliminują 90% błędów w JS.

Drugi insight: **zawsze rozdzielaj źródło prawdy (`data/offers.json`) od warstwy widoku (`docs/data.json`).** Pozwala to przebudowywać format frontendu bez ruszania backendu i odwrotnie.

---

**Wersja blueprintu:** 1.0  
**Data:** 28.04.2026  
**Repo źródłowe:** github.com/Bonaventura-EW/SONAR-POKOJOWY  
**Status SONAR-POKOJOWY:** produkcyjny, 3 skany dziennie, ~150 aktywnych ofert
