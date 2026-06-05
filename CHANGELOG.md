# Changelog

Wszystkie istotne zmiany w projekcie SONAR MIESZKANIOWY.

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Daty w formacie RRRR-MM-DD (strefa Europe/Warsaw).

> Wpisy do 2026-05-22 zrekonstruowano z datowanych komentarzy `# FIX` w kodzie
> (historia gita w tym klonie sięga 2026-05-23). Od tej daty źródłem są commity.

## [Niewydane]

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
