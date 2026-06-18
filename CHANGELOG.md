# Changelog

Wszystkie istotne zmiany w projekcie SONAR MIESZKANIOWY.

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Daty w formacie RRRR-MM-DD (strefa Europe/Warsaw).

> Wpisy do 2026-05-22 zrekonstruowano z datowanych komentarzy `# FIX` w kodzie
> (historia gita w tym klonie sięga 2026-05-23). Od tej daty źródłem są commity.

## [Niewydane]

### Naprawione (audyt 2026-06-12)
- **`geocoder.py`: limit `MAX_NEW_GEOCODES` faktycznie działa.** Flaga
  `_geocoding_limited` była ustawiana w `main.py`, ale geocoder nigdy jej nie
  czytał — limit 150 geokodowań/skan był martwy. Tryb limited = tylko cache,
  bez zapytań Nominatim i bez zapisu `None` do cache.
- **Blokada OLX raportowana jako ⚠️ warning, nie „✅ brak zmian".** Skan z 0 ofert
  (ochrona przed masową dezaktywacją) kończył się statusem `completed` bez
  błędów — API/aplikacja pokazywały sukces, mimo że system był ślepy (skany
  11–12.06). Teraz powód blokady trafia do `scan_history` jako błąd
  (`uiStatus=warning`, powiadomienie ⚠️, system `degraded`), a weryfikacja 50
  nieaktywnych ofert jest przy blokadzie pomijana (i tak padała 50/50).
- **Atomowe zapisy JSON + abort przy uszkodzonej bazie.** Nowy
  `src/atomic_json.py` (tmp + `os.replace`) dla `offers.json`,
  `removed_listings.json`, `geocoding_cache.json`, `scan_history.json`.
  `_load_database` przy `JSONDecodeError` przerywa skan z `RuntimeError`
  zamiast cicho startować od pustej bazy (ryzyko scommitowania utraty całej
  historii ofert).
- **Frontend (XSS): dane z OLX escapowane przed `innerHTML`.** Opisy, adresy
  i URL-e scrapowanych ogłoszeń trafiały do HTML bez escapowania (popup mapy,
  lista „bez lokacji", karty zmian cen w `market_analysis.html`, toast
  `?offer=`). Dodano `escapeHtml`/`safeUrl` w `assets/script.js` i
  `market_analysis.html`, pełne escapowanie w `top5.html`; id oferty w
  `toggleDescription` przez `data-offer-id` zamiast parametru inline `onclick`.
- **`geocoder.py`: świeży null-cache nie odpytuje Nominatim co skan.** Adres
  z odmienialną nazwą (mianownik ≠ oryginał) omijał TTL: każdy skan robił
  zapytania live (oryginał + mianownik), a finalny zapis nulla odświeżał
  timestamp — TTL nigdy nie wygasał. Świeży null = tryb cache-only (fallbacki
  przez cache wariantów nadal działają), timestamp odświeżany tylko po realnej
  próbie live.
- **Cooldown weryfikacji nieaktywnych ofert (7 dni).** Te same 50 najnowszych
  nieaktywnych było odpytywane przy każdym skanie (3×dziennie). Potwierdzenie
  nieaktywności zapisuje `verified_inactive_at`; oferta wraca do puli po 7
  dniach (lub natychmiast po reaktywacji).
- **Upgrade źródła ceny z różnicą ≥50% = korekta, nie zmiana ceny.** Wcześniej
  upgrade (np. Parser tekstowy → JSON-LD) omijał sanity-check 50%: błędna cena
  parsera „zmieniała się" na poprawną, generując fałszywy trend i gigantyczną
  „okazję" w top5. Korekta aktualizuje cenę po cichu (nadpisuje błędny wpis
  w `history`), bez `price_trend`/`previous_price`/`price_changes`.
- **Godziny skanu ujednolicone na 9:17/15:17/21:17.** Cron działa o :17 od
  2026-05-25, ale `_calculate_next_scan_time` (`main.py`, `api_generator.py`)
  liczyło pełne godziny — „następny skan" na froncie/API był zaniżony o 17 min.
  Zaktualizowano też README (stary cron `0 7,13,19`) i `docs/API.md`.
- **`quick_scan.py` wymaga `--force`.** Skrypt czyści całą bazę (bezpowrotna
  utrata historii cen, `first_seen`, ofert nieaktywnych) — dotąd bez
  ostrzeżenia. Ścieżka do bazy z `paths.py` zamiast względnej zależnej od CWD.

