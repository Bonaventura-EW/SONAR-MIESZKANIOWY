# Changelog

Wszystkie istotne zmiany w projekcie SONAR MIESZKANIOWY.

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Daty w formacie RRRR-MM-DD (strefa Europe/Warsaw).

> Wpisy do 2026-05-22 zrekonstruowano z datowanych komentarzy `# FIX` w kodzie
> (historia gita w tym klonie sięga 2026-05-23). Od tej daty źródłem są commity.

## [Niewydane]

### Dodane (2026-08-07) — sprzątanie warstwy „bez lokacji"
- **Odzysk ulicy z zaśmieconej etykiety** (`main._salvage_street_label`). Gdy
  geokoder nie umie umiejscowić adresu, obcinamy człony z końca nazwy, aż zostanie
  ulica z whitelisty OSM: „PeowiakówZdjęcia są" → „Peowiaków", „Piłsudskiego Okna"
  → „Piłsudskiego", „Obywatelska piętro 10" → „Obywatelska". Na obecnej bazie
  **7 ofert wraca z listy „bez lokacji" na mapę**. Uruchamiane wyłącznie dla ofert
  bez współrzędnych, więc nie może przesunąć żadnej istniejącej pinezki.
  Zabezpieczenia (każde z realnego przypadku): nie skracamy nazwy, która **w całości**
  jest poprawna („Osiedle Klemensa Junoszy" nie może stać się „Osiedle Klemensa"),
  odrzucamy krótkie jednoczłonowe trafienia whitelisty („Residence" ⊂ „Wikana
  Residence") i wymagamy wielkiej litery na początku.
- **`_update_existing_offer`: zdobycie współrzędnych zawsze jest poprawą.** Bez tego
  odzysk nie dotarłby do ofert już w bazie — dotychczasowe warunki „lepszości"
  wymagały dodania numeru albo śmieciowego starego adresu.
- **Warstwa „bez lokacji" nie udaje adresu tam, gdzie go nie ma.** Etykiety typu
  „Umowa", „DOSTĘPNE", „Nowoczesne" (39 z 73 kart) to resztki po parserze — karta
  pokazuje teraz „Adres nieznany", a surowy odczyt ląduje pod spodem jako szara
  wskazówka diagnostyczna („parser odczytał: …"), żeby nie tracić informacji.
  Bump `script.js?v=16` → `v=17`.
- **Naprawiona niespójność wprowadzona przez ten odzysk** (złapana przy weryfikacji
  na produkcji): blok „uzupełnij brakujące coords" wstawiał punkt do STAREGO adresu,
  przez co warunek „zdobyto współrzędne" już nie działał — 8 ofert wylądowało na
  mapie z etykietą „Piłsudskiego Okna" i `precision='none'`, więc frontend nie
  wiedział, jakim markerem je narysować. Stan „miał coords" jest teraz zapamiętywany
  przed kopiowaniem, precyzja idzie w parze ze współrzędnymi, a
  `_backfill_address_precision` traktuje `none` przy istniejących coords jako
  niespójność do przeliczenia (rekordy z bazy naprawią się przy kolejnym skanie).
- 13 nowych testów; suite 201 → 217.

### Zmienione (2026-08-07) — oferty bez adresu zostają na stronie
- **`main._process_offer` nie kasuje już oferty, gdy parser nie znajdzie ulicy.**
  Dotąd `return None` sprawiał, że **~34 ogłoszenia na skan znikały ze strony bez
  śladu** — a to normalne oferty, tyle że sprzedawca nie podał w treści żadnej
  ulicy („Kawalerka dla studenta w świetnej lokalizacji!"). Teraz dostają pusty
  adres (`precision='none'`) i trafiają do istniejącej warstwy **„bez lokacji"**
  pod mapą: są widoczne, klikalne i wchodzą do statystyk cenowych. Zweryfikowane
  na realnej próbce: **27 z 27** wcześniej odrzuconych ofert zostaje na stronie.
- **Zakładka debugowa (`docs/skipped_debug.html`) pokazuje je jako diagnostykę,
  nie jako straty.** Kategoria „bez adresu" ma nową etykietę („na stronie, bez
  pinezki"), opis mechanizmu i informację, że pozostałe kategorie (duplikat, brak
  ceny) nadal oznaczają pominięcie. Dzięki temu regresja parsera dalej rzuca się
  w oczy — zmienia się tylko to, że nie kosztuje już utraty ogłoszeń.
- **Pusty adres nie dziedziczy cudzych współrzędnych.** Optymalizacja „ten sam
  adres → użyj zapisanych coords" porównywała `address_full`, więc dwie oferty
  bez ulicy („" == „") mogłyby dostać ten sam punkt na mapie. Dodany warunek
  niepustego adresu.
- **Nowa statystyka `no_address_kept`** w logu skanu (osobno od `skipped_*`), na
  niej opiera się teraz bezpiecznik `MAX_NO_ADDRESS_RATIO` — jego znaczenie
  zmieniło się z „ile ofert straciliśmy" na „ile ofert nie ma lokalizacji".
- 4 nowe testy (`tests/test_offer_without_address.py`); suite 197 → 201.

### Dodane (2026-08-07)
- **`src/clean_geocoding_cache.py` — sprzątanie cache geokodera ze śmieciowych
  kluczy**, wpięte w skan (`main._clean_geocoding_cache`, idempotentne). Powód:
  `AddressParser` buduje whitelistę `_known_streets` **z kluczy cache'u**, więc
  każdy zgeokodowany śmieć („pod nr 60", „Duze nowoczesne 2", „Dostępne 15")
  stawał się „znaną ulicą" i uwiarygadniał kolejne takie parsowania — pętla
  sprzężenia zwrotnego. Usuwane są wyłącznie klucze, których **nie używa żadna
  oferta** i które nie odpowiadają realnej ulicy Lublina (z uwzględnieniem
  odmiany), więc operacja z definicji nie rusza pinezek. Na obecnej bazie: 122
  klucze z 2022; zero osieroconych adresów, parser zwraca identyczne wyniki.
  Ręcznie: `cd src && python clean_geocoding_cache.py [--apply]`.

### Zmienione (2026-08-07)
- **Udokumentowany wynik negatywny: przecinek między ulicą a numerem.**
  Dopuszczenie „ul. Skibińskiej, 20" w `ADDRESS_PATTERN` wygląda na oczywistą
  poprawkę, ale w polskich ogłoszeniach przecinek kończy człon zdania — pomiar na
  całej aktywnej bazie dał 7 nowych numerów i **wszystkie 7 fałszywych**:
  „Skibińskiej, 20 m" i „Chopina, 50 m2" (metraż), „Legionowa, 20-053 Lublin"
  (kod pocztowy), „Litewskiego, 10 min. do UMCS" i „Medycznego, 20 minut" (czas
  dojścia), „Nałkowskich, 3 oddzielne pokoje" i „Filaretów, 2 pokoje" (liczba
  pokoi). Zmiana wycofana, powód zapisany w komentarzu przy `ADDRESS_PATTERN`
  i w 5 testach regresyjnych, żeby nikt nie próbował tego ponownie.

### Weryfikacja na produkcji (skan 2026-08-07 07:26, pierwszy po merge PR #7)
- Migracja adresów wykonała się raz (`address_parser_version: 2026-08-06`).
- Audyt pinezek na żywych danych: **87,3% pod właściwym budynkiem** (przed: 78,3%),
  mediana błędu 2,4 m; fałszywa precyzja **51 → 7**, adresy-widma **41 → 21**,
  pinezki „środek ulicy" udające dokładne **21 → 8**, niespójne `has_number` **4 → 0**.
- Ofert nie ubyło: aktywne 703 → **715**, a `skipped_no_address` spadło **42 → 31**
  (ratunki z tytułu i `extract_street_only` odzyskują oferty, które wcześniej
  znikały ze strony). Skan bez błędów, bezpiecznik `MAX_NO_ADDRESS_RATIO` nie
  zadziałał (31/761 = 4,1%).

### Naprawione (audyt pinezek 2026-08-06)
- **Parser przestał dorabiać numery domów z innego zdania.** `ADDRESS_PATTERN`
  łapie „ul. ZANA Mieszkanie 2" jako ulicę „ZANA Mieszkanie" + numer „2”; logika
  odcinania słów-śmieci z końca nazwy (FIX 2026-05-16) zostawiała numer, choć po
  odcięciu należał on już do innego zdania („2-pokojowe”, „34 m2”, „dostępne od 1”).
  Teraz odcięcie ogona ⇒ `number=None`, `has_number=False` — zostaje sama ulica.
  Dodatkowo numer w formie metrażu („55m”, „40m2”) nigdy nie jest numerem domu.
  Zmierzone na całej bazie (2890 ofert): **0 utraconych adresów**, 129 poprawionych
  zapisów, 40 z 51 ofert z „fałszywą precyzją” naprawionych, zero regresji wśród
  232 pinezek stojących dziś poprawnie.
- **`extract_from_whitelist` był niedeterministyczny.** Przy dwóch znanych ulicach
  o nazwach tej samej długości („Wrotków” vs „Fulmana”, „Spokojnej” vs „Stokrotka”)
  zwycięzcę wybierała kolejność iteracji po zbiorze `_known_streets`, czyli
  `PYTHONHASHSEED` — ten sam opis dawał różny adres w różnych uruchomieniach skanu,
  a pinezka skakała po mapie. Remis rozstrzyga teraz: dłuższa nazwa → wcześniejsza
  pozycja w tekście → alfabetycznie.
- **`has_number` liczone z adresu, który faktycznie wygrał geokodowanie** (mógł to
  być wariant bez numeru z `alternatives`), a nie z głównego kandydata parsera.
  6 aktywnych ofert miało `has_number=True` przy `number=None` — i kroplę „adres
  dokładny" na mapie.

### Dodane
- **Adres brany NAJPIERW z tytułu, dopiero potem z treści ogłoszenia**
  (`main._address_from_title`). Wcześniej tytuł był po prostu doklejany do opisu
  (`full_text = title + " " + description`), więc nie miał żadnego pierwszeństwa —
  a to on jest pisany świadomie („Cyrkoniowa 7 - kawalerka do wynajęcia") i nie ma
  w nim zdań, z których parser sklei pseudo-adres. Wynik z tytułu przyjmujemy
  tylko, gdy nazwa jest realną ulicą/osiedlem Lublina (whitelist OSM) i ma numer
  albo jawny prefiks („ul.", „al.", „os.") — bez tego warunku tytuły typu
  „Nowoczesne mieszkanie 2 pokoje" podstawiałyby śmieci w miejsce dobrego adresu
  z opisu. Gdy tytuł podaje samą ulicę, numer dobieramy z treści, ale wyłącznie
  dla **tej samej ulicy** (porównanie odporne na odmianę: „ul. Głęboka" w tytule +
  „Głębokiej 21" w opisie → „Głęboka 21"). Dochodzi obcinanie reklamowego
  przedrostka („BEZPOŚREDNIO Nałęczowska 20" → „Nałęczowska 20") — tylko gdy ogon
  nazwy jest realną ulicą, więc „Krakowskie Przedmieście" zostaje nietknięte.
  Pomiar na 703 aktywnych ofertach: **22 adresy lepsze, 2 gorsze, 0 utraconych**;
  286 adresów pochodzi teraz z tytułu, 417 z treści.
- **`address['precision']` — mapa przestaje udawać precyzję, której nie ma.**
  Geokoder od dawna zwracał w meta `number_fallback` („nie znalazłem numeru,
  zwracam samą ulicę"), ale `main.py` tę informację wyrzucał, a mapa rysowała
  kroplę po samym `has_number`. Teraz `precision` ('exact' | 'street' | 'none')
  trafia do `offers.json` → `docs/data.json` → frontendu, który po niej wybiera
  kształt markera (`isExactLocation`, `script.js?v=16`); stare rekordy bez pola
  działają po staremu. `_backfill_address_precision()` uzupełnia pole dla ofert
  sprzed zmiany **bez sieci** — punkt identyczny z geokodem samej ulicy = środek
  ulicy, nie budynek. Efekt na obecnej bazie: 18 ofert traci mylącą kroplę,
  aktywne rozkładają się na 273 `exact` / 370 `street` / 60 bez lokacji.
- **Dwa ratunki przed wyrzuceniem oferty ze skanu** (`_process_offer`): parsowanie
  samego **tytułu** (filtry chroniące przed śmieciami z opisu potrafiły skasować
  poprawny adres z tytułu — „Cyrkoniowa 7 - kawalerka…") oraz `extract_street_only`
  (main.py wypisywał w logu „extract_street_only znalazłby: X" i mimo to wyrzucał
  ofertę). Oba przyjmują wynik tylko dla realnej ulicy Lublina — odzyskują ~4 z 37
  ofert gubionych w każdym skanie, bez wpuszczania nowych śmieci.
- **`data/streets_lublin.json` + `src/street_whitelist.py`** — snapshot 1563 nazw
  ulic i osiedli Lublina z OSM (odświeżanie: `python street_whitelist.py --update`).
  Lista służy **wyłącznie do akceptowania** adresów ratunkowych, nigdy do
  odrzucania ofert: pomiar pokazał, że 114 aktywnych ofert ma nazwę spoza listy,
  ale kilkadziesiąt z nich to prawdziwe adresy, których OSM nie ma w formie użytej
  w ogłoszeniu („Osiedle Botanik", „Skłodowskiej", „Aleja Racławickiej").
- **Korekta adresu „w dół" w `_update_existing_offer`.** Dotąd adres był
  nadpisywany tylko wtedy, gdy nowy *dodawał* numer — poprawiony parser nigdy nie
  naprawiłby ofert już w bazie. Teraz przy **identycznej nazwie ulicy** wycofanie
  zmyślonego numeru aktualizuje rekord (i nie przenosi na nowy adres starych
  współrzędnych, bo wskazywały zmyślony budynek). Licznik w podsumowaniu skanu.
- **Bezpiecznik `MAX_NO_ADDRESS_RATIO = 0.20`** (`_no_address_alert`). Oferta bez
  rozpoznanego adresu nie trafia na stronę w ogóle, więc regresja parsera potrafi
  po cichu wyciąć setki ogłoszeń, a skan i tak kończy się „✅ sukces". Zdrowy skan
  gubi ~5,5% ofert (42 z 767); przekroczenie 20% loguje błąd skanu → monitoring
  pokazuje ⚠️ (ten sam mechanizm co ochrona przed masową dezaktywacją).
- **Korpus regresyjny parsera** (`tests/data_address_corpus.json`, 120 realnych
  opisów) + `tests/test_address_regression.py` i `tests/test_address_precision.py`.
  Każda przyszła zmiana parsera, która zgubi albo przekręci adres, wywala CI.
- **`src/address_migration.py` — jednorazowa migracja adresów w bazie.** Poprawka
  parsera sama naprawia tylko oferty, które scraper widzi w listingu; **nieaktywne**
  (2187 rekordów, wchodzą do mapy historycznej i analiz cen po adresach) zostałyby
  ze zmyślonym numerem na zawsze. Opis oferty jest w bazie, więc adres przeliczamy
  z zapisanego tekstu — **bez ani jednego zapytania do Nominatim**: punkt ulicy
  bierzemy z `geocoding_cache.json`, a gdy go tam nie ma, zostawiamy dotychczasowe
  współrzędne (realny budynek przy tej samej ulicy) i obniżamy `precision`.
  Korekta działa wyłącznie przy **identycznej nazwie ulicy** — nigdy nie przenosi
  oferty pod inny adres (76 takich przypadków świadomie pominiętych). Bezpiecznik
  `MAX_RETRACTION_RATIO = 0.25` blokuje migrację, gdyby parser chciał przepisać
  pół bazy (wtedy wersja nie jest stemplowana i próba powtórzy się po naprawie).
  Migracja odpala się raz w skanie (`main._migrate_legacy_addresses`, stempel
  `address_parser_version` w bazie); ręczny podgląd: `python address_migration.py`
  (sucha próba) / `--apply`.
  Efekt na bazie 2026-08-06: **127 poprawionych adresów (43 aktywne + 84 nieaktywne)**,
  0 ofert utraconych, 0 ofert bez współrzędnych. Audyt pinezek przed → po:
  pinezka pod właściwym budynkiem **78,3% → 86,1%**, fałszywa precyzja **51 → 10**,
  adresy-widma **41 → 21**, pinezki na środku ulicy udające dokładne **21 → 12**.
- **`audit_map_placement.py --offers PATH`** — audyt na dowolnym pliku bazy
  (do porównań przed/po migracją). Suite 135 → 173 testy (przechodzą przy
  dowolnym `PYTHONHASHSEED`).
- **`src/audit_map_placement.py` — audyt jakości umieszczenia pinezek na mapie.**
  Mapa rysuje „kroplę" (adres dokładny) dla każdej oferty z `has_number=True`,
  nie sprawdzając, czy geokoder trafił w budynek. Skrypt weryfikuje to dwoma
  niezależnymi źródłami OSM: Overpass (punkty adresowe Lublina → dystans pinezki
  od budynku o tym numerze) i Nominatim reverse (co faktycznie stoi w punkcie
  pinezki), plus sprawdza, czy para „ulica numer" w ogóle występuje w treści
  ogłoszenia. Werdykty: `DOKLADNA`, `SASIEDNI_BUDYNEK`, `PRZESUNIETA`,
  `SRODEK_ULICY`, `BRAK_NUMERU`, `ZLA_ULICA`, `ADRES_WIDMO`, `BRAK_GPS`
  + osobna sekcja `FALSZYWA_PRECYZJA`. Cache danych OSM leży poza repo
  (katalog tymczasowy), więc `--offline` powtarza audyt bez sieci.
  Wynik pierwszego przebiegu (2026-08-06, 322 aktywne oferty z `has_number`):
  252 (78%) pinezek stoi na właściwym budynku (mediana błędu 1,6 m), ale tylko
  232 (72%) ma jednocześnie numer potwierdzony w treści ogłoszenia; 51 ofert ma
  numer dorobiony przez parser z innego zdania („2-pokojowe" → „Zana 2",
  „34 m2" → „Nałęczowska 34", „dostępne od 1" → „Wolne 1"), 16 ma ulicę
  nieistniejącą w Lublinie, 26 nie ma GPS.
- **Auto-retry skanu przy blokadzie OLX/Cloudflare** (`main.run_scan_with_retry`).
  Gdy scraper zwróci 0 / podejrzanie mało ofert (ten sam warunek co ochrona przed
  masową dezaktywacją, `_deactivation_block_reason`), skan czeka 2 min
  (`RETRY_ON_BLOCK_WAIT_SECONDS = 120`) i ponawia próbę — do 2 dodatkowych podejść
  (`RETRY_ON_BLOCK_MAX_RETRIES = 2`). Blokada bywa chwilowa (rate limit), a pełny
  cykl to tylko 3×/dzień, więc jeden strzał po 2 min ratuje skan zamiast czekać
  ~5 h do następnego harmonogramu. `run_scan()` zwraca teraz `scrape_blocked`;
  każda próba loguje osobny wpis w `scan_history` (widoczny w monitoringu).
  Ochrona przed dezaktywacją nie jest tym omijana — dopóki ofert jest za mało,
  dezaktywacja pozostaje pominięta. `scanner.yml` bez zmian (retry dzieje się
  wewnątrz procesu `main.py`). 4 nowe testy (`tests/test_main_scan.py`).
- **Nowa podstrona „Indeks podaży"** (`docs/trend.html`) — port `trend.html`
  z `SONAR-POKOJOWY`. Dwa wykresy ApexCharts:
  - *Indeks podaży* — dzienna rekonstrukcja liczby żywych ofert
    (`first_seen ≤ dzień ≤ last_seen`), z liniami MAX/MIN i zmianami 1D/1M/6M/1Y
    (6M/1Y = „—" dopóki nie uzbieramy historii). Analog indeksu z betonometr.pl.
  - *Odpływ ofert* — ile ofert znikło danego dnia + średnia krocząca 7 dni.
  - `src/trend_generator.py` — rekonstrukcja z `data/offers.json` →
    `docs/trend_data.json` (zapis atomowy przez `atomic_json`). Seria startuje
    16.05.2026: wcześniejsze dni są zaniżone, bo do tego dnia parser adresów
    odrzucał setki ofert na skan (patrz wpis `[2026-05-16]`).
  - Wpięty w `scanner.yml` (po `area_price_generator`) i w commit skanu.
  - Link „📉 Indeks" w nawigacji mapy, Top 5 i strony debugowej.
  - 12 nowych testów (`tests/test_trend_generator.py`); suite 118 → 130.
- **Szablon PR** (`.github/pull_request_template.md`) — stała struktura opisu
  zmiany: co się zmienia / dlaczego / changelog / testy / weryfikacja, plus
  checklista pułapek projektu (ID `CID3`, `address.coords`, próg dezaktywacji,
  limit geokodowań, `atomic_write_json`, `escapeHtml`, `paths.py`, harmonogram
  skanów, wpięcie nowego generatora w `scanner.yml`). GitHub wypełnia nim
  automatycznie opis każdego nowego PR-a.

### Naprawione
- **Domknięcie „martwej strefy" ochrony przed masową dezaktywacją** — próg
  `MIN_DEACTIVATION_RATIO` podniesiony **0.3 → 0.6**. Zdrowy skan zwraca ~770 ofert
  przy ~710 aktywnych (ratio ~1.08), więc próg 0.3 (≈212) łapał tylko drastyczne
  blokady (0/42/93 oferty). *Częściowa* blokada zwracająca ~połowę ofert
  prześlizgiwała się pod progiem — realny incydent **2026-08-05 06:31**: scraper
  zwrócił 365 ofert przy 706 aktywnych (ratio 0.52), przez co system dezaktywował
  **409 realnych ofert** (aktywne 706 → 349). Próg 0.6 (≈424) łapie taki przypadek,
  zachowując ogromny margines do zdrowego ratio ~1.08 (zero fałszywych trafień na
  historycznych zdrowych skanach). Częściowa blokada trafia teraz też w auto-retry
  (wyżej). Zaktualizowano `CLAUDE.md` pkt 3, checklistę w szablonie PR (30% → 60%)
  i testy (`tests/test_main_scan.py`). Łączna suite z auto-retry: 130 → 135.

### Zmienione
- **`CLAUDE.md`: changelog czytany na starcie sesji, nie tylko dopisywany na
  końcu.** Nagłówek pliku i pkt 8 „Pułapek" wymagają teraz przeczytania sekcji
  `## [Niewydane]` przed pracą (kontekst ostatnich zmian) oraz dopisania wpisu
  **w tym samym PR-ze**, co zmiana — zamiast osobnego commita „po fakcie".
- **Główna mapa renderuje markery na JEDNYM `<canvas>` (L.canvas) zamiast ~1500
  węzłów DOM (L.divIcon).** Port mechanizmu z `SONAR-POKOJOWY`. Markery to
  kształty wektorowe — rozszerzenia `L.CircleMarker` (`PinMarker` = kropla dla
  dokładnego adresu, `SquareMarker` = kwadrat z przerywaną ramką dla adresów
  przybliżonych, decyzja po `has_number`) ze wspólnym `renderer: canvasRenderer`.
  Każda klasa nadpisuje `_updatePath` (rysowanie kropli/kwadratu + białe kółko
  w środku, `×` dla nieaktywnych, badge `N`/`↓`/`↑` w rogu), `_updateBounds`
  (culling) i `_containsPoint` (ręczne pole kliknięcia popupu — bąbel kropli
  r=19 px, kwadrat ±16 px). Dodano `restackCanvasOrder()` utrzymujący z-order
  (aktywne pinezki > aktywne kwadraty > nieaktywne) po przebudowie/filtrowaniu.
  Efekt: płynny pan/zoom i filtrowanie przy ~1500 ofertach, bez klastrowania.
  Zachowane bez zmian: lazy popup, debounce filtrów, wszystkie warstwy/filtry,
  suwak dni, wyszukiwarka, deep-link `?offer=`, statystyki i escapowanie XSS.
- **Sprzątnięcie martwego CSS po `divIcon`.** Usunięto z `assets/style.css`
  nieużywane już klasy markerów (`.pin-wrap`, `.square-wrap`, `.pin-svg`,
  `.square-svg`, `.marker-badge*`, `.pin-marker`, `.square-marker`) — markery
  rysuje teraz canvas, więc nic ich nie referuje. Bump `style.css?v=2` → `v=3`.

## [2026-06-18]

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
- **Nowa podstrona „Analiza cen wg metrażu"** (`docs/analiza_metraz.html`).
  Analizuje treść ogłoszeń: cena za m², przedziały cenowe wg metrażu, podział
  na dzielnice, mapa cieplna dzielnica×metraż, korelacja powierzchnia-cena,
  trend zł/m² w czasie, rozkład stawek i zestawienia tabelaryczne. Dostępna z
  nawigacji (mapa + Top 5). Dane liczone z **całej historii** ofert:
  - `src/area_parser.py` — ekstrakcja metrażu (m²), liczby pokoi i dzielnicy
    z opisów/adresów (regex + walidacja zakresów). Pokrycie metrażem ~63% bazy.
  - `src/area_price_generator.py` — agregacja → `docs/area_price_data.json`
    (zapis atomowy). Wpięty w `scanner.yml` (po `top5_generator`) i commit.
  - 23 nowe testy (`tests/test_area_parser.py`, `tests/test_area_price_generator.py`);
    suite 95 → 118.

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
