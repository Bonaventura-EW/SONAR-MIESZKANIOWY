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

> ⚠️ **WSZYSTKIE skrypty zakładają uruchomienie z katalogu `src/`.**
> Ścieżki do danych są względne (`../data/...`). Bez `cd src` skrypty nie znajdą plików.

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
- `quick_scan.py` — skan 5 stron z wyczyszczeniem bazy (do szybkich napraw).
- `test_scan.py` — test 5 ofert z pierwszej strony (zapis do `/tmp`).
- `remove_listing.py <offer_id>` — ręczne ukrycie oferty (lista `removed_listings.json`).
- `fix_missing_coords.py [--dry-run] [--active-only]` — dogeokoduj oferty bez GPS.

## Testy

Suite **pytest** w katalogu `tests/` (uruchamiana też w CI przez
`.github/workflows/tests.yml` na każdym push/PR dotykającym `src/`):

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

3. **Zabezpieczenie przed masową dezaktywacją** (`main.py`): jeśli scraper zwróci
   0 ofert lub <30% wcześniejszej liczby aktywnych, system **nie** dezaktywuje ofert
   (zakłada blokadę OLX/Cloudflare). Nie usuwaj tej ochrony.

4. **Limit geokodowań** `MAX_NEW_GEOCODES = 150` na skan (Nominatim ~1 req/s).
   Cache (`data/geocoding_cache.json`) ma TTL dla negatywnych wpisów (7 dni).

5. **Geokoder zna polską fleksję** — transformuje dopełniacz→mianownik
   („Puławskiej" → „Puławska"), warianty l. mnogiej/pojedynczej, fallback „sama
   ulica bez numeru". Nie upraszczaj tej logiki bez testów — łapie ~40% adresów.

6. **`EXCLUDED_WORDS`** w `address_parser.py` to czarna lista słów, które nie mogą
   być nazwą ulicy (dzielnice, instytucje, słowa „mieszkaniowe"). Dodając wpisy
   pamiętaj: wszystko **lowercase**.

7. **Konwencja komentarzy historycznych**: zmiany oznaczaj datowanym komentarzem
   `# FIX YYYY-MM-DD: opis` lub `# OPTYMALIZACJA YYYY-MM:` przy zmienianym kodzie,
   a istotne zmiany dopisuj do `CHANGELOG.md`.

8. **Workflow CI używa `secrets.PAT_TOKEN`** (nie domyślnego `GITHUB_TOKEN`).

## Konwencja commitów

Format `typ(zakres): opis` po polsku, np.:
`fix(scanner):`, `feat(market):`, `perf:`, `monitoring:`, `hotfix:`.
Skany automatyczne commitują jako `🤖 Automatyczny scan: <data>`.

## Czego NIE robić

- Nie zmieniaj ścieżek względnych bez sprawdzenia wszystkich wywołań.
- Nie commituj sekretów (workflow polega na `PAT_TOKEN` z ustawień repo).
- Nie usuwaj zabezpieczenia przed masową dezaktywacją ofert.
- Nie modyfikuj ręcznie `data/offers.json` — to plik generowany przez skan.
