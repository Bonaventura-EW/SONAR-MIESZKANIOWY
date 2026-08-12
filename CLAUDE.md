# CLAUDE.md

Wytyczne dla Claude Code (i innych agentów) pracujących w tym repozytorium.
Czytaj ten plik na starcie każdej sesji — opisuje jak projekt działa, jak go
uruchomić i jakich pułapek unikać.

> 📓 **Na starcie każdej sesji przeczytaj też `CHANGELOG.md`** (co najmniej
> sekcję `## [Niewydane]` i 2–3 ostatnie wydania) — to najświeższy zapis tego,
> co i dlaczego zmieniło się w projekcie. A na końcu każdej zmiany **dopisz do
> niego wpis** (szczegóły w „Pułapki i konwencje" pkt 8).

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
trend_generator.py    → docs/trend_data.json    (indeks podaży + odpływ)
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
python trend_generator.py   # generuje docs/trend_data.json

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
   zwróci 0 ofert lub <60% wcześniejszej liczby aktywnych (`MIN_DEACTIVATION_RATIO`),
   system **nie** dezaktywuje ofert (zakłada blokadę OLX/Cloudflare). Blokada jest
   logowana jako błąd skanu → API/aplikacja pokazują ⚠️ warning. Nie usuwaj tej
   ochrony. **Auto-retry** (2026-08-05): po wykryciu blokady `run_scan_with_retry`
   czeka 2 min i ponawia skan (do 2 dodatkowych prób) — próg 0.6 łapie też
   *częściową* blokadę (~połowa ofert), która wcześniej pod progiem 0.3
   dezaktywowała setki realnych ofert.

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

8. **`CHANGELOG.md` czytaj na starcie, dopisuj na końcu.** Przed pracą przeczytaj
   sekcję `## [Niewydane]` i ostatnie wydania — tam jest kontekst ostatnich zmian.
   Każdą istotną zmianę opisz w `## [Niewydane]` → odpowiedni podtytuł
   (`Dodane`, `Naprawione`, `Zmienione`, `Wydajność`). Wpis ma być **częścią
   PR-a ze zmianą** (patrz `.github/pull_request_template.md`), a nie osobnym
   commitem „po fakcie". Jeśli zmiana poszła bez PR-a — commit z wpisem pushuj
   bezpośrednio na `main`.

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

13. **Kolejność źródeł adresu: TYTUŁ → pełny tekst → sam opis → ratunki.**
    Tytuł ma pierwszeństwo (`main._address_from_title`), ale tylko gdy nazwa jest
    realną ulicą z whitelisty OSM i ma numer albo jawny prefiks „ul./al./os.";
    brakujący numer dobieramy z treści wyłącznie dla tej samej ulicy. Nie zmieniaj
    tej kolejności bez pomiaru na całej bazie (patrz pkt 14).

14. **Zaostrzając parser adresów pamiętaj: brak adresu = oferta znika ze strony**
    (`main._process_offer` → `return None`). Każdą zmianę w `address_parser.py`
    zmierz na całej bazie („ile adresów ubyło?") i puść `pytest` — korpus
    regresyjny (`tests/data_address_corpus.json`, 120 realnych opisów) wywala się,
    gdy adres zniknie lub się przekręci. W skanie pilnuje tego bezpiecznik
    `MAX_NO_ADDRESS_RATIO` (20% odrzuconych → błąd skanu i ⚠️ w monitoringu).
    Whitelist ulic (`street_whitelist.py`, `data/streets_lublin.json`) służy
    **tylko do akceptowania** adresów ratunkowych — nigdy do odrzucania ofert,
    bo ~30 realnych adresów z ogłoszeń nie występuje w OSM w takiej formie.

15. **Zmieniając parser adresów bumpnij `address_migration.ADDRESS_PARSER_VERSION`** —
    inaczej poprawka ominie oferty już w bazie, a zwłaszcza **nieaktywne** (scraper
    ich nie odwiedza, więc `_update_existing_offer` się dla nich nie uruchomi).
    Migracja (`main._migrate_legacy_addresses`) przelicza adres z opisu zapisanego
    w bazie, działa bez sieci i tylko przy identycznej nazwie ulicy. Podgląd przed
    zmianą: `cd src && python address_migration.py` (sucha próba).

16. **O kształcie markera decyduje `address['precision']`, nie `has_number`**
    ('exact' = pinezka pod budynkiem, 'street' = kwadrat na środku ulicy,
    'none' = warstwa „bez lokacji"). Ustawia je `main._address_precision` z meta
    geokodera (`number_fallback`), a dla starych rekordów offline'owy
    `_backfill_address_precision`. Frontend czyta je przez `isExactLocation()`
    z fallbackiem do `has_number` — zmieniając kontrakt bumpnij `script.js?v=`.
    Kontrolę jakości pinezek robi `src/audit_map_placement.py --offline`.

17. **W `street_whitelist.py` strona ZAPYTANIA i strona INDEKSU mają różne reguły.**
    `name_variants` (tekst z ogłoszenia) jest wąskie, `index_variants` (nazwy z OSM)
    szerokie — bo wariant dołożony do zapytania potrafi trafić w *inną* realną nazwę
    („Piastowskie" → „Piastowska"), a dołożony do indeksu tylko dokłada zapis nazwy,
    która i tak istnieje. Nie przenoś przekształceń na stronę zapytania.
    Do tego dwa tryby dopasowania: **po podciągu członów** (`is_known_street`,
    `is_street_name` — ogłoszenia skracają nazwy) i **pełne** (`is_known_place`,
    `is_district_name` — inaczej śmieć „Nowe" broni się podciągiem „Nowe Sady",
    a „Rury Jezuickie" robi dzielnicę z ul. Jezuickiej). Zmieniając którąkolwiek
    z tych reguł zmierz przejścia KEEP/CLEAN/DEMOTE na całej bazie: dozwolone są
    tylko KEEP→CLEAN i KEEP→DEMOTE — realna ulica nigdy nie może stracić pinezki.

18. **`extract_address` ma cztery ścieżki i każdy filtr musi obowiązywać we wszystkich.**
    Kolejność: kandydaci `ADDRESS_PATTERN` → fallback nazwiskowy
    (`POLISH_SURNAME_PATTERN`) → `extract_street_only` → `extract_from_whitelist`.
    Fallback nazwiskowy przez lata omijał filtry ścieżki głównej i wpuszczał z powrotem
    adresy dopiero co odrzucone („Powierzchnia 32" z metrażu, „Nałęczowska 2" z czasu
    dojścia). Dokładając filtr do ścieżki głównej **sprawdź, czy nie trzeba go dodać
    również tam** — i pamiętaj, że tylko ten fallback zwraca `has_number=True`, czyli
    jego błąd od razu daje na mapie „adres dokładny". Regułę przymiotnikową
    (przymiotnik ≠ ulica) trzymaj wyłącznie za publicznym `is_adjectival_label`
    — to ono składa `_boundary_text` i `_capitalized_words`. Poza parserem
    (np. `address_migration`) **nigdy** nie wołaj `_is_adjective_use` wprost:
    trzy poprawki z rzędu (2026-08-10/11) rozjechały się dokładnie na tym, że
    druga strona montowała przesłanki sama i gubiła jedną.

19. **Trafienie Nominatim ≠ trafienie w budynek.** Na adres z numerem, którego nie ma
    w OSM, Nominatim potrafi oddać punkt reprezentatywny ulicy (czasem *innej* —
    „Lubomelskiej 9" → ul. Boczna Lubomelskiej, 142 m od celu) i zaraportować to
    jako sukces. Dlatego zapytania idą z `addressdetails=1`, a `_number_confirmed`
    wymaga zgodnego `house_number`. Odrzucenie **nie gubi oferty** — leci do
    fallbacku „sama ulica" (KROK 4) i wraca z `number_fallback=True`. Nie dodawaj
    tu walidacji nazwy ulicy: odróżnienie „Boczna Lubomelskiej" od legalnego skrótu
    „Chodźki" → „Doktora Witolda Chodźki" wymaga dopasowania ścisłego, które psuje
    skróty, na których stoi parser (zmierzone 2026-08-08).

20. **`reactivated_at` to JEDNA, nadpisywana data — nie buduj z niej szeregu
    dziennego.** Oferta, która wracała trzy razy, pamięta tylko ostatni powrót,
    więc „ile ofert wróciło dnia X" wypłukuje się wraz z wiekiem dnia (zmierzone
    2026-08-09: 15/dzień w połowie lipca vs 85 w dniu pomiaru, przy niezmienionym
    ruchu). Pełną historię trzyma `reactivation_dates` (moduł
    `reactivation_log.py`) — każdy powrót osobno, z długością nieobecności
    (`gap_h`) i źródłem. Dwa filtry, bez których liczby są bez sensu: przerwa
    < 24 h to zgubienie oferty na jeden skan, a `reactivation_source ==
    'verification'` oznacza, że **my** pomyliliśmy się przy dezaktywacji, bo
    ogłoszenie cały czas żyło na OLX (~48 takich na skan wobec 0–9 realnych
    powrotów). Filtruj po stronie generatora, nie przy zapisie — surowe wpisy
    mają zostać nietknięte. Wykresy powrotów w `trend_generator` pokazują tylko
    zmierzony zakres (`measured_from`), a dni-artefakty (`REACTIVATION_ARTIFACT_DAYS`)
    lecą do serii jako `null`.

21. **Ścieżka ratunkowa parsera (route 4, `extract_from_whitelist`) to zgadywanie
    — i tak ją traktuj.** Bierze nazwę z kluczy `geocoding_cache.json`, a cache
    uczy się wszystkiego, co raz się zgeokodowało, łącznie z naszymi błędami.
    Stąd dwa filtry (`_filter_candidates`): kandydat musi być realną ulicą z OSM
    i nie może stać jako przymiotnik przed rzeczownikiem mieszkaniowym
    („przytulna kawalerka"). Reguła przymiotnikowa działa **tylko** dla nazw
    z `_ADJECTIVE_STREETS` — dla nazwisk w dopełniaczu („Narutowicza Mieszkanie"
    to sklejka tytułu z opisem) kasowałaby realne adresy. Czyta tekst z „¶"
    w miejscu interpunkcji, bo bez granic zdań te sklejki są nie do odróżnienia.
    Filtruj KANDYDATÓW, nie zwycięzcę — inaczej śmieć dalej bije realną ulicę
    wymienioną obok. Wymóg wielkiej litery zmierzono i odrzucono (zabiera pinezkę
    ogłoszeniom pisanym małą literą) — szczegóły w `_capitalization_ok`.

## Konwencja commitów

Format `typ(zakres): opis` po polsku, np.:
`fix(scanner):`, `feat(market):`, `perf:`, `monitoring:`, `hotfix:`.
Skany automatyczne commitują jako `🤖 Automatyczny scan: <data>`.

## Czego NIE robić

- Nie zmieniaj ścieżek względnych bez sprawdzenia wszystkich wywołań.
- Nie commituj sekretów (workflow polega na `PAT_TOKEN` z ustawień repo).
- Nie usuwaj zabezpieczenia przed masową dezaktywacją ofert.
- Nie modyfikuj ręcznie `data/offers.json` — to plik generowany przez skan.
