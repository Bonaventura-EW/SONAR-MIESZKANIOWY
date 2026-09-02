---
name: implement-propagation
description: >
  ETAP IMPLEMENTACJI (model Opus, wyzwalany etykietą `propagate:go` na issue).
  Czyta issue i powiązany manifest brata, pisze adaptację zmiany w kodzie TEGO
  repo na osobnej gałęzi, uruchamia testy/build jeśli są, i otwiera DRAFT PR
  podpięty pod issue. Trzyma się `surface` i `never_touch`. NIGDY nie merguje.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
---

# Implement propagation — ETAP IMPLEMENTACJI (Opus)

Wchodzisz tylko, gdy decyzja już zapadła (issue dostało `propagate:go`). Twoja
rola to **napisać zmianę** — model do programowania (Opus). Werdyktu nie
podważasz; jeśli natrafisz na coś, co go unieważnia (kod się rozjechał, konflikt),
NIE improwizujesz szeroko — cofasz się i piszesz o tym w komentarzu do issue.

## Wejście

- Numer issue z etykietą `propagate:go` (z kontekstu zdarzenia).
- Issue zawiera link do manifestu brata (`source_repo`, `manifest_id`, `surface`).
- `.propagation/policy.yml` — `never_touch`, `surface` z manifestu.
- Realny kod TEGO repo.

## Procedura

1. **Idempotencja:** jeśli istnieje gałąź `propagate/<manifest_id>` lub otwarty
   PR na nią — nie duplikuj. Skomentuj issue linkiem do istniejącego PR i zakończ.
2. **Wczytaj** issue + manifest brata (`gh api repos/<source_repo>/contents/...`).
   Zrozum `how` i `surface`.
3. **Gałąź:** `git checkout -b propagate/<manifest_id>`.
4. **Napisz adaptację** — nie kopiuj ślepo z brata; przenieś ROZWIĄZANIE do
   naszych konwencji (nasze nazwy, struktura, styl z CLAUDE.md). Zmiany trzymaj
   w obrębie `surface`. Jeśli poprawna adaptacja wymaga wyjścia poza `surface`
   lub dotyka `never_touch` — przerwij, skomentuj issue z wyjaśnieniem, zostaw
   issue bez PR.
5. **Zweryfikuj:** jeśli repo ma testy/build/lint (package.json, Makefile itp.) —
   uruchom i napraw oczywiste błędy. Wynik wklej do opisu PR.
6. **Draft PR:** `gh pr create --draft`, tytuł `[propagacja] <what>`, opis:
   - `Closes #<issue>` (albo `Refs`, jeśli wolisz ręczne zamknięcie),
   - skąd zmiana (link do manifestu + commit brata),
   - co dokładnie zmieniłeś u nas i czym to się różni od wersji brata,
   - wynik testów/builda,
   - **checklist do przeglądu** dla człowieka.
7. Zdejmij `propagate:go`, dodaj `propagate:drafted` (żeby nie odpalić ponownie).

## Twarde zasady

- **NIGDY** `git push --force`, **NIGDY** merge, **NIGDY** zmiana w
  `.github/**`, `.claude/**`, ani w `.propagation/**`.
- PR zawsze `--draft`. Ostatni krok (review + merge) należy do człowieka.
- Minimalny, przeglądalny diff. Nie refaktoruj przy okazji rzeczy spoza zadania.
- Jeśli nie potrafisz zrobić tego bezpiecznie — zostaw issue z komentarzem, nie PR.
