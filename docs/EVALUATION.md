# Evaluating recommendation quality

Technical tests check correctness, consistency and basic semantics. They do not
prove that users consider the ranking useful.

Prepare a UTF-8 JSON file containing a non-empty list of cases:

- `query`: the same fields as an examples/*.json request.
- `relevance`: an object mapping contractor IDs to human grades:
  0 = unsuitable preference match, 1 = weak, 2 = good, 3 = excellent.

Rate ALL contractors that pass mandatory conditions for each query, including
ones the model does not place in its top three. At least one must be relevant.
Do not use model scores as human labels. Have reviewers read original profiles;
include different cities, categories, budgets, negations and unusual requests.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_ranking path/to/ratings.json
```

The command reports mean nDCG@3: a value from 0 to 1 measuring ranking quality
against the supplied human judgments. It rejects missing eligible ratings rather
than silently treating unjudged contractors as bad matches.

No human-rated benchmark is included yet. No improved quality score is claimed.
Keep a fixed held-out set for comparing model or ranking changes.

## Regression fixes (v1.1)

Free-text preferences are encoded separately from the category/event context;
otherwise generic category words can outweigh a short specific request.
When preferences are empty, the existing category/event context is still used.

A small Russian rule layer checks explicit statements about contests and games.
Unqualified requests such as "без конкурсов" are checked against explicit absence
or offers in descriptions. Conflicting profiles stay eligible under the structured
filters, but sort after non-conflicting profiles and have a visible warning.
Absence of evidence is not a promise. Qualified phrases ("без банальных конкурсов"),
double negations and mixed statements are deliberately not treated as universal
absence claims. This does NOT cover arbitrary negation, synonyms or all languages.
The neural model still performs semantic ranking; rules never replace inference.

`tests/test_preferences.py` includes the reproduced failure and opposite requests,
unsupported wishes, qualifications, double negations, source evidence and determinism.
These artificial fixtures are regression checks, not a human-rated quality benchmark.
No overall accuracy or perfect understanding is claimed.
