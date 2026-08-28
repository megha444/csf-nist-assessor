# CSF Assessor Fleet — Accuracy Evaluation vs. Expert Golden Set

**Date:** 2026-08-27 · **Target:** Northwind Financial (demo persona) · **Run:** `35123c2d…/ec686fc3…`

## What this measures

We validated the fleet's scoring against an **independent expert golden set** authored by
a KPMG cybersecurity practitioner — CMMI maturity scores (1–5) for **all 106 NIST CSF 2.0
subcategories**, rolled up to 22 Category averages and 6 Function Tiers, scored against the
same Northwind evidence the agents saw. The agents never see the golden scores; this is a
blind comparison of our automated assessment against expert human judgment.

- **Our run:** full Northwind corpus — 33 evidence documents + 234 questionnaire answers —
  scored end-to-end by the 6 specialist agents (all 22 categories, all 6 functions).
- **Harness:** [`csf_specialists/scripts/eval_golden.py`](../csf_specialists/scripts/eval_golden.py)
  (reproducible — see below).

## Headline results

| Level | Metric | Result |
|---|---|---|
| **Function / Tier** | Tier agreement with the expert | **100% — 6 / 6 functions** |
| **Subcategory** | Within ±1 CMMI level | **99.1%** (105 / 106) |
| Subcategory | Exact match | 60.4% |
| Subcategory | Mean absolute error | 0.41 |
| Category | Within 0.5 of expert average | 68.2% (MAE 0.41) |
| Evidence | Cited the expert's primary evidence doc | 47.6% |

> **The fleet agrees with a KPMG expert on the maturity Tier for all 6 NIST CSF functions,
> and scores within one CMMI level 99% of the time across 106 subcategories.**

## Per-function breakdown

| Function | Subcats | Exact | Within ±1 | Tier (ours / expert) |
|---|---|---|---|---|
| Detect   | 11 | 90.9% | 100% | 3 / 3 ✓ |
| Govern   | 31 | 87.1% | 100% | 3 / 3 ✓ |
| Identify | 21 | 47.6% | 100% | 2 / 2 ✓ |
| Respond  | 13 | 46.2% | 100% | 2 / 2 ✓ |
| Protect  | 22 | 40.9% | 100% | 2 / 2 ✓ |
| Recover  |  8 | 25.0% | 87.5% | 2 / 2 ✓ |

Every function's Tier matches the expert. All subcategory disagreements are within one CMMI
level except a single case (below).

## Notable disagreements (honest)

- **Systematic +1 on Identify** — the fleet scores `ID.RA-01/03/04/05/06` and `ID.AM-02/04/05`
  one level *higher* than the expert (a consistent, not random, pattern). Under investigation
  as a calibration item — see `internal_docs/identify_scoring_investigation.md`. It does **not**
  change any Function Tier.
- **Largest single miss:** `RC.CO-03` (ours 1, expert 3) — the only >±1 disagreement; a
  missing-evidence case on our side.

## Limitations (stated plainly)

- Single organization (Northwind), expert-authored ground truth — a validation, not a
  multi-company benchmark.
- Evidence-doc precision (47.6%) measures whether we cited the *specific* document the expert
  named as primary; a lower number here often means we cited a *different* valid document for
  the same finding, not that the finding was ungrounded.

## Reproduce

```bash
# 1. Full run: create a session, ingest the 33 Northwind docs, preseed the 234 answers:
PYTHONPATH=. poetry run python csf_specialists/scripts/preseed_questionnaire.py --session <SID>
#    then trigger the assessment (UI "Run assessment" or POST /sessions/<SID>/run)
# 2. Diff against the golden set:
PYTHONPATH=. poetry run python -m csf_specialists.scripts.eval_golden --session <SID> --run <RID>
```
