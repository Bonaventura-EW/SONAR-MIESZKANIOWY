# CLAUDE.md

Wytyczne dla Claude Code (i innych agentów) pracujących w tym repozytorium.
Czytaj ten plik na starcie każdej sesji — opisuje jak projekt działa, jak go
uruchomić i jakich pułapek unikać.

## Czym jest projekt

**SONAR MIESZKANIOWY** — automatyczny agent monitorujący oferty wynajmu
mieszkań w Lublinie (źródło: OLX). Działa bez serwera i bez bazy SQL:

- **GitHub Actions** uruchamia skan 3×/dzień (`.github/workflows/scanner.yml`).
- **GitHub Pages** serwuje statyczny frontend z katalogu `docs/`.
- **Źródłem prawdy są pliki JSON** w `data/` (commitowane do repo przez Actions).

Projekt powstał jako port z siostrzanego `SONAR-POKOJOWY` (monitoring pokoi),
stąd część kodu (zwłaszcza `price_parser.py`) wciąż ma nazewnictwo „pokojowe".

## Przepływ danych

```
scraper.py            → pobiera oferty z OLX (listing + szczegóły, wielowątkowo)
  ↓
address_parser.py     → wyciąga adres z tytułu/opisu (regex + fallbacki)
price_parser.py       → wyciąga cenę (priorytet: JSON-LD > cache > parser tekstu)
geocoder.py           → adres → współrzędne (Nominatim + cache + polska fleksja)
duplicate_detector.py → odrzuca duplikaty (ten sam adres + opis >95% podobny)
  ↓
data/offers.json      → baza ofert (aktywne + historia)
  ↓
map_generator.py      → docs/data.json          (mapa Leaflet)
api_generator.py      → docs/api/*.json          (mobile API: status/history/health)
top5_generator.py     → docs/top5_data.json      (zmiany cen)
monitoring_generator.py → docs/monitoring_data.json (dashboard skanów)
skipped_debug_generator.py → docs/skipped_debug.html (diagnostyka odrzuconych)
```

## Jak uruchomić

