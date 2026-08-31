Good question. CMMI is more granular and more familiar to GRC audiences than CSF Tiers. Worth switching.

## Quick comparison

**CSF Tiers (1-4):** describe the *whole organization's* risk management posture. Coarse. Meant for executive framing, not per-control scoring.

**CMMI Levels (1-5):** describe *maturity of a specific process or control*. Granular. Meant for per-control scoring.

For your assessor, CMMI is a better fit because you're scoring 30+ subcategories individually, not the whole org.

## CMMI 1-5 (adapted for cyber controls)

**Level 1: Initial**
Control exists in some form but is ad-hoc, undocumented, inconsistent. Depends on individual heroics.

**Level 2: Managed**
Control is documented and performed, but only within specific teams or projects. Not org-wide.

**Level 3: Defined**
Control is standardized across the org. Written policies, assigned owners, followed consistently.

**Level 4: Quantitatively Managed**
Control is measured. Metrics collected (e.g., patch SLA compliance %, MTTR). Performance tracked against targets.

**Level 5: Optimizing**
Control is continuously improved based on metrics, threat intel, and post-incident learnings. Proactive tuning.

## What this changes in your build

**Rubric structure per subcategory** (teammate writes):
```
GV.OC-01: Organizational cybersecurity strategy is established
  Level 1: No written strategy; ad-hoc security decisions
  Level 2: Strategy exists for one BU or project only
  Level 3: Org-wide written strategy, owner assigned, reviewed annually
  Level 4: Strategy tied to measured KPIs (e.g., risk reduction targets)
  Level 5: Strategy adjusted quarterly based on threat intel + metrics
```

**Scoring output schema** (no change, just relabel):
```json
{
  "subcategory_id": "GV.OC-01",
  "cmmi_level": 3,
  "confidence": 0.87,
  "evidence_citation": "InfoSec Policy v2.1, Section 1.2, p.3",
  "reasoning": "Written strategy exists org-wide with named CISO owner..."
}
```

**Report changes**
- Radar chart: 6 axes (Functions), each showing average CMMI level 1-5
- Subcategory table: subcategory | CMMI level | target level | gap | evidence
- Roadmap: prioritized by (target level - current level) × business impact

**Demo language**
Instead of "You're Tier 2 on Protect" say "Your average Protect maturity is CMMI 2.4, with access control at Level 3 and vulnerability management at Level 1."

## Why this is better for your submission

1. GRC audiences immediately recognize CMMI. Judges scoring "Innovation & Operational Utility" who know the space will nod.
2. 5 levels give more differentiation. Tier 1-4 forces false precision when a control is between levels.
3. CMMI is used by CMMC, Cyber Essentials, and most Big 4 GRC practices.
4. Numeric scores (1.0-5.0 including decimals for aggregated Function scores) make the heatmap richer.

## One thing to note

CSF 2.0 itself does not officially prescribe CMMI. You're combining CSF's *what to assess* (108 subcategories) with CMMI's *how mature is each*. This is a very common consultant approach and totally defensible. Say so explicitly in the README and demo: "We use CSF 2.0 subcategories as the control taxonomy and CMMI 1-5 for per-control maturity scoring. This mirrors standard Big 4 assessment practice."

Ask your teammate: "CSF Tiers or CMMI 1-5 per subcategory?" If she says CMMI, you're good. If she prefers something else (some firms use custom 1-5 scales), use what she uses.