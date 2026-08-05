<!--
Szablon PR dla SONAR MIESZKANIOWY. Wypełnij sekcje, które mają sens dla tej
zmiany — puste usuń. Sekcja „Changelog" jest obowiązkowa: wpis w CHANGELOG.md
ma być CZĘŚCIĄ TEGO PR-a, nie osobnym commitem „po fakcie".
-->

## Co się zmienia

<!-- 2–5 punktów: co dochodzi/znika/działa inaczej, z nazwami plików. -->

-

## Dlaczego

<!-- Problem, który to rozwiązuje. Jeśli to bug: co się działo źle i od kiedy. -->

## Changelog

- [ ] Wpis dopisany do `CHANGELOG.md` → sekcja `## [Niewydane]` → `Dodane` / `Naprawione` / `Zmienione` / `Wydajność`
- [ ] Zmieniony kod oznaczony datowanym komentarzem `# FIX YYYY-MM-DD:` / `# OPTYMALIZACJA YYYY-MM:` (jeśli to poprawka istniejącej logiki)

## Testy

<!-- Co odpalone i z jakim wynikiem. `pytest` z katalogu głównego repo, nie z src/. -->

- [ ] `pytest` — X passed (suite: N → M)
- [ ] Nowe testy pokrywają zmienioną logikę (parser / geokoder / generator)

## Weryfikacja

<!-- Jak sprawdzone „na żywo": render strony, wynik generatora, zrzut liczb. -->

## Pułapki projektu (odhacz to, czego dotyczy PR)

- [ ] **ID ofert** — porównania po `CID3-IDxxxx` (`extract_cid`), nie po slugu URL
- [ ] **Współrzędne** — czytane z `offer['address']['coords']`, nie z top-level `coordinates`
- [ ] **Dezaktywacja** — zabezpieczenie przed masową dezaktywacją (próg 60%) nietknięte
- [ ] **Geokoder** — limit `MAX_NEW_GEOCODES`, TTL null-cache i fleksja bez zmian (albo pokryte testami)
- [ ] **Zapisy JSON** — przez `atomic_json.atomic_write_json`, nie gołym `json.dump`
- [ ] **Frontend** — dane z OLX przepuszczone przez `escapeHtml()` / `safeUrl()` przed `innerHTML`
- [ ] **Ścieżki** — z `paths.py`, nie względne zależne od CWD
- [ ] **Harmonogram** — zmiana cronu odzwierciedlona w `main._calculate_next_scan_time`, `api_generator.SCAN_SCHEDULE` i README
- [ ] **Nowy generator** — wpięty w `scanner.yml` (krok + `git add` w commicie skanu)
