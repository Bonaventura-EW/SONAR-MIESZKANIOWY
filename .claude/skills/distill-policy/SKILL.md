---
name: distill-policy
description: >
  Przebieg okresowy (np. raz w tygodniu). Czyta rejestr decyzji, liczy
  scorecard skuteczności per kategoria i PROPONUJE aktualizację polityki przez
  PR — nowe learned_rules i ewentualne awanse autonomii (ask → draft).
  Niczego nie wdraża sam; Ty zatwierdzasz PR. Auto-merge nie istnieje.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(gh:*)
  - Bash(git:*)
  - Bash(jq:*)
---

# Distill policy

To jest mechanizm "uczenia się". Model się nie douczy — więc wiedza narasta
TU, w polityce, w sposób jawny i zatwierdzany przez człowieka.

## Procedura

1. Wczytaj `.propagation/decisions.jsonl` i `.propagation/policy.yml`.
2. Weź tylko wpisy z wypełnionym `human_decision`
   (accepted / rejected / modified). Reszta = jeszcze nierozstrzygnięte, pomiń.
3. **Scorecard per kategoria:**
   - liczba propozycji, accepted, rejected, modified,
   - wskaźnik akceptacji = (accepted + modified) / propozycje,
   - próbka `human_note` (dlaczego odrzucane / poprawiane).
4. **Zaproponuj learned_rules** z wyraźnych wzorców w `human_note`
   (np. powtarzające się odrzucenia dotykające jednego modułu → reguła
   wykluczająca). Formułuj je jako krótkie, sprawdzalne zdania.
5. **Zaproponuj awanse autonomii** — kategoria kwalifikuje się do `ask → draft`
   gdy: ≥ 8 rozstrzygniętych propozycji ORAZ wskaźnik akceptacji ≥ 0.9 ORAZ
   0 odrzuceń z powodu ryzyka/bezpieczeństwa. Nigdy nie proponuj auto-merge.
   Degradacja (`draft → ask`) gdy wskaźnik spadnie < 0.6.
6. **Otwórz PR** na gałęzi `policy/distill-<data>`:
   - zmiany w `policy.yml` (nowe `learned_rules`, zmienione `categories`),
   - w opisie PR wklej scorecard (tabela) i UZASADNIENIE każdej zmiany z
     powołaniem na konkretne wpisy rejestru.
   PR ZAWSZE draft-do-decyzji. Nie merguj.

## Zasady

- Każda proponowana reguła musi wskazywać dowody (ile decyzji ją popiera).
- Nie usuwaj historii z rejestru. Nie edytuj cudzych `human_note`.
- Jeśli danych za mało (kategoria < 8 rozstrzygnięć) — nie awansuj, napisz to
  wprost w PR ("za mało danych, zostaje ask").
- Ton propozycji: pytający, nie dyrektywny. To Ty stawiasz granicę.
