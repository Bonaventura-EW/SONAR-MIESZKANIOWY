# Rejestr decyzji (`decisions.jsonl`)

Append-only. Jedna linia = jedno zdarzenie. To surowiec, z którego skill
`distill-policy` destyluje reguły i liczy scorecard autonomii. **Nie kasuj wpisów.**

Schemat jednej linii (JSON):

```json
{
  "ts": "2026-08-25T07:03:11Z",
  "manifest_id": "2026-08-25-hero-lazyload",
  "source_repo": "acme/site-ecofutural",
  "category": "perf",
  "verdict": "propose",          // propose | skip
  "autonomy": "ask",             // ask → issue | draft → draft PR
  "artifact": "issue#42",        // co powstało: issue#N (decyzja) | pr#N (implementacja) | none
  "reason": "Ten sam wzorzec hero co u nas; lazyload da realny zysk LCP.",
  "human_decision": null,        // WYPEŁNIASZ TY później: accepted | rejected | modified
  "human_note": null             // dlaczego — to najważniejsze pole do uczenia
}
```

Etap decyzji (Sonnet) pisze wpis z `artifact: issue#N`. Etap implementacji
(Opus) dopisuje osobny wpis z `artifact: pr#N` dla tego samego `manifest_id`.

Po tym, jak zamkniesz issue/PR, dopisz `human_decision` i `human_note`
(albo rób to hurtem raz na jakiś czas — `distill-policy` i tak czyta całość).
Bez `human_note` agent nie wyjdzie poza zgadywanie.
