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
