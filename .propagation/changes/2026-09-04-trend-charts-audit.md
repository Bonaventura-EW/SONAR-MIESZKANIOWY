---
id:          2026-09-04-trend-charts-audit
repo:        Bonaventura-EW/SONAR-MIESZKANIOWY
family:      sonary
date:        2026-09-04
category:    bugfix
what:        Wykresy na zakładce Indeks liczyły trwającą dobę jak zamkniętą, nie maskowały dni z niepełną liczbą skanów, a odpływ nie domykał się z napływem — cztery niezależne błędy dające fałszywy zjazd na prawej krawędzi każdego wykresu.
why:         Strona pokazywała „1D −78" i 691 aktywnych ofert, gdy ostatnia zamknięta doba miała 769; odpływ ostatniego dnia stał na zerze. Wcześniejsza naprawa (okres życia kończy się na `last_seen`) zdjęła błąd przeciwnego znaku, który to maskował — więc problem jest świeży dokładnie u tych braci, którzy tamtą naprawę już wdrożyli.
how:         Jedna wspólna oś dni dla wszystkich metryk (`_window`) plus maska pokrycia skanami (`_scan_coverage`)- dzień wchodzi do serii tylko, gdy zakończyły się w nim WSZYSTKIE zaplanowane przebiegi, a wykres kończy się na ostatnim takim dniu. Odpływ przedefiniowany z „potwierdzona dezaktywacja po last_seen" na „koniec odcinka życia" (wyjście z Indeksu), napływ czyta starty tych samych odcinków - bilans `Indeks(D) = Indeks(D−1) + napływ(D) − odpływ(D−1)` domyka się z definicji. Dzień zniknięcia oferty odtwarzany z `at − gap_h` w godzinach zamiast `int(gap_h // 24)`. Średnie „X/dzień" liczone z ostatnich 30 dni, z jawnym oknem przy każdej liczbie.
surface:     src/trend_generator.py, docs/trend.html, tests/test_trend_generator.py
generality:  family
propagate:   yes
commit:      HEAD
---

# Kontekst

Cztery błędy, wszystkie **wbudowane w konstrukcję**, którą mają bracia
z dziennym szeregiem odtwarzanym z `offers.json`. Warto sprawdzić u siebie —
każdy da się zmierzyć w minutę, bez czytania kodu.

**1. Trwająca doba rysowana jak zamknięta.** Jeśli okres życia oferty kończy
się na `last_seen` (naprawa `2026-09-02-active-count-drift`), to dzień liczy
oferty widziane w JEGO skanach — a dzisiejszy dzień ma za sobą dopiero część
przebiegów. Sprawdzenie: `git log` po snapshotach wygenerowanego JSON-a
i porównanie ostatniego punktu serii z kolejnych skanów tej samej doby.
U nas: 686 → 717 → 748 → 767 w ciągu jednego dnia, przy 769 nazajutrz.
Uwaga na kolejność wdrożeń: **przed** tamtą naprawą błąd był niewidoczny,
bo aktywne oferty ciągnęły się do dnia ostatniego skanu i zawyżały dzień
bieżący dokładnie tyle, ile ten mechanizm zaniża.

**2. Dni z niepełną liczbą skanów.** Maskowaliśmy dobę BEZ skanu, ale nie dobę
z jednym przebiegiem z trzech. Sprawdzenie: policz przebiegi na dzień
z `scan_history.json` i porównaj wartość Indeksu ze średnią sąsiadów.
U nas dni z 2 przebiegami leżą średnio 17,5 oferty poniżej sąsiadów, przy
+7,1 dla dni pełnych — i to one dawały „rekord odpływu". Ograniczenie, którego
świadomie nie łatamy: doba PO niepełnej niesie jej spillover (oferty dostają
`first_seen` o dzień za późno), więc bywa zawyżona.

**3. Odpływ nie domyka się z napływem.** Jeśli odpływ liczy potwierdzone
dezaktywacje, a napływ — powroty z historii reaktywacji, to opisują dwa różne
rynki: dezaktywacja przychodzi z opóźnieniem (kolejka linków), a wyjście oferty
na czas nieobecności nie jest liczone wcale, choć jej powrót już tak.
Sprawdzenie: zsumuj napływ i odpływ z tego samego okna i porównaj z realną
zmianą Indeksu. U nas 23 dni dawały +146 wobec faktycznego +5.
Lekarstwo jest tanie: jedno źródło prawdy — starty i końce odcinków życia,
z których i tak liczy się Indeks.

**4. `int(gap_h // 24)` do odtworzenia dnia zniknięcia.** Przy skanach o stałych
porach (u nas 9:17/15:17/21:17) różnica pór doby sięga 12 h, więc dzielenie
całkowite myli się o dobę w **32%** przypadków, zawsze w stronę skrócenia
nieobecności. Jeśli wpis powrotu trzyma pełny timestamp i przerwę w godzinach,
odtworzenie `at − gap_h` jest bezstratne i nie wymaga zbierania historii od nowa.

Poza tym dwie rzeczy frontendowe warte przeniesienia niezależnie od reszty:
pad biblioteki wykresów z CDN wywalał cały skrypt (wszystkie kontenery zostawały
na „Ładowanie danych…" bez komunikatu), a ApexCharts przy kilku punktach rozbija
oś `datetime` na godziny i powtarza tę samą datę kilkanaście razy — `tickAmount`
ani wymuszony `format` tego nie zmieniają (3.49.1), pomaga dopiero oś kategorii
z gotowymi etykietami dni.
