---
id:          2026-09-27-scan-gap-coverage
repo:        Bonaventura-EW/SONAR-MIESZKANIOWY
family:      sonary
date:        2026-09-27
category:    bugfix
what:        Maska niepełnych dni na wykresach Indeksu ocenia pełność doby po ciągłości obserwacji (brak przerwy > 12 h w obrębie dnia), a nie po liczbie skanów w dobie kalendarzowej.
why:         GitHub opóźnia cron o godziny, więc w poniedziałki kończyły się tylko 2 skany (trzeci po północy) i wykresy przepływu rysowały co tydzień fałszywą dziurę, choć doba była obserwowana co ~8–9 h.
how:         `load_scan_counts` zwraca `ScanCounts` (dict dzień→liczba + posortowane `times`). `_scan_coverage` dla takiego wejścia woła `_day_is_covered`: łańcuch ostatni skan przed dobą → skany w dobie → pierwszy skan po niej, każda przerwa przycięta do granic dnia musi być ≤ `MAX_SCAN_GAP_HOURS`. Brak skanu po dobie = doba w toku. Goła mapa/zbiór dni idą po staremu przez `SCANS_PER_DAY`.
surface:     src/trend_generator.py, tests/test_trend_generator.py
generality:  family
propagate:   yes
commit:      
---

Próg dobrany pomiarem na `scan_history.json` (06–26.09): zwykle najdłuższy odcinek
w dobie 7–9,4 h (watchdog odpala przy 7 h), wyjątki 10,9 / 11,8 h w dni z 5 skanami
i pierwszym przed południem. 10 h robiłoby z nich nowe dziury. U brata sprawdź
rozkład przerw u siebie przed wyborem progu — zależy od watchdoga i crona.
