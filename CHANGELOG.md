# Changelog

Wszystkie istotne zmiany w projekcie SONAR MIESZKANIOWY.

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Daty w formacie RRRR-MM-DD (strefa Europe/Warsaw).

> Wpisy do 2026-05-22 zrekonstruowano z datowanych komentarzy `# FIX` w kodzie
> (historia gita w tym klonie sięga 2026-05-23). Od tej daty źródłem są commity.

## [Niewydane]

### Dodane
- `CLAUDE.md` — wytyczne dla agentów (uruchamianie, przepływ danych, pułapki).
- `CHANGELOG.md` — ten plik.

### Do naprawienia (znane problemy)
- `scanner.yml`: warunek tygodniowego `fix_missing_coords` sprawdza cron
  `'0 7,13,19...'`, podczas gdy aktywny cron to `'17 7,13,19...'` — krok nigdy
  się nie wykonuje (martwy kod w pipeline).
- `extract_cid()` zduplikowane w `main.py` i `scraper.py` (powinno być wspólne).
- `EXCLUDED_WORDS` (`address_parser.py`) zawiera zdublowane wpisy z kolejnych łatek.

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
