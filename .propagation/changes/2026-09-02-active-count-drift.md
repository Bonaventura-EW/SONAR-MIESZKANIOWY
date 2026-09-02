---
id:          2026-09-02-active-count-drift
repo:        Bonaventura-EW/SONAR-MIESZKANIOWY
family:      sonary
date:        2026-09-02
category:    bugfix
what:        Licznik aktywnych ofert (i pierwszy wykres na zakładce Indeks) puchł o ~25%, bo dezaktywacja przez sprawdzanie linku ma sufit 60 ofert na skan, a kolejka kandydatów rosła szybciej — plus wykres ciągnął okres życia ofert `active` do dnia ostatniego skanu.
why:         Od wdrożenia dezaktywacji „tylko po potwierdzeniu linkiem" (2026-08-12) liczba aktywnych rosła 694 → 1019 przy PŁASKIM listingu (~770 ofert/skan). Nadwyżka co do kilku ofert pokrywała się z kolejką `verification.candidates` (3 → 254). Wykres pokazywał „rekord dziś" i wzrost 1M +120, gdy rynek realnie się kurczył (−73).
how:         Dwie warstwy. (1) Skaner - `MAX_MISSING_DAYS`: oferta nieobecna w CAŁYM listingu przez N dni (u nas 3 dni = ~9 przebiegów przy 3 skanach dziennie) idzie do nieaktywnych bez czekania na sprawdzenie linku; budżet sprawdzeń idzie odtąd na świeżo nieobecne, gdzie link check łapie zniknięcie WCZEŚNIEJ niż sufit. (2) Generator - okres życia oferty kończy się na `last_seen` (nie na dniu ostatniego skanu), jest cięty realnymi przerwami z historii reaktywacji (gap ≥ 24 h, bez powrotów ze źródła `verification`), a dni bez skanu idą do serii jako `null` zamiast fałszywego załamania.
surface:     src/main.py, src/trend_generator.py, tests/test_main_scan.py, tests/test_trend_generator.py
generality:  family
propagate:   yes
commit:      2f25455
---

# Kontekst

Ten błąd jest **wbudowany w konstrukcję**, którą mają wszyscy bracia:
dezaktywacja wyłącznie po potwierdzeniu linkiem + sufit sprawdzeń na skan.
Dopóki napływ nowych ofert przewyższa liczbę potwierdzonych zniknięć, pula
aktywnych puchnie liniowo — i to cicho, bo każda pojedyncza decyzja
(„nie dezaktywuj, dopóki OLX nie potwierdzi") jest sama w sobie słuszna.

Jak sprawdzić u siebie w minutę, bez czytania kodu — z `scan_history.json`:

    active − raw_offers  (nadwyżka)   vs   verification.candidates  (kolejka)

Jeśli oba rosną w tym samym tempie, a `raw_offers` stoi w miejscu, masz to samo.
U nas: 10.08 nadwyżka −25, kolejka 3 → 02.09 nadwyżka +245, kolejka 254.

Dwie pułapki przy adaptacji:

1. **Próg `MAX_MISSING_DAYS` zależy od częstotliwości skanów.** Przy 3 skanach
   dziennie 3 dni to ~9 pełnych przebiegów listingu — z zapasem na blokadę OLX
   (ochrona przed masową dezaktywacją i tak wstrzymuje wtedy cały krok).
   Przy jednym skanie dziennie ten sam zapas to raczej 5-7 dni.
2. **Nie licz stale-dezaktywacji jako osobnej metryki.** U nas API i monitoring
   czytają `verification.confirmed_inactive` jako „ile zniknęło" — nowe
   dezaktywacje wchodzą do tego samego licznika (plus osobne `stale_inactive`
   do diagnostyki), inaczej wykres „znikło" zaniża prawdę.

Przy pierwszym skanie po wdrożeniu licznik zniknięć pokazuje jednorazowy skok
o rozmiarze zaległej kolejki. Wykres odpływu rozłoży je na realne dni, o ile
liczy po `last_seen`, a dezaktywacja tego pola NIE rusza — u nas nie ruszała.