### Dodane
- **20 mockupów nowej podstrony „Analiza cen wg metrażu"** (`docs/mockups/`).
  Podstrona analizuje treść ogłoszeń (ekstrakcja metrażu m² i liczby pokoi
  regexem z opisów), liczy cenę za m², przedziały cenowe wg metrażu, podział
  na dzielnice, mapę cieplną dzielnica×metraż, korelację powierzchnia-cena,
  trend zł/m² w czasie i kalkulator szacowanego czynszu. Statystyki liczone z
  pełnej historii (`compute_stats.py` → `stats.json`, 956/1526 ofert = 63%
  pokrycia metrażem). 20 wariantów wizualnych do wyboru + galeria `index.html`.
  Generowane przez `docs/mockups/generate.py`. **Status: poglądowe mockupy**,
  jeszcze niewpięte w nawigację serwisu.

### Dodane (audyt 2026-06-12)
- `concurrency: sonar-scanner` w `scanner.yml` — cron + watchdog + manualny
  dispatch nie odpalą już dwóch skanów równolegle (dwa joby commitujące
  `data/offers.json` to ryzyko utraty danych mimo pętli `pull --rebase`).
- 49 nowych testów (suite 46 → 95): `test_geocoder.py` (limit geokodowań,
  TTL null-cache, regresja fleksji), `test_api_generator.py` (mapowanie
  blokady na warning), `test_atomic_json.py` (atomowy zapis, abort przy
  korupcji), `test_main_scan.py` (ochrona przed masową dezaktywacją —
  wyciągnięta do testowalnej `_deactivation_block_reason`, logika cen,
  cooldown weryfikacji).

### Wydajność (audyt 2026-06-12)
- `main.py`: set `removed_cids` liczony raz przed pętlą (było: od nowa dla
  każdej z ~530 ofert); indeks `cid_index {CID3 → oferta}` zamiast liniowego
  skanu bazy per oferta (~500 × 1375 porównań z regexem).

### Usunięte (audyt 2026-06-12)
- Martwy kod: `PriceParser._filter_invalid_prices` (nieużywane od usunięcia
  fallbacku „pierwsza sensowna kwota"), pętla podmieniająca ofertę w
  `all_offers` w scraperze (no-op — worker mutuje ten sam obiekt),
  `main._find_existing_offer` (zastąpione indeksem CID).

### Zmienione (audyt 2026-06-12)
- Jedna wersja Chart.js (4.4.1) na wszystkich podstronach (było: top5 4.4.1,
  reszta 4.4.0).

### Naprawione
- `address_parser.py`: dodano `'nice'` do `EXCLUDED_WORDS` — nazwa osiedla/kompleksu
  „Nice 2" była błędnie traktowana jako adres ulicy (oferta przy ul. Beliniaków
  dostawała adres `Nice 2` zamiast właściwego).


- `api_generator.py`: liczba ofert „które znikły" w API (`status.json`,
  `history.json`) jest teraz spójna z kolumną „Znikło" w dashboardzie
  monitoringu. Wcześniej API pokazywało surowe `disappeared` (oferty
  przeoczone przez scraper, zawyżone przez niestabilną paginację OLX), a
  dashboard `confirmed_inactive` (po weryfikacji). Nowy helper
  `_disappeared_count()` używa priorytetu `confirmed_inactive > disappeared`,
  identycznie jak `docs/monitoring.html`.

### Usunięte (sprzątanie)
- Martwy kod (0 użyć w repo): `PriceParser._detect_media_info_simple`,
  `PriceParser.PRICE_PATTERN`, `DuplicateDetector.find_duplicates_in_batch`,
  `Geocoder.batch_geocode`, `AddressParser.validate_lublin_address` (~90 linii).
- `src/migrate_price_changes.py` — jednorazowa migracja, już wykonana
  (134/148 ofert ma `price_changes`).

### Zmienione (sprzątanie)
- README zaktualizowany: status „działa produkcyjnie" zamiast „świeżo
  zainicjowany", realna roadmapa (done/todo), usunięte „skopiowane 1:1".
- `skipped_debug.html` przestaje być „tymczasowa" — to stała strona
  diagnostyczna parsera (zaktualizowany baner i docstring generatora).

### Dodane
- `CLAUDE.md` — wytyczne dla agentów (uruchamianie, przepływ danych, pułapki).
- `CHANGELOG.md` — ten plik.
- Suite testów `pytest` (`tests/`, 46 testów) + workflow CI `tests.yml`
  uruchamiany na push/PR dotykające `src/` lub `tests/`.
