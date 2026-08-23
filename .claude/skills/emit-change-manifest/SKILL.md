---
name: emit-change-manifest
description: >
  Wywołaj po każdej NIETRYWIALNEJ zmianie w tym repo (nowa funkcja, refactor,
  fix perf/a11y, bump zależności z efektem). Tworzy manifest w
  .propagation/changes/ opisujący co/jak/dlaczego, żeby repo-bracia mogły
  ocenić, czy warto to u siebie wdrożyć. Nie wołaj dla literówek, formatowania
  ani zmian czysto lokalnych bez wartości dla rodzeństwa.
allowed-tools: [Read, Write, Bash]
---

# Emit change manifest

Jesteś w trybie interaktywnym, właśnie skończyłeś istotną zmianę. Zanim uznasz
zadanie za zakończone, wyprodukuj manifest dla repo-braci.

## Kroki

1. Przeczytaj `.propagation/changes/_TEMPLATE.md` i `.propagation/policy.yml`
   (pola `repo`, `family`).
2. Ustal `category`, `surface` (z gita: `git diff --name-only`), `commit`
   (`git rev-parse HEAD`).
3. **Oceń `generality` uczciwie** — to najważniejsze pole:
   - `local` — sensowne tylko tu (nazwy, treści, integracje specyficzne dla repo).
     Manifest i tak zapisz, ale bracia go pominą.
   - `family` — wzorzec, który bracia z tej samej rodziny mogą mieć u siebie.
   - `universal` — użyteczne szerzej.
   Zaniżaj, nie zawyżaj. Fałszywy `universal` zasypie braci szumem.
4. `propagate`: Twoja szczera podpowiedź (yes/maybe/no) — bracia i tak decydują sami.
5. Zapisz `.propagation/changes/<id>.md` wg szablonu. `id` = `<data>-<krótki-slug>`.
6. Zacommituj manifest RAZEM ze zmianą (ten sam PR/commit).

## Zasady

- Jedna zmiana = jeden manifest. Nie łącz niezwiązanych rzeczy.
- `what` to jedno zdanie. `how` zwięźle, ale tak, by brat bez kontekstu zrozumiał podejście.
- Jeśli zmiana świadomie ROZJEŻDŻA to repo z braćmi (celowo lokalna decyzja),
  ustaw `generality: local` i w treści dopisz dlaczego — to chroni przed
  przypadkowym zlaniem projektów w jeden.
