# CSF Assessor Fleet — Accuracy Evaluation vs. Expert Golden Set

**Date:** 2026-08-31 · **Target:** Northwind Financial (demo persona) · **Run:** `7d74d63e…/41590f53…`

## What this measures

We validated the fleet's scoring against an **independent expert golden set** authored by
a cybersecurity practitioner — CMMI maturity scores (1–5) for **all 106 NIST CSF 2.0
subcategories**, rolled up to 22 Category averages and 6 Function Tiers, scored against the
same Northwind evidence the agents saw. The agents never see the golden scores; this is a
blind comparison of our automated assessment against expert human judgment.

- **Our run:** full Northwind corpus — evidence documents + questionnaire answers — scored
  end-to-end by the 6 specialist agents (all 22 categories, all 6 functions), completing with
  22 Category scores, 6 Function Tiers and 22 independent judge verdicts.
- **Harness:** [`csf_specialists/scripts/eval_golden.py`](../csf_specialists/scripts/eval_golden.py)
  (reproducible — see below).
- **Golden set:** [`docs/Golden Set.xlsx`](Golden%20Set.xlsx), published in this repo so the
  numbers below can be independently re-derived.

## Headline results

| Level | Metric | Result |
|---|---|---|
| **Function / Tier** | Tier agreement with the expert | **100% — 6 / 6 functions** |
| **Subcategory** | Within ±1 CMMI level | **100%** (106 / 106) |
| Subcategory | Exact match | 61.3% |
| Subcategory | Mean absolute error | 0.39 |
| Category | Within 0.5 of expert average | 68.2% (MAE 0.43) |
| Evidence | Cited the expert's primary evidence doc | 53.6% |

> **The fleet agrees with an expert on the maturity Tier for all 6 NIST CSF functions,
> and scores within one CMMI level on every one of 106 subcategories.**

## Per-function breakdown

| Function | Subcats | Exact | Within ±1 | Tier (ours / expert) |
|---|---|---|---|---|
| Detect   | 11 | 90.9% | 100% | 3 / 3 ✓ |
| Govern   | 31 | 87.1% | 100% | 3 / 3 ✓ |
| Identify | 21 | 57.1% | 100% | 2 / 2 ✓ |
| Protect  | 22 | 40.9% | 100% | 2 / 2 ✓ |
| Respond  | 13 | 38.5% | 100% | 2 / 2 ✓ |
| Recover  |  8 | 25.0% | 100% | 2 / 2 ✓ |

Every function's Tier matches the expert, and **every** subcategory lands within one CMMI
level — there are no outliers in this run. An earlier measured run had a single >±1
disagreement (`RC.CO-03`); it does not appear here.

## Notable disagreements (honest)

- **Systematic +1 on Identify** — the fleet scores `ID.RA-01/02/03/04/05/06/10` and `ID.AM-04`
  one level *higher* than the expert. A consistent cluster, not random noise, which points at
  rubric or prompt calibration rather than bad retrieval. It does **not** change any Function
  Tier. Deliberately not "fixed": with Tier agreement at 100% and every subcategory within ±1,
  tuning toward a single expert's scores risks overfitting to one opinion rather than
  improving accuracy.
- **Lower exact-match on Protect / Respond / Recover** (25–41%) with 100% within ±1 — the fleet
  sits consistently one level from the expert on these, rarely landing on the identical integer.

## Limitations (stated plainly)

- **Single organization** (Northwind), expert-authored ground truth — a validation against one
  practitioner, not a multi-company benchmark.
- **Run-to-run variance is real.** Across measured runs of this corpus, exact-match has ranged
  60.4–62.3%, within-±1 99.1–100%, and evidence precision 45.2–53.6%, because the underlying
  models are non-deterministic. **Tier agreement has been 6/6 on every run measured** — that is
  the stable figure, and the one to quote.
- **Evidence-doc precision (53.6%)** measures whether we cited the *specific* document the
  expert named as primary. A miss here often means we cited a *different valid* document
  supporting the same finding, not that the finding was ungrounded. This metric varies more
  between runs than the accuracy figures do.

## Reproduce

```bash
# 1. Full run: create a session, ingest the Northwind docs, preseed the questionnaire answers:
PYTHONPATH=. poetry run python csf_specialists/scripts/preseed_questionnaire.py --session <SID>
#    then trigger the assessment (UI "Run assessment" or POST /sessions/<SID>/run)

# 2. Diff that run against the expert golden set:
PYTHONPATH=. poetry run python -m csf_specialists.scripts.eval_golden \
    --session <SID> --run <RID>
```

The golden set ships in this repo at `docs/Golden Set.xlsx` and is the script's default, so
step 2 is runnable against any completed run without additional data.