> 🏷️ **„Uruchom scan" (polecenie użytkownika) = odpal workflow GitHub Actions
> `scanner.yml` na gałęzi `main`** (manualny `workflow_dispatch`), a NIE lokalne
> `python main.py`. Workflow sam commituje wyniki na `main`. Lokalne `main.py`
> uruchamiaj tylko gdy użytkownik wprost o to poprosi (np. „uruchom lokalnie").

> ℹ️ Ścieżki do danych są kotwiczone w `src/paths.py` (względem lokalizacji repo,
> nie CWD) — skrypty znajdą `data/`/`docs/` także uruchamiane z roota
> (`python src/main.py`). Konwencja `cd src && python ...` nadal obowiązuje
> w workflow i przykładach poniżej.

```bash
pip install -r requirements.txt

cd src
python main.py              # pełny skan (~9 min): scraping → przetwarzanie → zapis
python map_generator.py     # generuje docs/data.json (+ monitoring + debug)
python api_generator.py     # generuje docs/api/*.json
python top5_generator.py    # generuje docs/top5_data.json

# Podgląd frontendu:
cd ../docs && python -m http.server 8000   # http://localhost:8000
```

Skrypty pomocnicze (`src/`):
- `quick_scan.py --force` — skan 5 stron z **wyczyszczeniem całej bazy** (do
  szybkich napraw). Bez `--force` odmawia działania — bezpowrotnie kasuje
  historię cen, `first_seen` i oferty nieaktywne.
- `test_scan.py` — test 5 ofert z pierwszej strony (zapis do `/tmp`).
- `remove_listing.py <offer_id>` — ręczne ukrycie oferty (lista `removed_listings.json`).
- `fix_missing_coords.py [--dry-run] [--active-only]` — dogeokoduj oferty bez GPS.

## Testy

Suite **pytest** w katalogu `tests/` (95 testów; uruchamiana też w CI przez
`.github/workflows/tests.yml` na każdym push/PR dotykającym `src/`). Pokrywa
parsery, geokoder (limit geokodowań, TTL null-cache, fleksja), ochronę przed
masową dezaktywacją, logikę aktualizacji cen, atomowe zapisy JSON i mapowanie
statusów skanu w API:

```bash
pip install -r requirements.txt pytest
pytest                 # z katalogu głównego repo (nie z src/)
```

Dodatkowo każdy moduł ma wbudowane testy `if __name__ == "__main__"`
(uruchamiane z `src/`, drukują licznik `OK / FAIL`):

```bash
cd src
python address_parser.py   # ekstrakcja adresów
python geocoder.py         # fleksja/fallbacki (bez live Nominatim)
python price_parser.py     # parsowanie cen
```

> Uwaga: część inline-testów `price_parser.py`/`address_parser.py` ma znane,
> historyczne FAIL-e (zaszłość „pokojowa"). Miarodajna jest suite `pytest`.
> Po zmianach w parserze/geokoderze **zawsze** odpal `pytest`.

## Pułapki i konwencje (WAŻNE)

1. **Stabilne ID = `CID3-IDxxxx`**, nie pełny slug URL. Sprzedawca może edytować
   tytuł, co zmienia slug. Funkcja `extract_cid()` wyciąga stabilny identyfikator.
   Używaj go do każdego porównywania ofert (dedup, dezaktywacja, reaktywacja).

2. **Współrzędne są w `offer['address']['coords']`**, nie w top-level `coordinates`.
   To był realny bug (każde geocode robione od nowa).

3. **Zabezpieczenie przed masową dezaktywacją** (`main.py` →
   `_deactivation_block_reason`, testy w `tests/test_main_scan.py`): jeśli scraper
   zwróci 0 ofert lub <30% wcześniejszej liczby aktywnych, system **nie**
   dezaktywuje ofert (zakłada blokadę OLX/Cloudflare). Blokada jest logowana jako
   błąd skanu → API/aplikacja pokazują ⚠️ warning. Nie usuwaj tej ochrony.

4. **Limit geokodowań** `MAX_NEW_GEOCODES = 150` na skan (Nominatim ~1 req/s),
   egzekwowany flagą `geocoder._geocoding_limited` (od 2026-06-12 faktycznie
   czytaną w `_try_nominatim`; tryb limited = tylko cache, bez zatruwania
   None-ami). Cache (`data/geocoding_cache.json`) ma TTL dla negatywnych wpisów
   (7 dni); świeży null = tryb cache-only, bez ponownych zapytań live.

5. **Geokoder zna polską fleksję** — transformuje dopełniacz→mianownik
   („Puławskiej" → „Puławska"), warianty l. mnogiej/pojedynczej, fallback „sama
   ulica bez numeru". Nie upraszczaj tej logiki bez testów — łapie ~40% adresów.

6. **`EXCLUDED_WORDS`** w `address_parser.py` to czarna lista słów, które nie mogą
   być nazwą ulicy (dzielnice, instytucje, słowa „mieszkaniowe"). Dodając wpisy
   pamiętaj: wszystko **lowercase**.

7. **Konwencja komentarzy historycznych**: zmiany oznaczaj datowanym komentarzem
   `# FIX YYYY-MM-DD: opis` lub `# OPTYMALIZACJA YYYY-MM:` przy zmienianym kodzie,
   a istotne zmiany dopisuj do `CHANGELOG.md`.

8. **Po każdym mergu** dopisz wpis do `CHANGELOG.md` opisujący co zostało zmienione
   (sekcja `## [Niewydane]` → odpowiedni podtytuł: `Naprawione`, `Dodane`, `Zmienione`).
   Commit z wpisem pushuj bezpośrednio na `main`.

9. **Workflow CI używa `secrets.PAT_TOKEN`** (nie domyślnego `GITHUB_TOKEN`).
   `scanner.yml` ma `concurrency: sonar-scanner` — nigdy dwa skany równolegle.

10. **Zapisy JSON przez `atomic_json.atomic_write_json`** (tmp + `os.replace`),
    nie goły `json.dump` do pliku docelowego. Uszkodzony `data/offers.json`
    **przerywa skan** (`RuntimeError`) zamiast cichego startu od pustej bazy —
    przywróć plik z gita, nie obchodź tego zabezpieczenia.

11. **Frontend: wszystko co scrapowane z OLX** (opisy, adresy, URL-e) przed
    wstawieniem do `innerHTML` musi przejść przez `escapeHtml()`/`safeUrl()`
    (zdefiniowane w `docs/assets/script.js` i `market_analysis.html`) — to dane
    od obcych użytkowników, inaczej XSS.

12. **Harmonogram skanów: 9:17 / 15:17 / 21:17** (cron `17 7,13,19 * * *`,
    minuta 17 = off-peak). Zmieniając cron zaktualizuj też
    `main._calculate_next_scan_time`, `api_generator.SCAN_SCHEDULE` i README.

## Konwencja commitów

Format `typ(zakres): opis` po polsku, np.:
`fix(scanner):`, `feat(market):`, `perf:`, `monitoring:`, `hotfix:`.
Skany automatyczne commitują jako `🤖 Automatyczny scan: <data>`.

## Czego NIE robić

- Nie zmieniaj ścieżek względnych bez sprawdzenia wszystkich wywołań.
- Nie commituj sekretów (workflow polega na `PAT_TOKEN` z ustawień repo).
- Nie usuwaj zabezpieczenia przed masową dezaktywacją ofert.
- Nie modyfikuj ręcznie `data/offers.json` — to plik generowany przez skan.
