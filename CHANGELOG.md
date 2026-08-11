# Changelog

Wszystkie istotne zmiany w projekcie SONAR MIESZKANIOWY.

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Daty w formacie RRRR-MM-DD (strefa Europe/Warsaw).

> Wpisy do 2026-05-22 zrekonstruowano z datowanych komentarzy `# FIX` w kodzie
> (historia gita w tym klonie sięga 2026-05-23). Od tej daty źródłem są commity.

## [Niewydane]

### Podsumowanie rundy „jakość pinezek" (2026-08-06 → 2026-08-09)
Punktem wyjścia był audyt umieszczenia pinezek na mapie. Poniższe wpisy opisują
kolejne poprawki osobno; tu jest całość w jednym miejscu, razem z liczbami przed
i po (wszystkie zmierzone na produkcji, nie szacowane).

| | start (2026-08-06) | teraz (2026-08-09) |
|---|---|---|
| pinezka pod właściwym budynkiem | 78,3% | **87,3%** |
| mediana odległości od budynku z OSM | — | **2,1 m** |
| fałszywa precyzja (numer dorobiony z innego zdania) | 51 | **10** |
| adresy widmo („ulica", której nie ma w Lublinie) | 41 | **18** |
| pinezka = geokod samej ulicy, udająca dokładny adres | 21 | **8** |
| niespójne `has_number` | 4 | **0** |
| pinezki stojące na nazwie, która nie jest ulicą | 22 | **1** (świadomie zostawiona) |
| oferty tracone przez parser przy każdym skanie | ~34 | **0** |
| oferty aktywne | 703 | **711** |
| testy | 135 | **356** |

Wątek przewijający się przez całą rundę: **pojedyncza reguła prawie zawsze cofała
którąś z wcześniejszych poprawek.** Stąd trzy zasady zapisane w `CLAUDE.md`
(pkt 17–19) i konsekwentny tryb pracy — każda zmiana mierzona na całej bazie
(~2900 ofert) przed wdrożeniem, z dozwolonymi tylko jednokierunkowymi przejściami
(śmieć → ulica, nigdy odwrotnie).

**Zmierzone i świadomie NIEzrobione** (szczegóły w odpowiednich wpisach niżej) —
zapisane, żeby nikt nie próbował ich drugi raz:
- walidacja nazwy ulicy w odpowiedzi Nominatim — wymaga dopasowania ścisłego,
  które psuje skróty, na których stoi parser,
- rozwijanie skróconej nazwy do pełnej z OSM — 1 aktywna oferta zysku,
- szukanie ulicy wymienionej w treści dla ofert ze śmieciową etykietą — niemal
  same fałszywe trafienia, bo nazwy ulic Lublina to zwykłe przymiotniki
  („Dobra", „Cicha", „Widok"), a „Mieszka I" trafia w słowo *mieszka*,
- zaostrzenie `is_known_place` dla ostatniej pinezki na nie-ulicy — kosztowałoby
  etykietę sześciu realnych ulic.

Co zostaje otwarte: 4 pinezki przesunięte mimo potwierdzonego numeru i 2 źle
wybrane ulice — to rozjazd danych między Nominatim a Overpass, nie błąd parsera.
Ich naprawa wymagałaby własnego indeksu punktów adresowych z Overpass
(`audit_map_placement.py` już te dane pobiera i cache'uje).

### Naprawione (2026-08-11) — zablokowany skan nie udaje „Sukces" w monitoringu
Od ~13:00 dnia 2026-08-11 OLX (przez CloudFront) zaczął zwracać `403 Request
blocked` na requesty scrapera — kolejne skany (16:32/16:34/16:36 i
22:05/22:07/22:10, po trzy próby `run_scan_with_retry`) pobierały **0 ofert**.
Bezpiecznik przed masową dezaktywacją zadziałał poprawnie (nic nie
zdezaktywowano, błąd trafił do `scan_history`), ale dashboard monitoringu i tak
świecił się na zielono: kolumna „Status" czytała surowe `scan.status`
(`completed`), a nie fakt, że skan ma wpis w `errors`. Kafelek „Sukces" i
„Success Rate" liczyły blokadę jako sukces (100%).

Teraz status jest **efektywny** — łączy `status` z obecnością błędów, spójnie z
`uiStatus` w API mobilnym:
- `docs/monitoring.html`: skan `completed` z błędem pokazuje **⚠️ Ostrzeżenie**
  (amber), skan przerwany — **❌ Błąd** (czerwony); zielony „Sukces" tylko gdy
  zero błędów. Tooltip błędów czyta `error.message` zamiast `[object Object]`.
- `scan_logger.get_statistics`: `successful` = `completed` **i** zero błędów;
  doszedł osobny licznik `warnings`. Success Rate spadł ze zmyślonych 100% na
  realne 89% (11 zablokowanych skanów w historii).
- `monitoring_generator`: punkt wykresu „success rate" liczy 100% tylko dla
  skanu bez błędów.

Diagnoza samej blokady (403 CloudFront) i obejście — patrz wpis niżej
(impersonacja TLS `curl_cffi`).

### Zmienione (2026-08-11) — impersonacja TLS Chrome'a zamiast gołego requests
Obejście blokady 403 z wpisu wyżej. `requests` wysyła charakterystyczny pythonowy
fingerprint TLS (JA3), który WAF (CloudFront/AWS) potrafi odsiać przy IP
datacenter — a tak właśnie egresuje GitHub Actions. Scraper i weryfikacja
nieaktywnych ofert chodzą teraz przez `curl_cffi` z `impersonate="chrome"`
(ClientHello nieodróżnialny od prawdziwego Chrome'a).

- Nowy `src/http_client.py`: `ImpersonatedSession` — API zgodne z
  `requests.Session` (`.headers`, `.get`, `.close`), pod spodem `curl_cffi`.
  **Fallback**: brak `curl_cffi` (import) albo błąd na poziomie transportu →
  spadamy na `requests`. Odpowiedź 403 to normalny wynik `.get()`, więc blokada
  jest nadal wykrywana jako 0 ofert (bezpiecznik dezaktywacji bez zmian).
- **Wątki**: Session `curl_cffi` nie jest thread-safe (jeden uchwyt curl), więc
  każdy wątek puli scrapera dostaje własną sesję (`threading.local`).
- `scraper.py` i `main._verify_inactive_offers` przełączone na `ImpersonatedSession`;
  `except requests.RequestException` → `except http_client.RequestError` (krotka
  wyjątków obu backendów). `curl_cffi==0.16.0` w `requirements.txt`.
- Testy: `tests/test_http_client.py` (fallback, per-wątkowość, nagłówki);
  dwa testy weryfikacji patchują teraz `ImpersonatedSession.get`.

Weryfikacja skuteczności musi iść na produkcji (ręczny `workflow_dispatch`):
egress tego środowiska deweloperskiego re-terminuje TLS, przez co impersowany
handshake i tak pada i wpada w fallback — sprawdzianem jest `offers_found > 0`
w skanie z Actions.

### Naprawione (2026-08-11) — wielkość liter rozstrzyga przy nazwach-przymiotnikach
Audyt po skanie: „Przytulna" zeszła z mapy, ale zostało 13 aktywnych ofert
z etykietą typu „Spokojna"/„Nowe" wziętą z **„nowe wyposażenie"**, **„przy
spokojnej ulicy"**, **„mile widziana spokojna, pracująca para"**. Reguła
przymiotnikowa ich nie łapała, bo rzeczownik („wyposażenie", „ulica", „para")
nie mieści się w żadnej sensownej liście — takich słów są setki.

- **Dla nazw z `_ADJECTIVE_STREETS` decyduje teraz także wielkość liter**: jeśli
  nazwa w całym ogłoszeniu pisana jest małą literą, to zwykły przymiotnik, nie
  ulica. „ulica Spokojna" i „ul. Cicha" zostają adresem, „spokojnej okolicy"
  nie. Wymóg **nie** obowiązuje pozostałych nazw — tam ten sam pomysł zmierzono
  wcześniej i odrzucono, bo zabierał pinezkę realnym adresom pisanym małą literą
  („mieszkanie na wynajem unicka", „miasteczko akademickie weteranów 19").

Pomiar wobec wdrożonej wersji (3047 ofert): **KEEP 3019, CLEAN 22 (8 aktywnych),
CHANGE 6 (0 aktywnych), GAIN 0**. Wszystkie 22 sprawdzone w kontekście — każde to
przymiotnik, żadne nie miało obok prefiksu ulicy ani numeru domu. Korpus
regresyjny bez zmian. Testy: 418 (+6).

**Do zrobienia osobno:** 63 aktywne oferty mają w bazie etykietę inną niż to, co
mówi dziś parser (np. zapisane „Spokojna", parser widzi „Chodźki"). Migracja ich
nie rusza, bo mają współrzędne, a przesuwanie pinezki to ryzykowniejsza operacja
niż jej zdjęcie — wymaga własnego pomiaru jakości starej i nowej etykiety.

### Naprawione (2026-08-11) — filtr przymiotnikowy objął wszystkie ścieżki parsera
Skan po wdrożeniu poprzedniej poprawki pokazał, że ogłoszenie „**Przytulna**
kawalerka 38 m²" — to samo, od którego wszystko się zaczęło — **dalej** ma pinezkę
pod ul. Przytulną. Filtr siedział wyłącznie w ścieżce ratunkowej (route 4), a tę
nazwę wyciągała ścieżka główna (route 1). Dokładnie pułapka z CLAUDE.md pkt 18:
*każdy filtr musi obowiązywać we wszystkich czterech ścieżkach*.

- **Reguła przymiotnikowa stoi teraz na wspólnym wyjściu `extract_address`**,
  a nie w jednej trasie. Adres z numerem domu jest zwolniony („Przytulna 5" to
  adres, nie opis wnętrza), prefiks „ul./al./os." nadal broni realnej ulicy.
- **Przecinek przestał być granicą zdania.** Wyliczanka „cicha, bezpieczna
  i monitorowana okolica" gubiła rzeczownik, bo przecinek trafiał do tekstu jako
  „¶" na równi z kropką. Teraz twarda interpunkcja (kropka, kreska, pionowa
  kreska) rozdziela zdania, a przecinek jest zwykłym separatorem; wyliczankę
  przechodzimy do pięciu tokenów.
- Wspólny `_boundary_text` zamiast dwóch kopii tego samego wyrażenia
  (parser + migracja).

Pomiar różnicy wobec wdrożonej wersji (3039 ofert): **KEEP 3032, CLEAN 7
(4 aktywne), CHANGE 0, GAIN 0**. Wszystkie 7 sprawdzone w kontekście — każde to
przymiotnik („Okolica bardzo spokojna, mieszkanie ciepłe", „cicha, bezpieczna
i monitorowana okolica"). Korpus regresyjny: 2 kolejne przypadki. Testy: 412 (+6).

Znane ograniczenie: gdy filtr odrzuci zwycięzcę, `extract_address` zwraca brak
adresu zamiast sięgnąć po następnego kandydata — jedna z siedmiu ofert miała
w treści realną ulicę („…w spokojnej, cichej okolicy, ul. J. Kossaka") i zamiast
niej trafia do warstwy „bez lokacji". To utrata *okazji*, nie zła pinezka.

### Naprawione (2026-08-10) — koniec pinezek na przymiotnikach
Ogłoszenie „**Przytulna** kawalerka 38 m², centrum" dostawało pinezkę pod
ul. Przytulną. Winna jest czwarta, ratunkowa ścieżka parsera
(`extract_from_whitelist`): gdy trzy wcześniejsze nic nie znajdą, bierze dowolną
nazwę z kluczy `geocoding_cache.json`, która pada gdziekolwiek w tekście —
a cache uczy się wszystkiego, co raz udało się zgeokodować, łącznie z naszymi
własnymi błędami (pętla sprzężenia zwrotnego opisana w `clean_geocoding_cache.py`).
Nazwy ulic Lublina to w dużej części zwykłe przymiotniki, więc opis wnętrza
wystarczał za adres.

Skala przed poprawką: **87 z 694 aktywnych ofert** (12,5%) miało adres z tej
ścieżki — 27 etykiet w ogóle nie było ulicą („Wolne", „Miejsca", „Piętro",
„Stokrotka", „Botanik"), 19 było przymiotnikiem („Przytulna", „Spokojnej",
„Cicha", „Słoneczne").

- **Kandydat musi być realną ulicą Lublina z OSM** (`street_whitelist`), nie tylko
  kluczem cache'u. Filtrujemy kandydatów, nie zwycięzcę, więc śmieć przestaje też
  *wygrywać* z realną ulicą wymienioną obok („Uniwersytetu Medycznego" nie bije
  już „Chodźki").
- **Nazwa użyta przymiotnikowo nie jest adresem** — odrzucamy ją, gdy stoi przed
  rzeczownikiem mieszkaniowym („przytulna kawalerka", „w cichej i spokojnej
  okolicy"), o ile nigdzie w treści nie ma jej z prefiksem „ul./al./os.".
  Reguła działa tylko dla nazw z listy `_ADJECTIVE_STREETS`: dla nazwisk
  w dopełniaczu sąsiedztwo rzeczownika nic nie znaczy, a kasowałoby realne
  adresy („… | Narutowicza. Mieszkanie do wynajęcia" — 12 takich ofert).
- **Granice zdań mają znaczenie.** Reguła przymiotnikowa czyta tekst, w którym
  interpunkcja zostawia ślad („¶"). W wariancie ze spacjami sklejka tytułu
  z opisem wygląda jak przymiotnik przed rzeczownikiem.
- **Migracja `drop_rejected_labels`** zdejmuje etykietę ofertom już w bazie:
  `_update_existing_offer` umie adres tylko poprawić, nigdy skasować, a ofert
  nieaktywnych scraper nie odwiedza. Warunki wąskie (świeże parsowanie opisu nie
  daje adresu + stara etykieta jest śmieciem albo przymiotnikiem), bezpiecznik
  `MAX_RETRACTION_RATIO` jak w pozostałych migracjach.
  `ADDRESS_PARSER_VERSION` → `2026-08-10`.

**Pomiar na całej bazie** (3026 ofert, wymagany przez CLAUDE.md pkt 14/17):

| przejście | ofert | w tym aktywnych |
|---|---|---|
| KEEP (bez zmian) | 2882 | — |
| CLEAN (etykieta → brak adresu) | 82 | 23 |
| CHANGE (etykieta → inna etykieta z treści) | 62 | 16 |
| GAIN / utrata realnej ulicy | **0** | **0** |

Wszystkie 28 usunięć, w których etykieta była realną nazwą ulicy, sprawdzono
pojedynczo w kontekście — każde to przymiotnik („spokojna okolica", „cicha
okolica", „przytulnego miejsca"), żadne nie miało obok prefiksu ulicy ani numeru
domu. Migracja na produkcyjnej bazie: 81 ofert (22 aktywne). Korpus regresyjny
zaktualizowany w 6 przypadkach. Testy: 406 (+19).

**Zmierzone i świadomie NIEzrobione — wymóg wielkiej litery.** Ulice pisze się
w ogłoszeniach wielką literą, a to, co ścieżka ratunkowa zgaduje ze zdania, jest
małą („wolne od lipca" → ul. Lipca, „nowe AGD" → ul. Nowe, „widok na miasto" →
ul. Widok). Reguła kasuje 37 z 62 podmian śmieć→śmieć, ale **zabiera pinezkę
realnym adresom pisanym małą literą** („mieszkanie na wynajem unicka", „wynajmę
mieszkanie wędrowna", „miasteczko akademickie weteranów 19") — ~9 ofert, a wyjątki
na prefiks i numer łatały to tylko częściowo. Kod został wyłączony
(`_capitalization_ok`), bo pkt 17 nie dopuszcza utraty pinezki przez realną ulicę.
Do zrobienia inaczej: odróżniać pospolite słowo od nazwy ulicy częstością zapisu
małą literą w całym korpusie ogłoszeń, nie wielkością liter w jednym tekście.

### Dodane (2026-08-09) — Indeks rozbity na nowe i wracające oferty
Port widoku z SONAR POKOJOWY: na stronie `trend.html` doszedł przełącznik
**„Suma aktywnych" / „Rozbij — nowe / reaktywacje"** (Indeks jako dwa pasma:
ogłoszenia świeże na dole, wracające z martwych na górze — suma pasm to
dokładnie linia Indeksu) oraz trzy wykresy napływu: **nowe oferty**,
**napływ całkowity** (nowe + powroty) i **reaktywacje**.

Przy porcie wyszło, że tej samej metryki co w POKOJOWYM nie da się tu policzyć:
- **`reactivated_at` jest nadpisywane przy każdym powrocie.** Dzień „ile ofert
  wróciło" pokazywał więc tylko te, które później już nigdy nie wróciły — im
  starszy dzień, tym więcej powrotów z niego wyparowało. Zmierzone na bazie:
  15/dzień w połowie lipca wobec 85 w dniu pomiaru, przy niezmienionym ruchu.
  Wykres z tych liczb rysowałby stromą rampę przy prawej krawędzi i pasmo
  recyklingu rosnące 143 → 250 w dwa dni — czysty artefakt pomiaru.
- **Większość „reaktywacji" to szum pipeline'u.** Zmierzone 09.08: ~48 na skan
  ze źródła `verification` (sami oznaczyliśmy ofertę jako nieaktywną, a jej
  strona na OLX cały czas była żywa) wobec 0–9 realnych powrotów z listingu.
- **Dodatkowo 2026-08-05:** blokada OLX zdjęła 409 ofert, a kolejne skany tego
  samego dnia przywróciły 308 z nich — 232 z nich to wciąż aktywne oferty, które
  nigdy nie zniknęły z rynku, a które wpadłyby do pasma „recykling".

Dlatego zamiast rysować te liczby jako trend:
- **Nowy `src/reactivation_log.py`** zapisuje **każdy** powrót osobno
  (`reactivation_dates`), razem z długością nieobecności i źródłem. Skan dopisuje
  wpis we wszystkich trzech miejscach reaktywacji (listing, „skipped",
  weryfikacja); `reactivated_at` zostaje bez zmian dla kompatybilności.
- **Powrót liczy się, gdy oferty nie było ≥24 h i wróciła w listingu** — krótsza
  przerwa to zgubienie oferty na jeden skan, a `verification` z definicji nie
  jest powrotem na rynek. Surowe wpisy zostają nietknięte, filtr jest po stronie
  generatora, więc zmiana progu nie wymaga zbierania historii od nowa.
- **Wykresy powrotów pokazują tylko zmierzony zakres.** Dni sprzed zapisu
  (i dzień-artefakt 2026-08-05) idą do serii jako `null` — na wykresie widać
  przerwę, a nie liczbę, której nie umiemy obronić. Pasma i przełącznik ruszają
  od pierwszego pełnego dnia pomiaru; do tego czasu przycisk „Rozbij" jest
  widoczny, ale nieaktywny, z wyjaśnieniem obok.
- `trend_data.json` dostał klucze `inflow` (`new` / `react` / `new_react`
  + `measured_from`) i `bands` (`new` / `react`). Wspólny `_flow_metric` obsługuje
  teraz wszystkie cztery wykresy przepływu — istniejąca seria odpływu wychodzi
  z refaktoru bajt w bajt identyczna.
- Testy: +31 (`test_reactivation_log.py`, `TestInflow`, `TestBands`, dwa w
  `test_main_scan.py` na zapis gapu przy reaktywacji) — łącznie 387.

### Naprawione (2026-08-09) — skan tracił wyniki przy kolizji z drugim skanem
Ręczny skan uruchomiony obok harmonogramu przepadł w całości: równoległy skan
zdążył wcześniej wypchnąć swoje pliki, rebase dał konflikt w 13 plikach
generowanych (`data/offers.json`, `docs/data.json`, `scan_history.json`…),
a workflow po trzech próbach zameldował **„dane skanu zostały utracone"**
(run 31332905163). Trzy próby były identyczne, więc dawały identyczny konflikt —
~9 minut pracy do kosza.

- **`scanner.yml` rozwiązuje teraz konflikty w plikach generowanych** na rzecz
  świeższego skanu. `data/` i `docs/` to jeden spójny zestaw (`docs/data.json`
  jest pochodną `data/offers.json` z tego samego przebiegu), więc wzięcie połowy
  z jednego skanu, a połowy z drugiego dałoby stan wewnętrznie sprzeczny —
  jedyne sensowne rozwiązanie to wziąć jedną stronę w całości.
- **Konflikt poza `data/` i `docs/` przerywa push z błędem.** Kodu źródłowego
  nie rozwiązujemy automatycznie.
- **Pułapka, którą trzeba tu znać:** w trakcie `rebase` etykiety są odwrócone —
  `--ours` to zdalny main, a `--theirs` to nasz przepisywany commit. Intuicyjne
  `--ours` wyrzuciłoby dokładnie ten skan, który ratujemy. Zweryfikowane
  doświadczalnie na sztucznym repo, nie z pamięci.
- Logika przetestowana na trzech scenariuszach (konflikt w plikach generowanych →
  wygrywa świeży skan; konflikt w `src/` → push pada i nie rusza kodu na remote;
  brak konfliktu → ścieżka bez zmian).

### Dodane (2026-08-09) — jakość mapy jako metryka skanu
Przez ostatnie rundy każdą zmianę parsera i geokodera trzeba było mierzyć doraźnym
skryptem („ile pinezek dokładnych ubyło?"). Teraz liczba jedzie do historii skanów
i na wykres, więc regresja zgłasza się sama.

- **`main`** dopisuje do `log_stats` blok `map_quality`: podział ofert aktywnych na
  `exact` / `street` / `none` oraz `on_map` / `off_map` z podziałem na przyczyny.
  Liczone przy okazji bilansu mapy, czyli z końcowego stanu bazy.
- **`monitoring_generator`** wystawia serię `charts.map_quality` z gotowymi udziałami
  procentowymi. Skany sprzed tej zmiany metryki nie mają i są **pomijane** — na
  wykresie nie pojawiają się jako zera.
- **`docs/monitoring.html`** — dwie nowe karty („Pinezki dokładne", „Bez pinezki",
  z liczbami bezwzględnymi w tooltipie i kolorem wg progu) oraz wykres „📍 Jakość
  mapy": słupki skumulowane z podziałem ofert plus linia z udziałem dokładnych.
  Na starcie: **34,5% dokładnych, 15,8% bez pinezki** z 715 ofert aktywnych.

### Zmienione (2026-08-09) — popup mapy bliżej SONAR-POKOJOWY
- **Tytuł ogłoszenia w popupie.** Dotąd był tam wyłącznie adres, więc przy jednym
  adresie z kilkoma ofertami nie dało się ich od siebie odróżnić. Tytuł jest teraz
  zapisywany w bazie przy skanie (`main._process_offer` i `_update_existing_offer` —
  ten drugi, żeby prawdziwą nazwę dostały też oferty już w bazie). Dla ogłoszeń
  sprzed tej zmiany `map_generator.display_title` odtwarza nazwę ze slugu URL,
  ucinając końcówkę „CID3-IDxxxx". Przy jednej ofercie tytuł idzie do nagłówka
  (fioletowa linia schodzi pod niego), przy kilku — do karty każdej oferty.
- **Metryki wyrównane do projektu bliźniaczego** (`style.css?v=4`, `script.js?v=18`):
  mniejsze odstępy i czcionki nagłówka, cena 22 → 18 px, karta oferty 16 → 8/9 px
  paddingu, „Skład: …" i tag oferty w jednym wierszu, daty zawijane obok siebie
  zamiast jedna pod drugą, „Pokaż całość" jako zwykły link zamiast przycisku
  (rozbijał wiersz opisu na dwa). Popup jest przez to wyraźnie niższy przy tej
  samej treści.
- **Nie przeniesione świadomie**: gwiazdka „Do ulubionych" i wiersz profilu
  firmowego z POKOJOWEGO — w MIESZKANIOWYM nie ma ani strony ulubionych, ani
  śledzenia profili, więc byłyby to przyciski donikąd, a nie zmiana wyglądu.
  Zostaje za to nasz własny blok „Lokalizacja przybliżona", którego POKOJOWY
  nie ma — tłumaczy kwadratowe markery.
- 15 nowych testów (`tests/test_popup_title.py`, `tests/test_map_quality_metric.py`);
  suite 341 → 356.

### Naprawione (2026-08-09) — zakładka debug pokazywała 28 ze 111 ofert bez pinezki
Strona obiecywała „oferty, które scraper pobrał, ale nie trafiły na mapę", a liczyła
tylko te, którym parser nie znalazł ULICY. Pozostałe **83 oferty nie były policzone
nigdzie** — bo współrzędne zdejmują im kroki uruchamiane PO pętli skanu
(`_demote_non_street_pins`), więc liczniki z tej pętli fizycznie nie mogły ich zobaczyć.

- **Bilans liczony z KOŃCOWEGO stanu bazy** (`main._write_map_gap_breakdown`,
  `_classify_map_gap`) zamiast z liczników pętli. Tylko wtedy rachunek się domyka.
- **Trzy nowe kategorie** obok istniejącej „bez adresu":
  - `not_a_street` — parser coś odczytał, ale to nie nazwa ulicy („King Size 180x",
    „Duże łóżko 120", „Wolne") — **75 ofert**,
  - `area_only` — osiedle albo dzielnica: znamy okolicę, nie budynek („Wrotków",
    „Osiedle Prestige") — **6 ofert**,
  - `no_coords` — realna ulica, ale geokoder nie dał punktu („Brzeska",
    „Osiedle Klemensa Junoszy") — **4 oferty**. Ten licznik pokazywał 0, mimo że
    takie oferty istniały.
- **Rachunek do sprawdzenia gołym okiem** na górze strony: „711 ofert aktywnych =
  600 na mapie + 111 bez pinezki (bez adresu 26 + nie ulica 75 + obszar 6 + brak
  współrzędnych 4)". Gdy suma się nie zgadza, pasek robi się czerwony i mówi o ile —
  czyli pojawienie się piątej, nienazwanej przyczyny od razu widać.
- Rozdzielone komunikatem dwie różne rzeczy, które wcześniej stały obok siebie bez
  wyjaśnienia: cztery pierwsze kategorie to oferty **obecne na stronie** (warstwa
  „bez lokacji"), a duplikaty i brak ceny to ogłoszenia **pominięte w skanie**.
- **Kontrola krzyżowa z mapą** (`_map_reality`) — sam domknięty bilans okazał się
  niewystarczający. Pierwsza wersja liczyła go przed Krokiem 4 (weryfikacja ofert
  nieaktywnych), więc opisywała stan **sprzed reaktywacji**: 665 aktywnych zamiast
  713, 561 na mapie zamiast 600. Wewnętrznie się zgadzał (104 = 25+70+5+4), więc
  zielony pasek „bilans OK" uwiarygadniał liczby rozjechane z mapą o 48 ofert.
  Bilans liczy się teraz tuż przed zapisem bazy, a strona dodatkowo konfrontuje go
  ze `stats` z `docs/data.json` — rozjazd któregokolwiek z dwóch rachunków zapala
  czerwony pasek z konkretną różnicą. Brak `data.json` = brak kontroli, nie alarm.
- 21 nowych testów (`tests/test_map_gap.py`), w tym testy obu kontroli (równanie
  bilansu i zgodność z mapą) oraz wstecznej zgodności ze starym plikiem próbek;
  suite 320 → 341.

### Naprawione (2026-08-08) — Nominatim oddaje punkt ULICY na zapytanie o numer domu
Analiza grupy „nieprecyzyjnych" pokazała, że **jest ona w większości uczciwa**: z 352
aktywnych ofert z `precision='street'` aż **340 nie podaje numeru domu w treści** —
nie ma tam czego naprawiać. Prawdziwa wada siedziała w geokoderze.

- **`Geocoder._number_confirmed`** — zapytanie o „Lubomelskiej 9" wraca z Nominatim
  jako trafienie, ale odpowiedź nie ma `house_number` i jest przypięta do **innej
  ulicy** (`road='Boczna Lubomelskiej'`). Braliśmy to za adres budynku: pinezka
  142 m od celu i kropla „adres dokładny". Zapytania idą teraz z `addressdetails=1`,
  a odpowiedź na adres z numerem musi ten numer potwierdzić (bez wielkości liter,
  bez części po „/", bo „22B"↔„22b" i „33/40"↔„33" to ten sam budynek).
  **Odrzucenie nie gubi oferty** — sterowanie leci do istniejącego fallbacku „sama
  ulica", który zwraca ten sam punkt z `number_fallback=True`, czyli mapa rysuje
  kwadrat „przybliżony" zamiast udawać precyzję.
- **36 zatrutych kluczy cache** (`find_street_level_number_keys`,
  `_downgrade_street_level_pins`) — wpisy „ULICA numer" z punktem **co do bitu**
  równym punktowi samej ulicy. Bez sprzątania każda nowa oferta pod takim adresem
  dostawała z cache fałszywe `precision='exact'`, omijając nową walidację.
  Pinezka się nie rusza ani nie znika — zmienia się tylko kształt markera.
- **Reużyty punkt zachowuje precyzję.** ~70% ofert w skanie nie dotyka geokodera
  (`reused_coords`), a `_address_precision` liczyło wtedy precyzję od zera — więc
  oferta z numerem wracała jako 'exact', kasując uczciwe 'street'. Brak geokodera
  = brak nowej wiedzy, więc przenosimy poprzednią precyzję.

Zmierzony efekt **dziś: 0 ofert zmienia stan** — historyczne przypadki złapał już
`_backfill_address_precision`. To poprawka **u źródła**: zamyka dopływ nowych
fałszywych „adresów dokładnych", którego backfill nie łapie (pomija oferty, które
`precision` już mają).
- 27 nowych testów (`tests/test_number_confirmed.py`); suite 293 → 320.

#### Zmierzone i świadomie NIEzrobione
- **Sprawdzanie nazwy ulicy w odpowiedzi Nominatim** — „Lubomelskiej" trafia
  w „Boczna Lubomelskiej", ale odróżnienie tego od legalnego skrótu („Chodźki" →
  „Doktora Witolda Chodźki") wymaga dopasowania ścisłego, które psuje skróty,
  na których stoi cały parser.
- **Rozwijanie skróconej nazwy do pełnej z OSM** („Gabriela Narutowicza" →
  „Prezydenta Gabriela Narutowicza") — z 220 nulli w cache jednoznacznie rozwijalne
  jest 5, w tym **1 aktywna oferta**. Nie warto maszynerii.
- **Szukanie ulicy wymienionej w treści** dla 81 ofert ze śmieciową etykietą —
  pomiar dał niemal same fałszywe trafienia, bo nazwy ulic Lublina to zwykłe
  przymiotniki: „Dobra", „Cicha", „Ciepła", „Widok", „Spokojna", „Przytulna",
  a „Mieszka I" trafia w słowo *mieszka*. To jest dokładnie powód, dla którego
  parser wymaga prefiksu „ul." albo numeru — i granica tej metody.

### Naprawione (2026-08-08) — „ulice", których nie ma w Lublinie
Audyt po poprzedniej zmianie pokazał **21 aktywnych ofert stojących na nazwie, która
nie jest żadną ulicą Lublina** — „Netia 30", „King Size 180x", „Duże łóżko 120",
„Powierzchnia 32", „Kalina 38". Każda z `has_number=True`, czyli dla mapy „adres
dokładny" pod zmyślonym numerem.

- **Fallback nazwiskowy w `address_parser` omijał WSZYSTKIE filtry ścieżki głównej.**
  `POLISH_SURNAME_PATTERN` („NAZWA w dopełniaczu + numer") stoi w kolejności *przed*
  `extract_street_only`, więc wpuszczał z powrotem dokładnie te adresy, które parser
  chwilę wcześniej odrzucił: „Powierzchnia 32" pochodziło z „Powierzchnia 32 m kw."
  (złapane filtrem metrażu), „Nałęczowska 2" z „przystanek Nałęczowska 2 minuty
  pieszą". Obowiązują tam teraz te same trzy warunki co w ścieżce głównej: lista
  fałszywych adresów, lista instytucji i **przynależność nazwy do whitelisty ulic** —
  wzorzec poza nazwiskami trafiał też w imiona i rzeczowniki („Sylwia 50",
  „Monika 66", „Sypialnia 1", „Netia 30").
  Pomiar na 2976 opisach: **25 adresów śmieć→ULICA, 0 pogorszeń, 1 utracony**
  (śmieciowy „Powierzchnia 32" oferty nieaktywnej — oferta zostaje na stronie).
  Whitelist tylko *wpuszcza*: brak modułu = zachowanie sprzed poprawki, więc jej
  awaria nie może zacząć odrzucać adresów.
- **Poprawka parsera dociera teraz do bazy** (`_update_existing_offer` →
  `street_upgraded`, `address_migration.upgrade_junk_streets`). Dotąd nie miała jak:
  „Kalina 38" ma numer, więc nie łapało się ani na „nowy ma numer, stary nie", ani na
  `old_looks_like_garbage` (ten warunek wprost wyklucza stary adres z numerem), ani na
  `number_retracted` (inna ulica). Kierunek jest jednostronny — nie-ulica → ulica —
  a warunek `not old_had_coords` pilnuje, żeby oferta z **poprawnie stojącą** pinezką
  i brzydką nazwą („Parysa Wynajmę", 23 m od ul. Parysa) trafiła do
  `_demote_non_street_pins`, które punkt zostawia. Migracja wsteczna działa offline
  i tylko dla ofert bez współrzędnych: **116 etykiet** (5 aktywnych, 111 nieaktywnych),
  z czego **102 zyskały pinezkę** z cache geokodera.
- **Stare współrzędne nie jadą już za etykietą na inną ulicę.** Blok „zachowaj coords"
  w `_update_existing_offer` działał bezwarunkowo, więc podmiana „Zana" → „Lipowa 5"
  stawiała punkt ul. Zana pod adresem przy Lipowej. Teraz punkt zostaje tylko przy tej
  samej ulicy (albo przy sprzątaniu ogona etykiety).
- **Sam numer domu przestał być wariantem nazwy** (`street_whitelist.name_variants`).
  „Kwarcowa Nowoczesne 3" uchodziło za kompletną nazwę ulicy, bo człon „3" trafiał
  w indeks (istnieje ulica z „3" w nazwie) — i sprzątanie etykiety odpuszczało.
  Na bazie: 1 etykieta („Politechniki 3") przestaje udawać ulicę.
- **Warstwa „bez lokacji" nie pokazuje już śmiecia jako adresu.** `map_generator`
  decydował o tym przez `is_known_street` (dopasowanie po podciągu), więc
  „Nieruchomość 3", „Stokrotka 3", „GRATIS Przestronne 3" wyświetlały się jako adres.
  Kryterium jest teraz `is_known_place` (dopasowanie pełne).

Wynik na 21 ofertach z audytu: **5 dostało realną ulicę** (Beliniaków, Wschodnia ×2,
Niepodległości, Laurowej; 4 z pinezką), pozostałe **16 pokazuje uczciwe
„Adres nieznany"** zamiast wymyślonego adresu. Żadna oferta nie zniknęła ze strony.
- 18 nowych testów (`tests/test_surname_fallback.py`, `tests/test_street_upgrade.py`);
  suite 275 → 293.

### Naprawione (2026-08-08) — dopasowanie nazw: strona zapytania kontra strona indeksu
Po poprzedniej zmianie na mapie zostało **6 aktywnych pinezek stojących na nazwie,
która nie jest ulicą**. Każda próba domknięcia tego jedną regułą cofała którąś
z wcześniejszych napraw, więc rozdzieliliśmy role obu stron dopasowania.

- **`name_variants` (ZAPYTANIE) jest wąskie, `index_variants` (SNAPSHOT) szerokie.**
  Zamiana l. mnogiej na pojedynczą (`Racławickie` → `Racławicka`) jest potrzebna,
  żeby „Racławickiej" trafiło w „Aleje Racławickie" — ale zastosowana do **tekstu
  z ogłoszenia** zamieniała osiedle „Piastowskie" w realną, zupełnie inną ulicę
  „Piastowska". Po stronie indeksu ten sam wariant tylko dokłada zapis nazwy,
  która w OSM istnieje, więc nie może uwiarygodnić śmiecia. Snapshot ulic
  (`_index`) wchodzi teraz do pamięci we wszystkich formach.
  Pomiar na 2890 ofertach: **+2 rozpoznane ulice** („Racławickiej", „Brzeska"
  = Magdaleny Brzeskiej), zero nowych fałszywych.
- **`is_known_place` — dopasowanie PEŁNE zamiast po podciągu.** `is_known_street`
  celowo dopasowuje po członach (ogłoszenia skracają nazwy), więc chroniło przed
  zdjęciem z mapy nawet czysty śmieć „Nowe" — bo taki człon ma „Nowe Sady".
  Do pytania „czy ta etykieta w ogóle jest czyimś adresem" właściwe jest
  dopasowanie całości.
- **`is_district_name` nie liczy już samego ostatniego członu** (`whole_only`).
  „Rury Jezuickie" robiło dzielnicę z ul. Jezuickiej, a nazwa osiedla z **59 ofert
  przy ul. Nałęczowskiej**. Dzielnice i tak są w liście pod krótkimi nazwami
  („Rury", „Czuby"), więc nic na tym nie tracimy. Do tej pory te ulice ratował
  wyłącznie warunek `is_street_name` sprawdzany wcześniej — pułapka czekała na
  pierwsze użycie predykatu bez tej osłony.
- **`_salvage_street_label` mierzy „nazwa już jest kompletna" listą ULIC**, nie
  szeroką whitelistą — ta ostatnia dopasowuje po podciągu, więc „Sekutowicza
  Mieszkanie" uchodziło za nazwę kompletną i śmieć zostawał doklejony na zawsze.

Efekt na bazie (2976 ofert, pomiar przed/po): **8 etykiet sprzątniętych z zachowaniem
pinezki** („Sekutowicza Mieszkanie" → „Sekutowicza", „Granata NOWE" → „Granata",
„Bursztynowa Mieszkanie" → „Bursztynowa"…), **14 pinezek zdjętych do warstwy
„bez lokacji"** (12× śmieć „Nowe", „Osiedle Piastowskie Mieszkanie", „Mała").
Żadnego przejścia w drugą stronę — **ani jedna realna ulica nie straciła pinezki**.
Wśród aktywnych: 2 sprzątnięte, 3 zdjęte → **0 pinezek na nie-ulicach**.
Bez bumpa `ADDRESS_PARSER_VERSION`: `address_parser.py` się nie zmienił,
a `_demote_non_street_pins` i tak przelicza całą bazę przy każdym skanie.
- 30 nowych testów (`tests/test_street_whitelist.py` + rozszerzony
  `test_area_not_address.py`); suite 245 → 275.

### Zmienione (2026-08-08) — na mapie stoją tylko adresy uliczne
- **Adres opisujący OBSZAR nie dostaje pinezki** (`main._is_area_not_address`,
  `_demote_non_street_pins`). Nazwy osiedli („Botanik", „Piastowskie", „Skarpa",
  „Poręba", „Wrotków", „Rury"), instytucji („Uniwersytetu Medycznego") i resztek
  po parserze („Wolne" — 10 ofert, „Miejsca" — 5, „Stokrotka", „Piętro") dostawały
  punkt gdzieś w tej okolicy i na mapie wyglądały jak normalny adres. Trafiają
  teraz do warstwy **„bez lokacji"**: oferta zostaje na stronie i w zakładce
  debugowej, ale nie udaje, że wiadomo, gdzie stoi. Decyzja produktowa.
  Efekt: na mapie 669 → 615 aktywnych ofert, warstwa „bez lokacji" 71 → 125.
  Kolejność ma znaczenie — najpierw próbujemy sprzątnąć etykietę („Piłsudskiego
  Okna" → „Piłsudskiego", 32 rekordy), bo to ratuje pinezkę; dopiero gdy nic
  z nazwy nie zostaje, oferta traci punkt (203 rekordy, w tym nieaktywne).
- **`data/districts_lublin.json`** (nowe) — 137 nazw dzielnic i osiedli z OSM
  (`place=suburb|neighbourhood|quarter`, `landuse=residential`) + `is_district_name`
  w `street_whitelist`. Współrzędne celowo **nie** są używane do stawiania markerów:
  osiedle to obszar, nie punkt.
- **`street_names` w `data/streets_lublin.json`** — podzbiór samych ulic (1445 nazw
  `highway` z OSM) + `is_street_name`. Szeroka lista `names` (1563) dalej służy
  wyłącznie do *akceptowania* adresów ratunkowych.
- Warunek zdejmowania pinezki jest złożony, bo **każdy pojedynczy test miał
  zmierzone fałszywe trafienia**: sama lista ulic nie zna form odmienionych po
  stronie indeksu (wypadała realna „Racławickiej"), samo dopasowanie dzielnic po
  podciągu robiło z tej ulicy dzielnicę („Racławicka Dzielnica Mieszkaniowa"),
  a bez szerokiej whitelisty ginęły nietypowo zapisane adresy („Sekutowicza
  Mieszkanie"). Zdejmujemy pinezkę tylko wtedy, gdy nazwa nie jest ulicą **i**
  jest znaną dzielnicą albo w ogóle nie ma jej w whiteliście.
- 24 nowe testy (`tests/test_area_not_address.py`); suite 221 → 245.

### Dodane (2026-08-08) — sprzątanie etykiet przy poprawnych pinezkach
- **Etykieta adresu czyszczona, gdy pinezka stoi dobrze.** Audyt kwadratów liczył
  jako „źle postawione" 17 ofert, których punkt jest w porządku — brudna była tylko
  nazwa: „Parysa Wynajmę" stoi **23 m** od ul. Parysa, „Przyjaźni Kuchnia Hol" 28 m,
  „Nowy Świat Przytulne" 20 m, „Ćwiklińskiej Przestronny" 23 m. Teraz doklejony
  ogon jest obcinany, a **współrzędne zostają nietknięte** (osobna ścieżka od
  odzysku z 2026-08-07: tam geokoder nic nie znalazł, tu znalazł dobrze).
  Na obecnej bazie: 18 aktywnych ofert (48 łącznie z nieaktywnymi).
  W `_update_existing_offer` warunek jest wąski — nowa nazwa musi być **początkiem**
  starej i realną ulicą, a stara nie; to gwarantuje obcięcie ogona zamiast zmiany
  adresu. Krytyczny warunek `not final_number`: bez niego „Lipowa 10" skróciłoby się
  do „Lipowa", bo obcinanie nie odróżnia numeru domu od śmiecia (złapane testem).
- 4 nowe testy; suite 217 → 221.

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

### Dodane (2026-08-07) — whitelist ulic i migracja adresów
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

### Zmienione (2026-08-07) — kształt markera z `precision`
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

### Dodane (2026-08-06) — adres najpierw z tytułu
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

### Naprawione (2026-08-05) — martwa strefa ochrony przed dezaktywacją
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

### Zmienione (2026-07-26) — changelog czytany na starcie sesji
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