- Lazy-loading opisów na mapie: `data.json` zawiera tylko podgląd (200 znaków),
  pełne opisy w osobnym `docs/descriptions.json` doczytywanym po kliknięciu
  „Pokaż całość" (fetch raz, cache w pamięci). `data.json` 2,04 MB → 1,51 MB
  (−26%), 1,28 MB opisów ładowane na żądanie zamiast przy starcie.

### Wydajność
- Deduplikacja ofert w skanie: O(n²) → O(n·k) przez indeks `address_key →
  [oferty]`. Duplikat wymaga identycznego adresu, więc kosztowny Levenshtein
  liczony tylko w obrębie tego samego adresu (zwykle 1–2 oferty). Wynik
  identyczny — pilnuje `tests/test_duplicate_detector.py`.
- Tagi ofert (kawalerka/pokój/mieszkanie) liczone RAZ w `main.py` przy
  przetwarzaniu i zapisywane w `offers.json`. `map_generator` tylko je odczytuje
  (`resolve_tags`) zamiast liczyć regexy na każdym opisie przy każdej generacji.
  Dla starych ofert bez `tags` — fallback liczy w locie (zero regresji).

### Zmienione
- Ścieżki do danych/docs wydzielone do `src/paths.py` (kotwiczone do lokalizacji
  repo, nie do CWD). Skrypty działają teraz także uruchamiane spoza `src/`
  (np. z roota albo przez pytest). Domyślne argumenty bez zmian dla `cd src`.
- `price_parser.py`: nazewnictwo z „pokojowego" na „najmu/mieszkania”
  (`ROOM_PRICE_PATTERNS`→`RENT_PRICE_PATTERNS`, `_extract_room_price`→
  `_extract_rent_price`, docstringi). Treść regexów i publiczne API bez zmian —
  zachowanie identyczne (zaszłość po porcie z SONAR-POKOJOWY).

### Niezmienione (świadomie)
- `PRICE_RANGES` (zakresy/kolory mapy) — pozostawione bez zmian po analizie
  rozkładu (mediana 2300 zł, ~75% ofert w 1750–2750 zł, obecne progi pokrywają
  ten przedział wystarczająco gęsto).

### Naprawione
- `scanner.yml`: krok tygodniowego `fix_missing_coords` nigdy się nie wykonywał —
  warunek `if` sprawdzał stary cron `'0 7,13,19'`, a aktywny to `'17 7,13,19'`.
  Usunięto kruchy warunek; o dzień tygodnia pyta `date` w skrypcie.

### Zmienione
- `extract_cid()` wydzielone do wspólnego modułu `src/cid.py` (był zduplikowany
  w `main.py` i `scraper.py`). Zachowanie identyczne.
- `EXCLUDED_WORDS` (`address_parser.py`): usunięto ~40 zdublowanych wpisów.
  Zawartość zbioru bez zmian (248 słów — pilnuje `tests/test_excluded_words.py`).

## [2026-05-29]

### Zmienione
- Monitoring: pokazuje potwierdzone zniknięcia ofert zamiast surowej dezaktywacji.

## [2026-05-26]

### Naprawione
- CI: użycie `secrets.PAT_TOKEN` zamiast `GITHUB_TOKEN` w checkoutcie i watchdogu
  (domyślny token został zawieszony).

## [2026-05-25]

### Dodane
- Watchdog (`.github/workflows/watchdog.yml`) — sprawdza co 30 min, czy skan się
  odbył; przy braku skanu >7 h wyzwala `scanner.yml`.
- Analiza rynku: 3-stanowy przełącznik rozkładu cen (Tylko aktywne / Nieaktywne / Wszystkie).

### Naprawione
- Scanner: cron przesunięty na minutę 17 (`17 7,13,19`) — off-peak, mniej
  pomijanych skanów przez kolejkę GitHub Actions.

## [2026-05-24]

### Naprawione
- Pełna spójność identyfikacji ofert po stabilnym `CID3-IDxxxx` (slug w URL bywa
  edytowany przez sprzedawcę).
- Deduplikacja ofert po `CID3-IDxxxx` — scalono 131 duplikatów w bazie.
- Przywrócono utracone pola cenowe: `price_changes`, `price_trend`,
  `previous_price`, `price_changed_at`.
- Spójność `reactivation_source` (`rescrape` / `skipped` / `verification`).
- Hotfix: brakujący `import re` po refaktorze deduplikacji.

