---
id:          2026-11-04-bands-follow-measured-index
repo:        Bonaventura-EW/SONAR-MIESZKANIOWY
family:      sonary
date:        2026-11-04
category:    bugfix
what:        Przy mierzonym Indeksie rozbicie na pasma (świeże / recykling) ma lukę tylko tam, gdzie lukę ma sam Indeks, a nie wg maski ciągłości skanów.
why:         Tryb „Suma" (mierzony, `index_history`) rysował doby z nocną przerwą > 12 h, a tryb „Rozbij" robił w nich dziurę — pojedynczy dzień między dwiema lukami ApexCharts w ogóle nie rysuje jako pole, więc dwie takie doby (29.10, 31.10) dały 4-dniową dziurę na wykresie.
how:         W `build_bands` gałąź z `index_series` przestała sprawdzać `d in incomplete`; maskuje wyłącznie dni, dla których zmierzony Indeks ma `None`. Udział recyklingu dalej idzie z rekonstrukcji (odcinki życia ofert nocna przerwa w skanach nie zmienia), liczba — z pomiaru. Gałąź bez `index_series` (rekonstrukcja) zostaje z maską `incomplete`.
surface:     src/trend_generator.py, tests/test_index_history.py
generality:  family
propagate:   yes
commit:      
---

Dotyczy tylko brata, który ma JEDNOCZEŚNIE mierzony Indeks (manifest
`2026-09-03-measured-index-history`) i pasma skalowane na niego
(`build_bands(index_series=...)`) z maską niepełnych dni z `_scan_coverage`
(manifest `2026-09-27-scan-gap-coverage`). Zasada: „ta sama maska co w Indeksie"
— przy pomiarze maską Indeksu są jego `None`, nie `incomplete`. Szybki test:
`trend_data.json` → dni, gdzie `series[i][1] != None`, a `bands.new[i][1] == None`;
u nas wyszło 29.10 i 31.10.
