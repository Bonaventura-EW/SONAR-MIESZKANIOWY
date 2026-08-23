---
name: evaluate-propagation
description: >
  ETAP DECYZJI (model Sonnet, cron pon/czw/sob). Zbiera nowe manifesty zmian od
  repo-braci, filtruje je przez politykę TEGO repo, ocenia dopasowanie do jego
  architektury i dla kandydatów OTWIERA ISSUE z werdyktem. NIE PISZE KODU.
  Greenlight do implementacji to etykieta `propagate:go` — nakłada ją sam
  (kategorie z autonomią `draft`) albo człowiek (kategorie `ask`). Loguje każdą
  decyzję. Nic nie merguje.
allowed-tools:
  - Read
  - Bash(gh:*)
  - Bash(git:*)
  - Bash(jq:*)
  - Bash(date:*)
  - Write
  - Edit
---

# Evaluate propagation — ETAP DECYZJI (Sonnet)

Działasz bez człowieka, model do rozumowania (Sonnet). Twoja rola to **tylko
decyzja**: co z tego, co zmienili bracia, warto rozważyć TU. Kodu NIE dotykasz —
od tego jest osobny etap na Opusie, który odpala etykieta `propagate:go`.
Ostrożność > kompletność.

## Wejście

- `.propagation/policy.yml` — repo, family, siblings, never_touch, categories,
  default_autonomy, learned_rules.
- `.propagation/state/last-review.json` — `last_review_utc`.
- `CLAUDE.md` i realny kod TEGO repo — do oceny dopasowania.
- Manifesty braci przez `gh` (env GH_TOKEN ma dostęp read do repo-braci).

## Procedura

1. **Wczytaj politykę i stan.**
2. **Zbierz manifesty braci** nowsze niż `last_review_utc`: dla każdego
   `sibling` → `gh api repos/<sibling>/contents/.propagation/changes`, sparsuj
   frontmatter, weź te z `family` == naszą i `date` > last_review.
3. **Pre-filtr (tani):** odrzuć gdy `generality: local`, `category` wykluczona
   przez politykę, `surface` trafia w `never_touch`, albo `manifest_id` już jest
   w `decisions.jsonl` (idempotencja — brak duplikatów i pętli).
4. **Ewaluacja dopasowania** ocalałych — w realnym kodzie TEGO repo sprawdź:
   czy jest analogiczny moduł? czy problem z `why` faktycznie tu występuje?
   czy `how` przeniesie się bez konfliktu ze świeżą pracą? czy nie łamie
   `learned_rules`? Werdykt `propose` / `skip` + jednozdaniowe `reason`.
5. **Dla każdego `propose` otwórz ISSUE** (szablon niżej). Etykiety zawsze:
   `propagation`, `family:<family>`, `cat:<category>`.
6. **Nałóż greenlight wg autonomii** kategorii
   (`categories[category]` else `default_autonomy`):
   - `ask`   → NIE dodawaj `propagate:go`. Issue czeka na człowieka.
   - `draft` → dodaj etykietę `propagate:go`. To wyzwoli etap Opusa, który
     napisze draft PR. (Kategoria zdobyła autonomię przez `distill-policy`.)
7. **Loguj ZAWSZE** — `propose` i `skip` dopisz linią do `decisions.jsonl`
   (`autonomy` = ask/draft, `artifact` = `issue#<n>`, `human_decision`/`human_note`
   = null).
8. **Zaktualizuj** `last_review.json` (`last_review_utc` = teraz UTC, `runs`+1),
   zacommituj rejestr i stan.
9. **Podsumowanie** do logu: ile manifestów, odfiltrowanych, issue, ile z `go`.

## Szablon issue

Tytuł: `[propagacja] <what> (z <source_repo>)`
Treść:
- **Skąd:** link do manifestu brata + commit.
- **Co / dlaczego:** `what` / `why`.
- **Jak u nich:** `how` + `surface`.
- **Dlaczego pasuje tutaj:** `reason` + nasz analogiczny moduł/ścieżki.
- **Ryzyka / na co uważać.**
- **Rekomendacja:** wdrożyć / odłożyć / odrzucić.
- **Jak zbudować:** dopisz `propagate:go`, a etap implementacyjny (Opus) otworzy
  draft PR. (Dla kategorii `ask` etykietę nakłada człowiek.)

## Twarde zasady

- Zero zmian w kodzie produktu. Zero `git push` poza commitem rejestru/stanu.
- Przy niepewności co do dopasowania: `skip` z uczciwym `reason`.
- Nie modyfikujesz polityki (od tego `distill-policy`).
