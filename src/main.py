"""
SONAR MIESZKANIOWY - Główny agent
Koordynuje: scraping → parsowanie → geokodowanie → wykrywanie duplikatów → zapis
WERSJA 2.0: Równoległy scraping + monitoring
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta, date
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
from street_whitelist import (is_district_name, is_known_place, is_known_street,
                              is_street_name, name_variants)
from address_migration import (ADDRESS_PARSER_VERSION, drop_rejected_labels,
                               retract_fake_numbers, upgrade_junk_streets)
from clean_geocoding_cache import (find_junk_keys, find_street_level_number_keys,
                                   street_forms)

# Jawny prefiks ulicy w tytule — wraz z whitelistą OSM decyduje, czy adres
# z tytułu jest na tyle pewny, żeby wyprzedzić adres z treści ogłoszenia.
TITLE_STREET_PREFIX_RE = re.compile(
    r'\b(ul\.?|ulica|ulicy|ulicą|al\.?|aleja|aleje|alei|pl\.?|plac|placu|os\.?|osiedle|osiedlu)\s',
    re.IGNORECASE)

# Stabilny identyfikator oferty (CID3-IDxxxx). Współdzielony z scraper.py.
from cid import extract_cid
from offer_tagger import build_tags, title_from_url
from atomic_json import atomic_write_json
import reactivation_log
import paths


class SonarMieszkaniowy:
    # Ochrona przed masową dezaktywacją: scrape musi zwrócić co najmniej
    # 60% wcześniejszej liczby aktywnych ofert, inaczej nie dezaktywujemy.
    #
    # FIX 2026-08-05: podniesione z 0.3 → 0.6. Zdrowy skan zwraca ~770 ofert
    # przy ~710 aktywnych (ratio ~1.08), więc próg 0.3 (≈212) łapał tylko
    # DRASTYCZNE blokady (0/42/93 oferty). Częściowa blokada zwracająca ~połowę
    # ofert (realny incydent 2026-08-05 06:31: 365 przy 706 aktywnych, ratio
    # 0.52) prześlizgiwała się pod progiem i dezaktywowała 409 realnych ofert
    # (aktywne 706 → 349). Próg 0.6 (≈424) łapie taki przypadek, mając wciąż
    # ogromny margines do zdrowego ratio ~1.08 (zero fałszywych trafień na
    # historycznych zdrowych skanach). Blokada → skan czeka i ponawia próbę
    # (run_scan_with_retry), a dezaktywacja pozostaje pominięta.
    MIN_DEACTIVATION_RATIO = 0.6

    # FIX 2026-08-05: retry przy wykrytej blokadzie OLX/Cloudflare. Gdy scraper
    # zwróci 0 / podejrzanie mało ofert (patrz _deactivation_block_reason),
    # skan czeka RETRY_ON_BLOCK_WAIT_SECONDS i próbuje ponownie, aż do
    # RETRY_ON_BLOCK_MAX_RETRIES dodatkowych prób. Blokada bywa chwilowa
    # (rate limit), a pełny cykl to tylko 3×/dzień — jeden strzał po 2 min
    # ratuje skan, zamiast czekać ~5 h na następny harmonogram.
    RETRY_ON_BLOCK_WAIT_SECONDS = 120
    RETRY_ON_BLOCK_MAX_RETRIES = 2

    # FIX 2026-08-06: bezpiecznik przed regresją parsera adresów.
    # Oferta bez rozpoznanego adresu jest wyrzucana ze skanu (`_process_offer`
    # → None), więc każde zaostrzenie parsera grozi cichym zniknięciem setek
    # ogłoszeń ze strony. Zdrowy skan gubi tak ~5,5% ofert (42 z 767).
    # Przekroczenie progu logujemy jako błąd skanu → monitoring pokazuje ⚠️,
    # zamiast raportować „✅ sukces" przy wyciętej połowie bazy.
    MAX_NO_ADDRESS_RATIO = 0.20

    # FIX 2026-08-12: dezaktywacja oparta na REALNYM stanie oferty, nie na
    # jednorazowej nieobecności w listingu.
    #
    # Problem: listing OLX jest niestabilny — pojedynczy scrape gubi losowe
    # ~7–10% żywych ofert (zestaw rotuje, przerwy <24 h). Stary kod dezaktywował
    # na PIERWSZYM chybieniu, a potem weryfikacja cofała ~48/50 z tych „zniknięć"
    # (zmierzone 8–11.08). To był churn: oferta migała inactive↔active co skan,
    # zatruwając historię reaktywacji i wykres odpływu.
    #
    # Teraz: oferta nieobecna w listingu dostaje +1 do licznika chybień; dopiero
    # po MISSING_STREAK_THRESHOLD kolejnych chybieniach sprawdzamy jej link
    # BEZPOŚREDNIO i dezaktywujemy tylko gdy OLX potwierdzi zniknięcie (404/410
    # lub brak „InStock"). Próg 2 wycina ~99% szumu paginacji za zero requestów.
    MISSING_STREAK_THRESHOLD = 2
    # Sufit sprawdzeń linków na skan (po filtrze streaka kandydatów jest mało;
    # limit chroni OLX na wypadek nietypowego skanu z lawiną chybień).
    MAX_LINK_CHECKS = 60
    # FIX 2026-09-02: sufit nieobecności. Sprawdzenie linku było JEDYNYM wyjściem
    # z puli aktywnych, a mieści się w nim MAX_LINK_CHECKS ofert na skan — przy
    # ~20 nowych ofertach na skan i ~7 potwierdzonych zniknięciach kolejka
    # `verification.candidates` rosła 3 → 254 (10.08 → 02.09), a liczba
    # „aktywnych" 694 → 1019 przy PŁASKIM listingu (~770 ofert/skan). Skan
    # przechodzi CAŁY listing 3×/dzień, więc ogłoszenie nieobecne we wszystkich
    # skanach przez tyle dni nie jest już na OLX — dezaktywujemy bez czekania
    # na swoją kolej w kolejce linków. Ochrona przed masową dezaktywacją
    # (`_deactivation_block_reason`) obejmuje ten krok tak samo jak weryfikację.
    MAX_MISSING_DAYS = 3
    # Circuit breaker: tyle błędów sprawdzenia linku z rzędu (403/sieć) i
    # przerywamy krok — IP prawdopodobnie zdławione. Błąd ≠ śmierć oferty, więc
    # nic na jego podstawie nie dezaktywujemy; przerwanie chroni przed biciem
    # w mur i pogłębianiem limitu (to był mechanizm 50/50 błędów z 22:45).
    LINK_CHECK_ERROR_CIRCUIT = 5

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
        """Oblicza czas następnego scanu (9:17, 15:17 lub 21:17).

        FIX 2026-06-12: cron działa o :17 (off-peak, zmiana 2026-05-25), a ta
        funkcja wciąż liczyła pełne godziny — frontend pokazywał "następny skan"
        zaniżony o 17 minut.
        """
        now = datetime.now(self.tz)
        scan_hours = [9, 15, 21]
        scan_minute = 17  # musi odpowiadać cronowi w .github/workflows/scanner.yml

        for hour in scan_hours:
            next_time = now.replace(hour=hour, minute=scan_minute, second=0, microsecond=0)
            if next_time > now:
                return next_time.isoformat()

        # Jeśli po ostatnim skanie dnia, to następny scan rano następnego dnia
        tomorrow = now + timedelta(days=1)
        next_time = tomorrow.replace(hour=scan_hours[0], minute=scan_minute, second=0, microsecond=0)
        return next_time.isoformat()
    
    @staticmethod
    def _address_precision(has_number: bool, coords: Dict, geocode_meta: Dict = None) -> str:
        """Jak dokładny jest punkt na mapie — 'exact' | 'street' | 'none'.

        FIX 2026-08-06: mapa rysowała kroplę „adres dokładny" po samym `has_number`,
        więc oferta z numerem, dla której geokoder cofnął się do samej ulicy
        (`meta['number_fallback']`), udawała precyzję, której nie ma.

        - 'exact'  — geokod trafił w konkretny budynek,
        - 'street' — znamy tylko ulicę (brak numeru albo fallback geokodera),
        - 'none'   — brak współrzędnych, oferta idzie do warstwy „bez lokacji".
        """
        if not coords:
            return 'none'
        if not has_number:
            return 'street'
        if geocode_meta and geocode_meta.get('number_fallback'):
            return 'street'
        return 'exact'

    def _migrate_legacy_addresses(self):
        """Jednorazowo przelicza adresy w bazie po zmianie parsera (bez sieci).

        FIX 2026-08-06: poprawka „numer musi sąsiadować z ulicą" działa dla nowych
        parsowań, a `_update_existing_offer` naprawia oferty, które scraper widzi
        w listingu. Oferty **nieaktywne** nie są odwiedzane, więc zostałyby ze
        zmyślonym numerem na zawsze (84 sztuki na 2026-08-06) — a wchodzą do mapy
        historycznej i do analiz cen po adresach. Opis mamy w bazie, więc adres
        przeliczamy z zapisanego tekstu.

        Migracja odpala się raz — dopóki `address_parser_version` w bazie nie
        zgadza się z `ADDRESS_PARSER_VERSION`. Bezpiecznik przed awarią parsera
        siedzi w `retract_fake_numbers` (patrz MAX_RETRACTION_RATIO).
        """
        if self.database.get('address_parser_version') == ADDRESS_PARSER_VERSION:
            return
        print(f"\n🔧 Migracja adresów do wersji parsera {ADDRESS_PARSER_VERSION}…")
        result = retract_fake_numbers(
            self.database['offers'],
            parser=self.address_parser,
            geocoding_cache=self.geocoder.cache,
        )
        if result['blocked']:
            print(f"   ⛔ {result['blocked']}")
            self.scan_logger.log_error(result['blocked'])
            return
        print(f"   ✅ Wycofano zmyślony numer w {result['to_fix']} ofertach "
              f"(aktywne: {result['active_to_fix']}, nieaktywne: {result['inactive_to_fix']}); "
              f"bez zmian: {result['kept']}")

        # FIX 2026-08-08: druga część migracji — śmieciowa etykieta na realną ulicę.
        # Dotyczy wyłącznie ofert BEZ współrzędnych, więc nie może przesunąć pinezki.
        upgrade = upgrade_junk_streets(
            self.database['offers'],
            parser=self.address_parser,
            geocoding_cache=self.geocoder.cache,
        )
        print(f"   ✅ Śmieciowa etykieta → realna ulica w {upgrade['to_fix']} ofertach "
              f"(aktywne: {upgrade['active_to_fix']}, nieaktywne: {upgrade['inactive_to_fix']}); "
              f"pinezkę z cache zyskało: {upgrade['gained_coords']}")

        # FIX 2026-08-10: trzecia część — etykieta, której parser już nie uznaje
        # za adres („Wolne", „Miejsca", „przytulna kawalerka"), schodzi z mapy.
        # `_update_existing_offer` umie adres tylko poprawić, nigdy skasować.
        dropped = drop_rejected_labels(
            self.database['offers'], parser=self.address_parser)
        if dropped['blocked']:
            print(f"   ⛔ {dropped['blocked']}")
            self.scan_logger.log_error(dropped['blocked'])
        else:
            print(f"   ✅ Zdjęto nieadresową etykietę z {dropped['to_fix']} ofert "
                  f"(aktywne: {dropped['active_to_fix']}, "
                  f"nieaktywne: {dropped['inactive_to_fix']})")

        self.database['address_parser_version'] = ADDRESS_PARSER_VERSION

    @staticmethod
    def _is_area_not_address(label: str) -> bool:
        """Czy etykieta opisuje OBSZAR (albo śmieć), a nie adres uliczny.

        FIX 2026-08-08: takie oferty nie dostają pinezki — idą do warstwy
        „bez lokacji". Warunek jest złożony, bo każdy pojedynczy test miał
        zmierzone fałszywe trafienia:
          - `is_street_name` musi znać formy odmienione PO STRONIE INDEKSU,
            inaczej „Racławickiej" (= Aleje Racławickie) wypada jako nie-ulica,
          - `is_district_name` po podciągu robiło z ulic dzielnice
            („Nałęczowska" ⊂ nazwy osiedla) — stąd dopasowanie pełne,
          - `is_known_place` też musi być pełne: dopasowanie po podciągu
            (`is_known_street`) chroniło nawet śmieć „Nowe", bo taki człon ma
            „Nowe Sady".
        Zdejmujemy więc pinezkę tylko wtedy, gdy nazwa NIE jest ulicą i jest
        albo znaną dzielnicą/osiedlem, albo w ogóle nie ma jej w whiteliście.
        Etykiety typu „Sekutowicza Mieszkanie" ratuje `_salvage_street_label`
        w `_demote_non_street_pins` — obcina ogon i zostawia pinezkę.
        """
        if not label or is_street_name(label):
            return False
        return is_district_name(label) or not is_known_place(label)

    def _demote_non_street_pins(self):
        """Zdejmuje z mapy pinezki, których adres nie jest ulicą (FIX 2026-08-08).

        Nazwy osiedli („Botanik", „Piastowskie", „Skarpa"), instytucji
        („Uniwersytetu Medycznego") i resztek po parserze („Wolne", „Miejsca",
        „Stokrotka") dostawały punkt gdzieś w tej okolicy i na mapie wyglądały
        jak normalny adres. Trafiają teraz do warstwy „bez lokacji" — oferta
        zostaje na stronie, ale nie udaje, że wiadomo, gdzie stoi.

        Kolejność ma znaczenie: najpierw próbujemy sprzątnąć etykietę
        („Obywatelska piętro" → „Obywatelska"), bo to ratuje pinezkę; dopiero
        gdy nic z niej nie zostaje, oferta traci punkt. Bez sieci, idempotentne.
        """
        cleaned = demoted = 0
        for offer in self.database['offers']:
            addr = offer.get('address')
            if not isinstance(addr, dict) or not addr.get('coords'):
                continue
            label = addr.get('street') or addr.get('full') or ''
            if not self._is_area_not_address(label):
                continue
            salvaged = self._salvage_street_label(addr.get('full') or '')
            if salvaged and is_street_name(salvaged):
                addr.update({'full': salvaged, 'street': salvaged, 'number': None,
                             'has_number': False, 'precision': 'street'})
                cleaned += 1
                continue
            addr.pop('coords', None)
            addr['precision'] = 'none'
            demoted += 1
        if cleaned:
            print(f"   🧹 Sprzątnięto etykietę (pinezka została): {cleaned}")
        if demoted:
            print(f"   📤 Zdjęto z mapy (adres nie jest ulicą): {demoted}")

    def _clean_geocoding_cache(self):
        """Wyrzuca z cache klucze-śmieci, które udają nazwy ulic (FIX 2026-08-07).

        `AddressParser` buduje whitelistę `_known_streets` z kluczy tego cache'u,
        więc każdy zgeokodowany śmieć („pod nr 60", „Duze nowoczesne 2") staje się
        „znaną ulicą" i uwiarygadnia kolejne takie parsowania — pętla sprzężenia
        zwrotnego. Usuwamy wyłącznie klucze, których nie używa ŻADNA oferta i które
        nie odpowiadają realnej ulicy Lublina, więc operacja nie rusza pinezek.
        Idempotentna: po pierwszym przebiegu nie ma już czego usuwać.
        """
        junk = find_junk_keys(self.geocoder.cache, self.database['offers'], street_forms())
        if not junk:
            return
        for key in junk:
            self.geocoder.cache.pop(key, None)
        self.geocoder._save_cache()
        print(f"   🗑️  Usunięto {len(junk)} śmieciowych kluczy z cache geokodera")

    def _downgrade_street_level_pins(self):
        """Adres z numerem, który stoi na punkcie SAMEJ ulicy, przestaje udawać
        adres dokładny (FIX 2026-08-08).

        Nominatim na numer, którego nie ma w OSM, potrafi oddać punkt
        reprezentatywny ulicy i zaraportować to jako trafienie — „Lubomelskiej 9"
        lądowało tak 142 m od celu, na ul. Bocznej Lubomelskiej, z kroplą „adres
        dokładny". Świeże geokodowania łapie teraz `Geocoder._number_confirmed`;
        tutaj domykamy to, co już siedzi w bazie i w cache.

        Pinezka NIE znika i się nie przesuwa — zmienia się wyłącznie `precision`
        ('exact' → 'street'), czyli kształt markera: kwadrat „przybliżony" zamiast
        kropli. Klucz z numerem znika z cache, żeby kolejne geokodowanie przeszło
        już przez walidację (i mogło trafić w budynek, gdy OSM się uzupełni).
        Bez sieci, idempotentne.
        """
        pairs = find_street_level_number_keys(self.geocoder.cache)
        if not pairs:
            return
        street_level = {key for key, _ in pairs}
        downgraded = 0
        for offer in self.database['offers']:
            addr = offer.get('address')
            if not isinstance(addr, dict) or not addr.get('coords'):
                continue
            if addr.get('precision') == 'exact' and (addr.get('full') or '').strip() in street_level:
                addr['precision'] = 'street'
                downgraded += 1
        for key in street_level:
            self.geocoder.cache.pop(key, None)
        self.geocoder._save_cache()
        print(f"   📐 Adres z numerem na punkcie ulicy: {len(pairs)} kluczy cache usuniętych, "
              f"{downgraded} ofert z 'exact' → 'street'")

    # Ile przykładów per kategoria trafia do zakładki debugowej.
    MAP_GAP_SAMPLE_LIMIT = 25

    def _classify_map_gap(self, address: dict) -> str:
        """Dlaczego ta oferta nie ma pinezki — jedna z czterech przyczyn.

        FIX 2026-08-09: zakładka debugowa obiecywała „oferty, które nie trafiły
        na mapę", a pokazywała wyłącznie te, którym parser nie znalazł ULICY
        (28 z 111). Reszta — etykieta nie do odczytania, nazwa obszaru zamiast
        punktu, brak geokodu — nie była nigdzie policzona, bo współrzędne
        zdejmują im kroki uruchamiane PO pętli skanu (`_demote_non_street_pins`).
        """
        label = (address.get('street') or address.get('full') or '').strip()
        if not label:
            return 'no_address'
        if is_street_name(label):
            return 'no_coords'
        if is_district_name(label) or is_known_place(label):
            return 'area_only'
        return 'not_a_street'

    def _write_map_gap_breakdown(self):
        """Dopisuje do `skipped_offers_sample.json` bilans „dlaczego nie na mapie".

        Liczone z KOŃCOWEGO stanu bazy, nie z liczników pętli — tylko wtedy suma
        się domyka, bo część ofert traci współrzędne dopiero w krokach
        porządkowych po skanie. Dzięki temu na stronie da się sprawdzić
        rachunek: aktywne = na mapie + suma kategorii.
        """
        active = [o for o in self.database['offers'] if o.get('active')]
        counts = {'no_address': 0, 'not_a_street': 0, 'area_only': 0, 'no_coords': 0}
        samples = {key: [] for key in counts}
        precision = {'exact': 0, 'street': 0, 'none': 0}
        on_map = 0

        for offer in active:
            address = offer.get('address') if isinstance(offer.get('address'), dict) else {}
            precision[address.get('precision') if address.get('precision') in precision else 'none'] += 1
            if address.get('coords'):
                on_map += 1
                continue
            category = self._classify_map_gap(address)
            counts[category] += 1
            if len(samples[category]) < self.MAP_GAP_SAMPLE_LIMIT:
                samples[category].append({
                    'url': offer.get('url', ''),
                    # Oferty w bazie nie mają pola `title` — czytelną nazwę
                    # odtwarzamy ze slugu URL, tak samo jak `map_generator`.
                    'title': title_from_url(offer.get('url', '')),
                    'description_preview': (offer.get('description') or '')[:500],
                    'address_parsed': address.get('full') or None,
                })

        payload = {
            'active': len(active),
            'on_map': on_map,
            'off_map': len(active) - on_map,
            'counts': counts,
            'precision': precision,
            'samples': samples,
        }
        # FIX 2026-08-09: ta sama liczba idzie do monitoringu (`log_stats` →
        # `map_quality`), żeby jakość mapy dało się śledzić w czasie zamiast
        # liczyć ją doraźnym skryptem po każdej zmianie parsera czy geokodera.
        self.map_quality_stats = {k: v for k, v in payload.items() if k != 'samples'}

        samples_path = self.data_file.parent / 'skipped_offers_sample.json'
        try:
            existing = json.loads(samples_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            existing = {'scan_timestamp': datetime.now(self.tz).isoformat(),
                        'counts': {}, 'samples': {}}
        existing['map_gap'] = payload
        atomic_write_json(str(samples_path), existing)
        print(f"   📊 Bilans mapy: aktywnych {payload['active']} = na mapie {on_map} "
              f"+ bez pinezki {payload['off_map']} "
              f"({', '.join(f'{k}: {v}' for k, v in counts.items() if v)})")

    def _backfill_address_precision(self):
        """Uzupełnia `precision` w ofertach sprzed FIX-a 2026-08-06 — bez sieci.

        Oferty z bazy nie mają meta z geokodera (a ich coords są reużywane, więc
        geokoder się dla nich nie odpala i nigdy by go nie dostały). Rozpoznajemy
        fallback „sama ulica" porównując zapisane coords z geokodem samej nazwy
        ulicy w `geocoding_cache.json`: identyczny punkt = to jest środek ulicy,
        nie budynek. Audyt z 2026-08-06 znalazł tak 21 aktywnych ofert.
        """
        cache = {k.strip().lower(): v for k, v in self.geocoder.cache.items() if v}
        updated = 0
        for offer in self.database['offers']:
            addr = offer.get('address') or {}
            if not isinstance(addr, dict):
                continue
            # FIX 2026-08-07: 'none' przy istniejących współrzędnych to niespójność
            # (oferta dostała punkt, ale precyzja została z czasów bez GPS) — taki
            # rekord przeliczamy ponownie, mimo że pole `precision` już jest.
            inconsistent = addr.get('precision') == 'none' and addr.get('coords')
            if addr.get('precision') and not inconsistent:
                continue
            coords = addr.get('coords')
            has_number = bool(addr.get('number'))
            precision = self._address_precision(has_number, coords)
            if precision == 'exact':
                street_keys = {
                    (addr.get('street') or '').strip().lower(),
                    re.sub(r'\s+\S+$', '', addr.get('full') or '').strip().lower(),
                }
                for key in street_keys:
                    street_coords = cache.get(key)
                    if not street_coords:
                        continue
                    same_point = (abs(street_coords['lat'] - coords['lat']) < 5e-5 and
                                  abs(street_coords['lon'] - coords['lon']) < 5e-5)
                    if same_point:
                        precision = 'street'
                        break
            addr['has_number'] = has_number   # domyka niespójność has_number=True/number=None
            addr['precision'] = precision
            updated += 1
        if updated:
            print(f"   🎯 Uzupełniono precyzję adresu dla {updated} ofert")

    def _backfill_promoted_from_url(self):
        """Uzupełnia flagę `promoted` ofertom sprzed wdrożenia detekcji — bez sieci.

        Sygnał wyróżnienia jest już w bazie: pełny URL oferty z parametrem
        atrybucji OLX (`search_reason=search|promoted`) zapisujemy od dawna, więc
        stan „promowana teraz" da się odtworzyć bez czekania na kolejny skan.
        Dla ofert bez pola `promoted` odczytujemy je z URL-a
        (`OLXScraper._is_promoted_href`). Aktywnym, aktualnie wyróżnionym ofertom
        dokładamy dzisiejszą datę do `promoted_dates`, żeby wykres miał pierwszy
        punkt od razu — głębiej wstecz wyróżnień NIE DA SIĘ odtworzyć (to stan
        chwilowy na listingu, nie ślad w ofercie), więc seedujemy tylko „dziś".
        Idempotentne: rusza tylko dla ofert bez pola `promoted`.
        """
        today = datetime.now(self.tz).strftime('%Y-%m-%d')
        filled = 0
        for offer in self.database['offers']:
            if 'promoted' in offer:
                continue
            promoted = bool(offer.get('active')
                            and OLXScraper._is_promoted_href(offer.get('url', '')))
            offer['promoted'] = promoted
            dates = offer.setdefault('promoted_dates', [])
            if promoted and today not in dates:
                dates.append(today)
            offer['promoted_count'] = len(dates)
            filled += 1
        if filled:
            print(f"   ⭐ Backfill promowanych: uzupełniono {filled} ofert z URL-a")

    def _address_from_title(self, raw_offer: Dict, full_text: str):
        """Adres z TYTUŁU ogłoszenia — pierwszeństwo przed treścią (2026-08-06).

        Tytuł to najpewniejsze miejsce na adres: jest krótki, pisany świadomie
        („Cyrkoniowa 7 - kawalerka do wynajęcia") i nie ma w nim zdań, z których
        parser potrafi skleić pseudo-adres. Wcześniej tytuł był po prostu doklejany
        do opisu (`full_text`), więc nie miał żadnego priorytetu, a filtry chroniące
        przed śmieciami z opisu potrafiły skasować poprawny adres z tytułu.

        Wynik z tytułu przyjmujemy tylko, gdy jest wiarygodny: nazwa musi być realną
        ulicą/osiedlem Lublina (whitelist OSM) i mieć numer albo jawny prefiks
        („ul.", „al.", „os."). Bez tego warunku tytuły typu „Nowoczesne mieszkanie…"
        podstawiałyby śmieci w miejsce dobrego adresu z opisu.

        Gdy tytuł podaje samą ulicę, numer dobieramy z treści — ale wyłącznie dla
        TEJ SAMEJ ulicy (porównanie odporne na odmianę: „ul. Głęboka" w tytule +
        „Głębokiej 21" w opisie → „Głęboka 21”).

        Zwraca `address_data` albo None (wtedy caller idzie starą ścieżką).
        """
        title = (raw_offer.get('title') or '').strip()
        if not title:
            return None
        candidate = self.address_parser.extract_address(title)
        if not candidate:
            return None
        street = candidate.get('street') or candidate.get('full') or ''
        if not is_known_street(street):
            return None
        if not candidate.get('has_number') and not TITLE_STREET_PREFIX_RE.search(title):
            return None

        candidate = self._trim_leading_junk(candidate)

        if not candidate.get('has_number'):
            from_body = self.address_parser.extract_address(full_text)
            if from_body and from_body.get('has_number') and self._same_street(from_body, candidate):
                print(f"      🏷️  Adres z tytułu + numer z treści: {from_body['full']}")
                return from_body
        print(f"      🏷️  Adres z tytułu: {candidate['full']}")
        return candidate

    @staticmethod
    def _trim_leading_junk(candidate: Dict) -> Dict:
        """Ucina reklamowy przedrostek sprzed nazwy ulicy („BEZPOŚREDNIO Nałęczowska 20").

        `EXCLUDED_WORDS` w parserze obcina śmieci tylko z KOŃCA nazwy, a tytuły
        ogłoszeń lubią zaczynać się od zawołania pisanego wielką literą, które
        wygląda dla regexu jak pierwszy człon nazwy ulicy. Obcinamy wyłącznie
        wtedy, gdy ogon nazwy jest realną ulicą Lublina, a początek nie jest —
        więc „Krakowskie Przedmieście" czy „Jana Sawy" zostają nietknięte.
        """
        street = candidate.get('street') or ''
        tokens = street.split()
        full = candidate.get('full') or ''
        # Przy zmapowanym prefiksie ("Aleja …", "Plac …") parser już rozdzielił
        # nazwę poprawnie — nie ruszamy.
        if len(tokens) < 2 or not full.startswith(street) or is_known_street(tokens[0]):
            return candidate
        for start in range(1, len(tokens)):
            tail = ' '.join(tokens[start:])
            if is_known_street(tail):
                trimmed = dict(candidate)
                trimmed['street'] = tail
                trimmed['full'] = f"{tail} {candidate['number']}" if candidate.get('number') else tail
                print(f"      ✂️  Obcięto przedrostek z tytułu: '{full}' → '{trimmed['full']}'")
                return trimmed
        return candidate

    @staticmethod
    def _salvage_street_label(label: str):
        """Wyłuskuje realną ulicę z zaśmieconej etykiety adresu (FIX 2026-08-07).

        Ostatnia szansa dla ofert, których geokoder nie potrafił umiejscowić, bo do
        nazwy ulicy dokleiło się pół zdania: „PeowiakówZdjęcia są" → „Peowiaków",
        „Piłsudskiego Okna" → „Piłsudskiego", „Obywatelska piętro 10" → „Obywatelska".
        Obcinamy człony od KOŃCA, aż zostanie nazwa z whitelisty OSM — czyli nigdy
        nie zgadujemy, tylko potwierdzamy istniejącą ulicę.

        Uruchamiane wyłącznie dla ofert BEZ współrzędnych, więc nie może przesunąć
        żadnej istniejącej pinezki. Zwraca nazwę ulicy albo None.
        """
        if not label or is_street_name(label) or is_district_name(label):
            # Cała etykieta jest już nazwą ulicy albo dzielnicy — nie ma czego
            # ucinać, a skracanie tylko by ją zepsuło („Osiedle Klemensa Junoszy"
            # → „Osiedle Klemensa"). FIX 2026-08-08: kryterium to lista ULIC,
            # nie szeroka whitelist — ta ostatnia dopasowuje po podciągu, więc
            # „Sekutowicza Mieszkanie" uchodziło za nazwę kompletną i śmieć
            # zostawał doklejony na zawsze.
            return None
        # Rozklej sklejone tokeny („PeowiakówZdjęcia" → „Peowiaków Zdjęcia")
        spaced = re.sub(r'([a-ząćęłńóśźż])([A-ZŚĆŁĄĘÓŻŹŃ])', r'\1 \2', label)
        tokens = spaced.split()
        for end in range(len(tokens), 0, -1):
            candidate = ' '.join(tokens[:end])
            # Jednoczłonowe nazwy bywają fałszywym trafieniem whitelisty
            # („Residence" ⊂ „Wikana Residence"), więc wymagamy wielkiej litery
            # i długości typowej dla nazwy ulicy.
            if candidate == label or len(candidate) < 5 or not candidate[0].isupper():
                continue
            if is_street_name(candidate):
                return candidate
        return None

    @staticmethod
    def _same_street(first: Dict, second: Dict) -> bool:
        """Czy dwa parsowania wskazują tę samą ulicę (odporne na odmianę i skróty)."""
        variants_first = name_variants(first.get('street') or first.get('full') or '')
        variants_second = name_variants(second.get('street') or second.get('full') or '')
        return bool(variants_first & variants_second)

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
        
        # 2. Parsuj adres: NAJPIERW TYTUŁ, potem treść ogłoszenia.
        # FIX 2026-08-06: tytuł ma pierwszeństwo (patrz `_address_from_title`).
        # Pomiar na 703 aktywnych ofertach: 22 adresy lepsze, 2 gorsze, reszta bez zmian.
        address_data = self._address_from_title(raw_offer, full_text)

        # Tytuł nie dał wiarygodnego adresu → cały tekst (tytuł + opis)
        if not address_data:
            address_data = self.address_parser.extract_address(full_text)

        # Dalej nic → sam opis
        if not address_data and raw_offer.get('description'):
            print(f"      🔍 Brak adresu w tytule, szukam w opisie...")
            address_data = self.address_parser.extract_address(raw_offer['description'])
        
        # FIX 2026-08-06: RATUNEK — sama ulica bez numeru.
        # Parser potrafi znać ulicę (`extract_street_only`), a mimo to oferta leciała
        # do kosza — main.py wypisywał nawet w logu „extract_street_only znalazłby: X".
        # Lepsza jest pinezka na poziomie ulicy (kwadrat) niż brak oferty na stronie.
        if not address_data:
            candidate = self.address_parser.extract_street_only(full_text)
            if candidate and is_known_street(candidate.get('street') or candidate.get('full', '')):
                print(f"      🛟 Adres odzyskany jako sama ulica: {candidate['full']}")
                address_data = candidate

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
        
        # FIX 2026-08-07: brak adresu NIE kasuje już oferty.
        # Wcześniej `return None` sprawiał, że ~34 ogłoszenia na skan znikały ze
        # strony bez śladu — a to normalne oferty, tyle że sprzedawca nie podał
        # w treści żadnej ulicy. Teraz zostają z pustym adresem: mapa pokazuje je
        # w warstwie „bez lokacji", a zakładka debugowa (skipped_debug.html) ma
        # je w sekcji „brak adresu", więc regresje parsera dalej widać jak na dłoni.
        if not address_data:
            address_data = {'full': '', 'street': '', 'number': None, 'has_number': False}
        
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
        # FIX 2026-08-06: geokoder od dawna raportuje w meta `number_fallback` („nie
        # znalazłem numeru, zwracam samą ulicę"), ale main.py tę informację wyrzucał.
        # Bez niej mapa rysowała kroplę „adres dokładny" także dla punktów, które są
        # w rzeczywistości środkiem ulicy. Zapisujemy ją jako address['precision'].
        geocode_meta = None
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
            # FIX 2026-08-07: pusty adres nie może „pasować" do pustego adresu innej
            # oferty — inaczej ogłoszenie bez ulicy odziedziczyłoby cudze współrzędne.
            if (existing and existing.get('coordinates') and address_data['full']
                    and existing.get('address_full') == address_data['full']):
                reused_coords = existing['coordinates']
            
            if reused_coords:
                coords = reused_coords
                # Skipowy log - bez print, żeby nie zaśmiecać outputu (470x ten sam log)
                # final_* używamy z address_data bo cache hit oznacza ten sam adres co main
                final_street = address_data.get('street', '')
                final_number = address_data.get('number')
                final_full = address_data['full']
                # FIX 2026-08-08: skoro reużywamy punktu, to geokoder NIE ruszał —
                # nie mamy więc żadnej nowej wiedzy o tym, czy trafia w budynek.
                # Bez tego `_address_precision` liczyło precyzję od zera i każda
                # reużyta oferta z numerem wracała jako 'exact', kasując uczciwe
                # 'street' ustawione wcześniej (fallback „sama ulica").
                previous_precision = (existing.get('address') or {}).get('precision')
                if previous_precision in ('street', 'none'):
                    geocode_meta = {'number_fallback': True}
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
                    geocode_meta = used_address.get('meta')
                else:
                    coords = None
                    final_street = address_data.get('street', '')
                    final_number = address_data.get('number')
                    final_full = address_data['full']
                    print(f"⚠️ Nie można geokodować: {final_full} (próbowano też {len(address_data.get('alternatives', []))} alt.) — trafi do warstwy bez lokacji")

                    # FIX 2026-08-07: ostatnia szansa — obetnij doklejone śmieci
                    # z końca etykiety i spróbuj samej ulicy. Dotyczy tylko ofert,
                    # które i tak nie mają pinezki, więc nic nie może się przesunąć.
                    salvaged = self._salvage_street_label(final_full)
                    if salvaged:
                        rescue = self.geocoder.geocode_with_alternatives(
                            {'street': salvaged, 'number': None, 'full': salvaged})
                        if rescue:
                            coords, used_address = rescue
                            final_street = used_address['street']
                            final_number = used_address['number']
                            final_full = used_address['full']
                            geocode_meta = used_address.get('meta')
                            print(f"      🛟 Odzyskano ulicę z zaśmieconej etykiety: {final_full}")
        
        # 5. Stwórz ID z URL (unikalne)
        offer_id = raw_offer['url'].split('/')[-1].split('.')[0]
        
        # Buduj address dict (bez coords lub z coords=None jeśli nie znaleziono)
        # MIESZKANIOWY: zapisujemy KTÓRY adres faktycznie się zgeokodował (może być z alternatives)
        # FIX 2026-08-07: sprzątnij etykietę, gdy pinezka już stoi dobrze.
        # „Parysa Wynajmę" ma poprawny punkt (23 m od ul. Parysa), ale brzydką
        # nazwę — obcinamy doklejony ogon, NIE ruszając współrzędnych. Osobna
        # ścieżka od odzysku wyżej: tam geokoder nic nie znalazł, tu znalazł dobrze.
        # Warunek `not final_number` jest krytyczny: bez niego „Lipowa 10" zostałoby
        # skrócone do „Lipowa" (obcinanie nie odróżnia numeru domu od śmiecia).
        if coords and final_full and not final_number:
            cleaned = self._salvage_street_label(final_full)
            if cleaned:
                print(f"      🧹 Sprzątnięto etykietę adresu: '{final_full}' → '{cleaned}'")
                final_full, final_street, final_number = cleaned, cleaned, None

        # FIX 2026-08-08: na mapie stoją tylko adresy ULICZNE.
        # Nazwy osiedli („Botanik", „Piastowskie"), instytucji („Uniwersytetu
        # Medycznego") i śmieci parsera („Wolne", „Miejsca") dostawały pinezkę
        # w losowym punkcie tej okolicy i wyglądały jak adres. Teraz trafiają do
        # warstwy „bez lokacji" (widocznej też w zakładce debugowej), gdzie
        # etykieta uczciwie mówi „Adres nieznany", a surowy odczyt zostaje jako
        # wskazówka. Decyzja produktowa 2026-08-08.
        if coords and self._is_area_not_address(final_street or final_full or ''):
            print(f"      📤 '{final_full}' to nie ulica — bez pinezki, do warstwy bez lokacji")
            coords, geocode_meta = None, None

        # FIX 2026-08-06: has_number liczymy z adresu, który FAKTYCZNIE wygrał
        # geokodowanie (mógł to być wariant bez numeru z `alternatives`), a nie
        # z głównego kandydata parsera. Wcześniej 6 aktywnych ofert miało
        # has_number=True przy number=None — i kroplę „adres dokładny" na mapie.
        has_number = bool(final_number)
        address_dict = {
            'full': final_full,
            'street': final_street,
            'number': final_number,
            'has_number': has_number,
            'precision': self._address_precision(has_number, coords, geocode_meta),
        }
        if coords:
            address_dict['coords'] = coords
        # Brak coords → offer_id zapisze się do bazy BEZ coords → map_generator włączy do unlocalised

        promoted = bool(raw_offer.get('promoted'))

        return {
            'id': offer_id,
            'url': raw_offer['url'],
            # FIX 2026-08-09: tytuł ogłoszenia w bazie — popup mapy pokazuje go pod
            # adresem (jak w SONAR-POKOJOWY). Wcześniej jedynym źródłem nazwy był
            # slug URL, czyli tekst bez polskich znaków i wielkich liter.
            'title': (raw_offer.get('title') or '').strip(),
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
            'days_active': 0,
            # Płatne wyróżnienie na listingu OLX (scraper._is_promoted_href).
            # `promoted` = stan z OSTATNIEGO skanu, `promoted_dates` = dni, w
            # których widzieliśmy ofertę jako promowaną (max 1/dzień) — z tego
            # trend_generator buduje dzienny szereg „ile ofert jest promowanych".
            'promoted': promoted,
            'promoted_dates': [datetime.now(self.tz).strftime('%Y-%m-%d')] if promoted else [],
            'promoted_count': 1 if promoted else 0,
        }
    
    # FIX 2026-06-12: usunięto _find_existing_offer (liniowy skan bazy per oferta) —
    # run_scan używa teraz indeksu cid_index {CID3 → oferta} budowanego raz.

    def _track_promoted(self, existing: Dict, promoted: bool) -> bool:
        """Zapisuje płatne wyróżnienie oferty na listingu OLX — max 1 dzień/wpis.

        `promoted` = flaga z bieżącego skanu (scraper czyta ją z parametru
        atrybucji w href kafelka). Aktualizuje stan bieżący i dopisuje dzisiejszą
        datę do `promoted_dates`, jeśli jeszcze jej tam nie ma. Skanujemy 3×
        dziennie, więc dzień z choć jednym promowanym wystąpieniem liczy się raz.
        Zwraca True, gdy dopisano nowy dzień.
        """
        existing['promoted'] = bool(promoted)
        if not promoted:
            return False
        today = datetime.now(self.tz).strftime('%Y-%m-%d')
        dates = existing.setdefault('promoted_dates', [])
        if today in dates:
            return False
        dates.append(today)
        existing['promoted_count'] = len(dates)
        return True

    def _update_existing_offer(self, existing: Dict, new_data: Dict):
        """Aktualizuje istniejące ogłoszenie z inteligentnym zarządzaniem ceną."""
        now = datetime.now(self.tz).isoformat()

        # FIX 2026-08-09: zapamiętaj last_seen SPRZED nadpisania — to jedyny
        # moment, w którym da się policzyć, jak długo oferty nie było na rynku
        # (patrz reactivation_log: gap odsiewa szum listingu od realnych powrotów).
        prev_last_seen = existing.get('last_seen')

        # Aktualizuj last_seen
        existing['last_seen'] = now

        # FIX 2026-08-09: tytuł doklejamy też ofertom już w bazie (i odświeżamy,
        # gdy sprzedawca go zmienił) — inaczej popup pokazywałby prawdziwą nazwę
        # tylko dla ogłoszeń dodanych po tej zmianie.
        if new_data.get('title'):
            existing['title'] = new_data['title']

        # Śledź płatne wyróżnienie na listingu (dotyczy każdej oferty)
        self._track_promoted(existing, new_data.get('promoted', False))

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
        # FIX 2026-08-07: zapamiętaj stan SPRZED skopiowania coords — niżej decyduje
        # on o podmianie całego adresu. Bez tego oferta z odzyskaną ulicą dostawała
        # współrzędne, ale zachowywała starą etykietę i `precision='none'`
        # („Piłsudskiego Okna" z pinezką, a mapa nie wiedziała, jak ją narysować).
        old_had_coords = bool(existing_coords)
        if new_coords and not existing_coords:
            existing.setdefault('address', {})['coords'] = new_coords
            # Precyzja musi iść w parze ze współrzędnymi, inaczej zostaje 'none'.
            existing['address']['precision'] = (
                new_data.get('address', {}).get('precision')
                or self._address_precision(bool(existing['address'].get('number')), new_coords)
            )
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

        # FIX 2026-08-06: KOREKTA W DÓŁ — ta sama ulica, ale nowy parser nie widzi
        # już numeru. Wcześniej „lepszy" adres oznaczał wyłącznie *dodanie* numeru,
        # więc oferty ze zmyślonym numerem („Zana 2" z „2-pokojowe") zostawały w bazie
        # na zawsze, mimo poprawionego parsera. Warunek jest wąski: nazwa ulicy musi
        # być identyczna — sam numer znika. To nie może przenieść pinezki na inną ulicę.
        def _street_key(addr):
            return (addr.get('street') or '').strip().lower()

        number_retracted = (
            old_has_num and not new_has_num
            and _street_key(new_addr) and _street_key(new_addr) == _street_key(old_addr)
        )

        # FIX 2026-08-07: zdobycie współrzędnych zawsze jest poprawą — oferta
        # przenosi się z listy „bez lokacji" na mapę. Tak dociera do bazy odzysk
        # ulicy z zaśmieconej etykiety („PeowiakówZdjęcia są" → „Peowiaków").
        gained_coords = bool(new_addr.get('coords')) and not old_had_coords

        # FIX 2026-08-07: sprzątnięcie etykiety („Parysa Wynajmę" → „Parysa").
        # Nowa nazwa musi być początkiem starej i realną ulicą, a stara — nie;
        # to gwarantuje, że tylko obcinamy doklejony ogon, nie zmieniamy adresu.
        label_cleaned = (
            new_full and old_full.startswith(new_full)
            and is_known_street(new_full) and not is_known_street(old_full)
        )

        # FIX 2026-08-08: śmieciowa etykieta → realna ULICA. Bez tego poprawki
        # parsera nie docierały do bazy: „Kalina 38" ma numer, więc nie łapało się
        # ani na „nowy ma numer, stary nie", ani na `old_looks_like_garbage`
        # (ten warunek wprost wyklucza stary adres Z numerem), ani na
        # `number_retracted` (inna ulica). Oferta zostawała ze zmyślonym adresem
        # na zawsze, mimo że parser od dawna czytał z jej opisu „Niepodległości".
        # Kierunek jest jednostronny — nie-ulica → ulica — więc realny adres nie
        # może przez to zostać podmieniony na śmieć.
        # Warunek `not old_had_coords` jest krytyczny: gdy stara etykieta ma już
        # pinezkę, punkt bywa poprawny mimo brzydkiej nazwy („Parysa Wynajmę" stoi
        # 23 m od ul. Parysa). Takie rekordy należą do `_demote_non_street_pins`,
        # które obcina ogon i ZOSTAWIA punkt; podmiana na inną ulicę zabrałaby go.
        street_upgraded = (
            new_full and not old_had_coords
            and is_street_name(new_addr.get('street') or new_full)
            and not is_street_name(old_addr.get('street') or old_full or '')
        )

        new_looks_better = new_full and new_full != old_full and (
            (new_has_num and not old_has_num) or
            (old_looks_like_garbage and len(new_full) >= 5) or
            number_retracted or
            gained_coords or
            label_cleaned or
            street_upgraded
        )

        if new_looks_better:
            old_coords = old_addr.get('coords')  # zachowaj coords
            # FIX 2026-08-08: stare coords wolno przenieść tylko wtedy, gdy adres
            # dotyczy TEJ SAMEJ ulicy (albo jest jej sprzątniętą etykietą). Przy
            # podmianie „Kalina 38" → „Niepodległości" punkt starego adresu leży
            # gdzie indziej — przeniesiony postawiłby pinezkę pod złym budynkiem.
            same_place = (
                _street_key(new_addr) == _street_key(old_addr)
                or label_cleaned
                or (old_full and new_full and old_full.startswith(new_full))
            )
            existing['address'] = dict(new_addr)
            if number_retracted:
                # Stare coords wskazywały budynek o zmyślonym numerze — nie przenosimy
                # ich na adres bez numeru. Gdy nowe geokodowanie nic nie dało, oferta
                # trafia na skan do warstwy „bez lokacji" i zgeokoduje się przy kolejnym.
                self.stats_number_retracted = getattr(self, 'stats_number_retracted', 0) + 1
                print(f"      🔧 Wycofano zmyślony numer domu: '{old_full}' → '{new_full}'")
            elif old_coords and not new_addr.get('coords') and same_place:
                existing['address']['coords'] = old_coords
            if not number_retracted:
                print(f"      🏠 Zaktualizowano adres: '{old_full}' → '{new_full}'")
        
        # Upewnij się że jest aktywne (REAKTYWACJA nieaktywnych ofert)
        was_inactive = not existing.get('active', True)
        existing['active'] = True
        
        if was_inactive:
            print(f"      🔄 REAKTYWOWANO ofertę: {existing['id']} (była nieaktywna)")
            # 'rescrape' = oferta wróciła w listingu
            reactivation_log.record(existing, now, 'rescrape', prev_last_seen)
    
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
    
    def _reconcile_presence(self, current_offer_ids: List[str], skipped_offer_ids: List[str] = None,
                            promoted_cids: set = None):
        """
        Aktualizuje obecność ofert i zwraca KANDYDATÓW do dezaktywacji — oferty
        aktywne w bazie, nieobecne w listingu przez ≥ MISSING_STREAK_THRESHOLD
        kolejnych skanów. NIE dezaktywuje sama (patrz `_verify_and_deactivate`).

        FIX 2026-08-12: pojedyncze zniknięcie z listingu to szum paginacji OLX
        (~48/50 takich „zniknięć" wracało przy dawnej weryfikacji). Zamiast
        dezaktywować na jednym chybieniu i cofać to weryfikacją, liczymy kolejne
        chybienia (`missing_streak`); dopiero uporczywie nieobecne oferty idą do
        sprawdzenia linku. Obecność zeruje licznik.

        Args:
            current_offer_ids: ID ofert przetworzonych w tym skanie (nowe + zaktualizowane)
            skipped_offer_ids: ID ofert pominiętych przez inteligentne skanowanie (ta sama cena)
            promoted_cids: CID3 ofert płatnie wyróżnionych na listingu w TYM skanie
                           (ratunek dla ofert skipped — nie przechodzą _update_existing_offer,
                           więc flaga promowania inaczej by dla nich znikała)

        Returns:
            Lista ofert-kandydatów do sprawdzenia linku i ewentualnej dezaktywacji.
        """
        if skipped_offer_ids is None:
            skipped_offer_ids = []
        promoted_cids = promoted_cids or set()

        # Wszystkie oferty które są obecne w listingu = przetworzone + pominięte
        # FIX 2026-05-24: porównanie po CID3-IDxxxx zamiast pełnego slugu
        # (slug może się zmienić gdy sprzedawca edytuje tytuł ogłoszenia)
        all_active_cids = set(extract_cid(i) for i in (current_offer_ids + skipped_offer_ids))
        skipped_cids = set(extract_cid(i) for i in skipped_offer_ids)

        now = datetime.now(self.tz).isoformat()
        reactivated_from_skipped = 0
        candidates = []

        for offer in self.database['offers']:
            offer_cid = extract_cid(offer.get('id', ''))
            if offer_cid in all_active_cids:
                # Obecna w listingu → zeruj licznik chybień
                offer.pop('missing_streak', None)
                if offer_cid in skipped_cids:
                    if not offer.get('active', True):
                        # Reaktywacja oferty która była nieaktywna
                        offer['active'] = True
                        # 'skipped' = cena się nie zmieniła, scraper pominął detail.
                        # last_seen jest tu jeszcze sprzed skanu — stąd gap.
                        reactivation_log.record(offer, now, 'skipped', offer.get('last_seen'))
                        reactivated_from_skipped += 1
                    # Aktualizuj last_seen dla skipped ofert
                    offer['last_seen'] = now
                    # Wyróżnienie — skipped omija _update_existing_offer, więc bez
                    # tego flaga promowania nigdy nie odświeżyłaby się dla ofert
                    # bez zmiany ceny.
                    self._track_promoted(offer, offer_cid in promoted_cids)
            elif offer.get('active'):
                # Nieobecna, ale wciąż aktywna → policz chybienie.
                # Dezaktywacja NIE tu — dopiero po progu i sprawdzeniu linku.
                streak = offer.get('missing_streak', 0) + 1
                offer['missing_streak'] = streak
                if streak >= self.MISSING_STREAK_THRESHOLD:
                    candidates.append(offer)

        if reactivated_from_skipped > 0:
            print(f"   🔄 Reaktywowano (skipped): {reactivated_from_skipped}")
        if candidates:
            print(f"   🔎 Kandydaci do dezaktywacji (nieobecni ≥{self.MISSING_STREAK_THRESHOLD} skany): {len(candidates)}")

        return candidates

    def _offer_page_is_live(self, html: str) -> bool:
        """Czy strona pojedynczej oferty OLX świadczy o żywym ogłoszeniu.

        Priorytet: JSON-LD `availability == InStock` (najpewniejsze), a jak go
        brak — obecność ceny i przycisków kontaktu. Ta sama heurystyka co dawniej
        w weryfikacji, wyciągnięta osobno, żeby dała się testować bez sieci.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    if 'InStock' in data.get('offers', {}).get('availability', ''):
                        return True
                    break
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        price_element = soup.select_one('[data-testid="ad-price-container"]')
        contact_btns = soup.select('[data-testid*="phone"], [data-testid*="contact"]')
        return bool(price_element and len(contact_btns) > 0)

    def _deactivate_offer(self, offer: Dict, now_iso: str):
        """Dezaktywuje ofertę potwierdzoną jako zniknięta z OLX."""
        offer['active'] = False
        # Nie ma jej na listingu → nie jest już promowana. Historia dni
        # (promoted_dates) zostaje — z niej liczy się szereg czasowy.
        offer['promoted'] = False
        offer['verified_inactive_at'] = now_iso
        offer.pop('missing_streak', None)

    def _verify_and_deactivate(self, candidates: List[Dict]) -> Dict:
        """
        Sprawdza bezpośrednio link każdego kandydata i dezaktywuje TYLKO oferty,
        które OLX potwierdza jako zniknięte. FIX 2026-08-12.

        Decyzja na podstawie realnego stanu ogłoszenia, nie nieobecności w naszym
        listingu:
          - 404/410 albo strona bez „InStock" → zniknęła → dezaktywuj
          - 200 + InStock                     → żyje mimo nieobecności → zostaje
                                                 aktywna, reset licznika chybień
          - 403 / timeout / błąd sieci        → NIE WIADOMO → zostaje aktywna,
                                                 spróbujemy następnym skanem
        Circuit breaker: LINK_CHECK_ERROR_CIRCUIT błędów z rzędu → przerywamy
        (IP prawdopodobnie zdławione — dalsze próby to bicie w mur).
        """
        import http_client

        stats = {
            'checked': 0,
            'confirmed_inactive': 0,
            'stale_inactive': 0,
            'still_alive': 0,
            'errors': 0,
            'circuit_broken': False,
            'candidates': len(candidates),
        }
        if not candidates:
            return stats

        now_day = datetime.now(self.tz).date()

        def _missing_days(offer):
            try:
                return (now_day - date.fromisoformat((offer.get('last_seen') or '')[:10])).days
            except ValueError:
                return 0          # brak/uszkodzony last_seen → nie zgadujemy

        # KROK 1: nieobecne dłużej niż sufit — dezaktywacja bez sprawdzania linku.
        # Bez tego kolejka rośnie szybciej, niż ją drenujemy (patrz MAX_MISSING_DAYS).
        stale = [o for o in candidates if _missing_days(o) >= self.MAX_MISSING_DAYS]
        if stale:
            stale_now = datetime.now(self.tz).isoformat()
            for offer in stale:
                self._deactivate_offer(offer, stale_now)
            stats['stale_inactive'] = len(stale)
            # Liczy się do tej samej metryki co potwierdzenia linkiem — API
            # i monitoring czytają `confirmed_inactive` jako „ile zniknęło".
            stats['confirmed_inactive'] += len(stale)
            print(f"   ⌛ Nieobecne ≥{self.MAX_MISSING_DAYS} dni → dezaktywowane bez "
                  f"sprawdzania linku: {len(stale)}")

        # KROK 2: świeżo nieobecne — link check łapie zniknięcie wcześniej niż sufit.
        fresh = [o for o in candidates if _missing_days(o) < self.MAX_MISSING_DAYS]
        if not fresh:
            print(f"   📊 Weryfikacja linków: pominięta (wszyscy kandydaci przekroczyli sufit)")
            return stats
        # Najstarsze last_seen najpierw — najbardziej podejrzane o realne zniknięcie.
        to_check = sorted(fresh, key=lambda o: o.get('last_seen', ''))[:self.MAX_LINK_CHECKS]
        print(f"   🔍 Sprawdzam linki {len(to_check)} kandydatów (z {len(fresh)})...")

        session = http_client.ImpersonatedSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'
        })
        now = datetime.now(self.tz).isoformat()
        consecutive_errors = 0

        def _register_error():
            nonlocal consecutive_errors
            stats['errors'] += 1
            consecutive_errors += 1
            if consecutive_errors >= self.LINK_CHECK_ERROR_CIRCUIT:
                stats['circuit_broken'] = True
                print(f"   🛑 Circuit breaker: {consecutive_errors} błędów z rzędu — "
                      f"przerywam sprawdzanie linków (IP prawdopodobnie zdławione).")
                return True
            return False

        for i, offer in enumerate(to_check, 1):
            url = offer.get('url', '')
            offer_id = offer.get('id', 'unknown')
            if not url:
                continue
            try:
                if i > 1:
                    time.sleep(random.uniform(0.3, 0.7))
                response = session.get(url, timeout=15)
                stats['checked'] += 1

                if response.status_code in (404, 410):
                    self._deactivate_offer(offer, now)
                    stats['confirmed_inactive'] += 1
                    consecutive_errors = 0
                    continue

                if response.status_code != 200:
                    if _register_error():
                        break
                    continue

                consecutive_errors = 0
                if self._offer_page_is_live(response.text):
                    # Żyje mimo nieobecności w listingu → zostaje aktywna.
                    offer.pop('missing_streak', None)
                    stats['still_alive'] += 1
                else:
                    self._deactivate_offer(offer, now)
                    stats['confirmed_inactive'] += 1
                    print(f"      ⏸️  Zniknęła z OLX: {offer_id[:50]}")
            except http_client.RequestError:
                if _register_error():
                    break
            except Exception:
                if _register_error():
                    break

        print(f"   📊 Weryfikacja linków: sprawdzono {stats['checked']}, "
              f"zniknęły {stats['confirmed_inactive']}, żyją mimo nieobecności {stats['still_alive']}, "
              f"błędy {stats['errors']}" + (" (circuit breaker)" if stats['circuit_broken'] else ""))
        return stats
    
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

    def _no_address_alert(self, no_address_count: int, scraped_count: int):
        """
        Zwraca ostrzeżenie, gdy zbyt duża część skanu została bez adresu,
        albo None gdy odsetek jest normalny.

        FIX 2026-08-06: bez tego bezpiecznika regresja parsera przechodziła bez
        żadnego sygnału — skan kończył się statusem „✅ sukces", choć setki ofert
        traciły lokalizację. Zdrowy skan ma ~4–5% ofert bez adresu (34 z 764);
        próg MAX_NO_ADDRESS_RATIO (20%) daje szeroki margines, a łapie awarię
        typu „parser przestał rozpoznawać ulice".

        FIX 2026-08-07: takie oferty nie znikają już ze strony (lądują w warstwie
        „bez lokacji"), więc alert dotyczy teraz JAKOŚCI lokalizacji, a nie utraty
        ogłoszeń. Skala zjawiska jest ta sama, dlatego próg zostaje bez zmian.
        """
        if scraped_count < 50 or no_address_count <= scraped_count * self.MAX_NO_ADDRESS_RATIO:
            return None
        pct = no_address_count / scraped_count * 100
        return (f"Parser adresów nie rozpoznał ulicy w {no_address_count} z {scraped_count} ofert "
                f"({pct:.0f}%, próg: {self.MAX_NO_ADDRESS_RATIO * 100:.0f}%) — prawdopodobna "
                f"regresja parsera lub zmiana formatu ogłoszeń. Te oferty trafiły na stronę "
                f"bez lokalizacji na mapie.")

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
            # FIX 2026-08-07: oferty bez adresu nie są już odrzucane — liczymy je
            # osobno, żeby monitoring i bezpiecznik dalej widziały skalę zjawiska.
            no_address_count = 0
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

                # FIX 2026-08-07: oferta bez rozpoznanego adresu zostaje na stronie
                # (warstwa „bez lokacji"), ale wciąż ją liczymy i próbkujemy — inaczej
                # regresja parsera byłaby niewidoczna. Zakładka debugowa pokazuje to
                # w sekcji „brak adresu".
                if not (processed.get('address') or {}).get('full'):
                    no_address_count += 1
                    if len(skipped_samples['no_address']) < SAMPLE_LIMIT:
                        full_text = raw_offer['title'] + " " + raw_offer.get('description', '')
                        sample = {
                            'url': raw_offer.get('url', ''),
                            'title': raw_offer.get('title', '')[:200],
                            'description_preview': (raw_offer.get('description', '') or '')[:500],
                            'note': 'oferta zostaje na stronie w warstwie „bez lokacji"',
                        }
                        street_only = self.address_parser.extract_street_only(full_text)
                        if street_only:
                            sample['note'] += f" | extract_street_only znalazłby: {street_only['full']}"
                        skipped_samples['no_address'].append(sample)

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
                            'no_address': no_address_count,
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
                'no_address_kept': no_address_count,
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
            print(f"   Bez adresu (zostają w warstwie 'bez lokacji'): {no_address_count}")
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

            # CID3 ofert płatnie wyróżnionych na listingu w TYM skanie — ratunek
            # dla ofert skipped, które nie przechodzą _update_existing_offer.
            promoted_cids = {
                extract_cid(offer['url'])
                for offer in raw_offers
                if offer.get('promoted')
            }
            print(f"   ⭐ Promowane na listingu: {len(promoted_cids)} ofert")

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
            #
            # FIX 2026-08-12: dezaktywacja oparta na REALNYM stanie oferty.
            # `_reconcile_presence` liczy chybienia (nieobecność w listingu),
            # a `_verify_and_deactivate` sprawdza link kandydatów (≥ próg chybień)
            # i dezaktywuje tylko potwierdzone zniknięcia. Blokada OLX → nie
            # ruszamy ani licznika chybień, ani dezaktywacji (inaczej odblokowanie
            # zrzuciłoby naraz wszystkie nagromadzone chybienia).
            block_reason = self._deactivation_block_reason(scraped_count, active_in_db)
            scrape_blocked = block_reason is not None
            if scrape_blocked:
                print(f"   ⚠️  OCHRONA: {block_reason}")
                self.scan_logger.log_error(block_reason)
                verification_stats = {
                    'checked': 0, 'confirmed_inactive': 0, 'still_alive': 0,
                    'errors': 0, 'circuit_broken': False, 'candidates': 0,
                    'skipped_blocked': True,
                }
            else:
                candidates = self._reconcile_presence(current_offer_ids, skipped_ids,
                                                      promoted_cids=promoted_cids)
                verification_stats = self._verify_and_deactivate(candidates)
                deactivated_count = verification_stats['confirmed_inactive']
            
            # FIX 2026-08-06: bezpiecznik — czy parser adresów nagle nie zaczął
            # wycinać ofert (regresja reguł / zmiana formatu opisów w OLX).
            no_address_reason = self._no_address_alert(no_address_count, scraped_count)
            if no_address_reason:
                print(f"   ⚠️  UWAGA: {no_address_reason}")
                self.scan_logger.log_error(no_address_reason)

            # Aktualizuj days_active dla WSZYSTKICH ofert
            self._update_days_active()

            # FIX 2026-08-06: przelicz adresy zapisane starym parserem (też nieaktywne),
            # a potem domknij `precision` dla rekordów sprzed tej zmiany. Oba kroki
            # są lokalne — zero zapytań do Nominatim.
            self._migrate_legacy_addresses()
            self._demote_non_street_pins()
            self._backfill_address_precision()
            self._backfill_promoted_from_url()
            self._clean_geocoding_cache()
            self._downgrade_street_level_pins()
            
            print(f"   Nowe oferty: {new_offers_count}")
            print(f"   Zaktualizowane: {updated_offers_count}")
            if reactivated_count > 0:
                print(f"   🔄 Reaktywowane: {reactivated_count}")
            retracted = getattr(self, 'stats_number_retracted', 0)
            if retracted:
                print(f"   🔧 Wycofane zmyślone numery domów: {retracted}")
            
            # (Weryfikacja + dezaktywacja odbyły się wyżej, w kroku dezaktywacji:
            #  _reconcile_presence + _verify_and_deactivate. FIX 2026-08-12 —
            #  nie ma już osobnego kroku „weryfikacja nieaktywnych", bo nie
            #  dezaktywujemy przedwcześnie, więc nie ma czego masowo cofać.)
            if verification_stats.get('still_alive'):
                print(f"   ℹ️  Żywe mimo nieobecności w listingu (zostają aktywne): "
                      f"{verification_stats['still_alive']}")

            # 5. Czyszczenie starych ofert
            print("\n🗑️ Krok 5: Czyszczenie starych ofert...")
            self._cleanup_old_offers(max_age_days=548)
            
            # 6. Aktualizacja metadanych
            self.database['last_scan'] = now.isoformat()
            self.database['next_scan'] = self._calculate_next_scan_time()
            
            # FIX 2026-08-09: bilans mapy liczymy DOPIERO TU — po weryfikacji
            # nieaktywnych (Krok 4) i czyszczeniu (Krok 5). Liczony wcześniej
            # opisywał stan sprzed reaktywacji: pokazywał 665 aktywnych zamiast
            # 713, a że sam w sobie się domykał, zielony pasek „bilans OK"
            # uwiarygadniał liczby rozjechane z mapą.
            self._write_map_gap_breakdown()

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
                'verification': verification_stats,
                # FIX 2026-08-09: jakość mapy jako metryka skanu — udział pinezek
                # dokładnych i podział ofert bez pinezki. Bez tego każdą zmianę
                # parsera/geokodera trzeba było mierzyć ręcznym skryptem.
                'map_quality': getattr(self, 'map_quality_stats', None),
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

            # FIX 2026-08-05: sygnał dla run_scan_with_retry — True gdy wykryto
            # blokadę OLX/Cloudflare (dezaktywacja pominięta), False przy zdrowym skanie.
            return scrape_blocked

        except Exception as e:
            # W przypadku błędu, zaloguj i zakończ jako failed
            print(f"\n❌ Błąd podczas skanowania: {e}")
            self.scan_logger.log_error(str(e))
            self.scan_logger.end_scan('failed', time.time() - scan_start_time)
            raise

    def run_scan_with_retry(self, wait_seconds: int = None, max_retries: int = None) -> bool:
        """
        Uruchamia run_scan(), a przy wykrytej blokadzie OLX/Cloudflare
        (0 / podejrzanie mało ofert) czeka i ponawia skan.

        FIX 2026-08-05: blokada OLX bywa chwilowa (rate limit / Cloudflare
        challenge). Zamiast czekać ~5 h do następnego skanu z harmonogramu,
        odczekujemy wait_seconds (domyślnie 2 min) i próbujemy ponownie,
        aż do max_retries dodatkowych prób. Każda próba loguje osobny wpis
        w scan_history (widoczny w dashboardzie monitoringu).

        Ochrona przed masową dezaktywacją NIE jest tym omijana — dopóki
        scraper zwraca za mało ofert, dezaktywacja pozostaje pominięta.

        Returns:
            True gdy po wyczerpaniu prób blokada nadal trwa, False gdy skan
            zakończył się zdrowo (bez blokady).
        """
        wait_seconds = self.RETRY_ON_BLOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds
        max_retries = self.RETRY_ON_BLOCK_MAX_RETRIES if max_retries is None else max_retries

        attempt = 0
        while True:
            blocked = self.run_scan()
            if not blocked:
                return False
            if attempt >= max_retries:
                print(f"\n⚠️  Blokada OLX utrzymuje się po {attempt + 1} "
                      f"próbach — kończę bez dezaktywacji ofert.")
                return True
            attempt += 1
            print(f"\n⏳ Wykryto blokadę OLX — czekam {wait_seconds}s i ponawiam "
                  f"scan (próba {attempt}/{max_retries})...")
            time.sleep(wait_seconds)


if __name__ == "__main__":
    agent = SonarMieszkaniowy(data_file=paths.OFFERS_JSON)
    agent.run_scan_with_retry()