### Dodane
- Monitoring: kolumna „Znikło" w tabeli i serii wykresu; backfill `disappeared`
  w danych historycznych.

## [2026-05-23]

### Dodane
- API i monitoring śledzą oraz wystawiają liczbę znikniętych ogłoszeń
  (`disappeared`); `null` dla starych skanów (brak danych ≠ 0 znikłych).

### Naprawione
- Parser+DB: aktualizacja adresu oferty, gdy nowe parsowanie daje lepszy wynik
  (np. pojawił się numer domu lub stary adres był śmieciem z tytułu).

### Wydajność
- Frontend: wsadowe dodawanie markerów (`addLayers`/`forEach+addLayer`) zamiast
  `addTo()` per marker — jeden rerender warstwy zamiast N.

## [2026-05-16]

### Naprawione
- Parser adresów: odcinanie słów „mieszkaniowych" z końca nazwy ulicy
  („Bursztynowa Mieszkanie" → „Bursztynowa") zamiast odrzucania całości.
- Przywrócono fallback `extract_street_only` (ulica bez numeru) — wcześniej jego
  usunięcie przy porcie kosztowało ~208 przybliżonych ofert na skan.
- Dodano fallback whitelisty znanych ulic z `geocoding_cache` dla opisów bez
  jawnego prefiksu (np. „Lublin, Narutowicza, mieszkanie").
- Rozbudowano `EXCLUDED_WORDS` o pułapki specyficzne dla mieszkań
  („Kaucja N", „wysokość wnętrz N", „klimatyzacja Mieszkanie N").

## [2026-05-15]

### Dodane
- `geocode_with_alternatives()` — geokoder próbuje głównego kandydata, a potem
  alternatyw z parsera (ratuje opisy typu „Mieszkanie 3-pokojowe Narutowicza 38").
- Parser zwraca listę `alternatives` posortowaną po pewności.

### Wydajność
- Per-thread rate limiter w scraperze + globalny soft cap (20 QPS) — realnie
  wielowątkowe pobieranie szczegółów (wcześniej wątki czekały sekwencyjnie).
- Reuse współrzędnych z poprzedniego skanu przy niezmienionym adresie — skan
  skrócony z ~70 min do ~9 min.

## [2026-05-14]

### Naprawione
- Geokoder: fallback „sama ulica bez numeru" + warianty l. pojedynczej żeńskiej
  („Kraśnickich" → „Kraśnicka"); nie zatruwa cache pod kluczem oryginału.
- Parser: preprocessing tekstu (rozdzielanie sklejonych tokenów CamelCase i
  „cyfra+Wielka", normalizacja spacji) — naprawia artefakty po HTML-strippingu.
- `STREET_ONLY_PATTERN` obsługuje prefiks z kropką bez spacji („ul.Furmańska").

## [2026-05-13]

### Naprawione
- Geokoder: bypass zatrutego cache (`None`) przez sprawdzenie formy mianownikowej.
- Rozróżnienie rate-limit (429) od prawdziwego braku wyniku — błędy tymczasowe
  nie są cache'owane jako `None`.
- Parser: obsługa form gramatycznych prefiksów („ulicy", „ulicą", „alei", „placu").

## [2026-05-11]

### Dodane
- Geokoder: transformacja dopełniacz→mianownik polskich nazw ulic
  (`to_nominative`) — odzyskuje ~40% adresów odrzucanych wcześniej.
- Parser: whitelist znanych ulic z `geocoding_cache.json` jako trzeci fallback.
- TTL dla negatywnych wpisów cache (7 dni) — chroni przed trwałym zamrożeniem
  ulic chwilowo niedostępnych w Nominatim.

## [2026-05] — Wcześniej

### Dodane
- Walidacja cen w zakresie 200–10000 zł (dostosowane z pokoi do mieszkań).
- Tagowanie ofert (`offer_tagger.py`): kawalerka / pokój / mieszkanie.
- Mobile API ze statycznymi JSON-ami (`status` / `history` / `health`).
- Weryfikacja nieaktywnych ofert przez bezpośrednie sprawdzenie URL na OLX.
- Zabezpieczenie przed masową dezaktywacją przy blokadzie OLX (próg 30%).

### Podstawa
- Port architektury z `SONAR-POKOJOWY`: scraper OLX, parser adresów/cen,
  geokoder Nominatim z cache, detektor duplikatów, generatory mapy/API/monitoringu,
  frontend Leaflet na GitHub Pages, harmonogram GitHub Actions (3 skany/dzień).
