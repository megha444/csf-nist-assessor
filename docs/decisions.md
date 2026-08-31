# Architecture Decision Records

Presentation-ready notes on the load-bearing choices in the CSF Assessor Fleet. Each ADR is scannable in 60 seconds and includes talking points for the demo Q&A and any post-hackathon interview.

Status legend: 🟢 accepted · 🟡 accepted but revisit-later · 🔴 superseded.

Related docs: [architecture.md](architecture.md) · [eval_results.md](eval_results.md) · [tier vs cmmi.md](tier%20vs%20cmmi.md).

---

## ADR-0001 — Vector store: Qdrant Cloud (not Vertex AI Vector Search)   🟡

**Date:** 2026-08-13

### Context
The specialists need a vector search backend to retrieve evidence chunks per assessment. The original plan locked Vertex AI Vector Search (all-GCP). Local dev revealed friction: creating a Vertex Vector Search index takes ~30 minutes per iteration, which kills the tight rebuild loop we need in a 19-day sprint. Megha already had Qdrant running in local Docker for another project.

### Decision
Use **Qdrant Cloud** (managed cluster hosted by Qdrant Solutions on GCP `us-east4`) as the vector store for both dev and prod. Local Docker Qdrant remains an option for offline dev; env vars swap between the two.

Wrapper module `csf_gateway/app/ingest/vector_store.py` abstracts the client so a future swap to Vertex AI Vector Search is a one-file change, not a systemic refactor.

### Alternatives considered
1. **Vertex AI Vector Search** (original plan). Native GCP, but ~30 min index-create wait per iteration + a different filter/query API. Rewrite cost estimated ~1 hr.
2. **Self-host Qdrant on GCE.** Adds an ops moving part + ~$14/month from credits. No advantage over managed.
3. **Tunnel local Qdrant via ngrok/cloudflared.** Fragile for a live demo; drops = demo dies.

### Consequences
- ✅ Dev iteration stays fast (Qdrant collection creation is instant)
- ✅ Judges hit a real network-accessible instance from Cloud Run
- ✅ Familiar client, simpler filter syntax
- ✅ Data still lives on GCP infrastructure (Qdrant Cloud runs the cluster on GCP `us-east4`), so the "GCP-hosted" story mostly holds
- ⚠ Third-party dependency (Qdrant Solutions Inc.) — a purist Fortified-track judge could dock a point for not being 100% GCP-native services
- ⚠ Client version pinning: cluster is Qdrant 1.19, client is pinned 1.16 for compatibility with the older local Docker. Version-mismatch warning is cosmetic; upgrade to 1.19 client is on the housekeeping list.

### Demo-Q&A talking points
- "We keep the vector store abstracted behind `vector_store.py` — swapping to Vertex AI Vector Search is a one-file change, and we'd do that in production if the customer required a strict all-GCP data-residency posture."
- "Qdrant Cloud runs the cluster on Google infrastructure in `us-east4`, so this isn't a cross-cloud dependency — data doesn't leave GCP's network."
- "The dev-loop cost of Vertex Vector Search's 30-minute index creation wasn't tolerable in a 19-day sprint; managed Qdrant made the demo shippable."

### Revisit-when
- Post-hackathon, if a real customer (say, a regulated bank) needs all-GCP-native. Then a Phase 3 hardening item swaps to Vertex Vector Search.

---

## ADR-0002 — Rubric scope: per CSF Category, not per Subcategory   🟢

**Date:** 2026-08-13

### Context
NIST CSF 2.0 has 6 Functions → ~22 Categories → ~106 Subcategories. The original plan locked scoring at the Subcategory level (~106 × 5 CMMI cells = ~530 rubric cells for the domain expert to author). That is the domain expert's single biggest deliverable and paces the entire domain track.

### Decision
Score CMMI at the **Category level (~22)** instead. The domain expert writes ~22 × 5 = ~110 cells. Aggregation still rolls up to CSF Tier 1-4 per Function.

### Consequences
- ✅ The domain expert's rubric authoring drops from ~500 cells to ~110 cells — realistic in the timeline
- ✅ Agent cost drops from ~60 Flash calls/run to ~22 (~$0.05 instead of $0.15)
- ✅ Report table stays scannable (22 rows vs. 60+)
- ⚠ Slight loss of fidelity — a Category with 4 well-managed Subcategories and 1 broken one shows up as CMMI 3 instead of pinpointing the broken one. Mitigated by capturing the fine-grained finding in the reasoning field per Category.
- ⚠ Divergence from standard practice — the domain expert's real-world engagements often go to Subcategory. For the demo they are already Category-focused for Northwind.

### Demo-Q&A talking points
- "In production this scales down naturally: adding Subcategory-level scoring is more agent calls with the same rubric structure — no architectural change. We chose Category for the demo because it lines up with the level a board consumes and finishes in 19 days."
- "The two-layer story is intact: CMMI 1-5 per Category for practitioners, Tier 1-4 per Function for executives. That maps directly to how to deliver these engagements."

### Revisit-when
- If we ship this as a real product, add Subcategory-level scoring as a "detailed" mode. Same agents, same rubrics, just more calls.

---

## ADR-0003 — PDF ingest: Gemini multimodal   🟢

**Date:** 2026-08-13

> The decision (multimodal-in ingest rather than a parser library stack) stands. The model
> named below was the current Flash at the time of writing; ingest now runs on
> `gemini-3.5-flash` — see [ADR-0005](#adr-0005--model-selection-gemini-35-flash--gemini-37-flash-no-pro-tier-available).

### Context
Policy docs (SANS templates, the domain expert's Northwind package) contain narrative text plus tables plus the occasional chart or image. Extraction quality matters — an agent scoring "PR.AA-05 (MFA on privileged accounts)" needs to find MFA policy text even when it's in a table cell, not free prose. The standard approach is `pypdf` + `pdfplumber` (tables) + `PyMuPDF` (images) + Tesseract or Vertex AI Document AI (OCR for scanned pages) — four libraries to stitch, none handling chart semantics.

### Decision
Use **Gemini 2.5 Flash multimodal** at ingest time. Each PDF is passed to Gemini with a prompt: "convert to structured markdown, preserve headings, render tables as markdown tables, insert `[Figure N: description]` placeholders for charts/images." Output is text-only markdown ready for the section-aware chunker.

### Alternatives considered
1. **pypdf + pdfplumber + PyMuPDF + Document AI/Tesseract soup.** ~1 day of glue code, still misses chart semantics, brittle across policy layouts.
2. **Vertex AI Document AI.** Purpose-built parser, but adds a separate service to configure and doesn't natively describe charts.
3. **Skip charts/images entirely, text-only pypdf.** Cheapest, loses the visual-content information.

### Consequences
- ✅ One library, one call, handles text + tables + charts + images + scanned pages
- ✅ Cost is negligible: ~$0.005 per doc, ~$0.05 for a 10-doc Northwind package
- ✅ Robust to layout variance across policy authors
- ⚠ Latency: ~5-10s per doc for the multimodal pass (offset by async ingest UX — user sees a progress bar)
- ⚠ Depends on Gemini quotas — a hard rate-limit at scale, mitigated with retry/backoff
- ⚠ Non-deterministic: the exact markdown output can vary between runs. Chunking is idempotent by content-hash dedupe, but ML/eval numbers should be pinned by seed if we care

### Demo-Q&A talking points
- "Multimodal-in ingest was cheaper and more accurate than a library stack. It also let us handle scanned PDFs without a separate OCR pipeline."
- "The ingest cost is under half a cent per document — the total per-assessment cost is dominated by the ~22 scoring calls, not ingest."

### Revisit-when
- If a real customer needs on-prem PDF extraction with no external LLM call, swap in Document AI or an open-source Docling pipeline. Chunker downstream doesn't change.

---

## ADR-0004 — Deployment topology: 3 Cloud Run services + per-agent SA impersonation   🔴 SUPERSEDED

**Date:** 2026-08-13 · **Superseded:** 2026-08-31

> **⚠ This ADR describes a topology that was never built. It is kept for the reasoning, not the
> outcome.** What actually shipped:
> - **Two** Cloud Run *services* (`csf-gateway`, `csf-ui`) plus one Cloud Run **Job**
>   (`csf-worker`, six parallel executions). There is no `csf-specialists` service.
> - The Coordinator is **not** a Cloud Run service — it runs on **Vertex AI Agent Engine**
>   under a native **SPIFFE agent identity**.
> - There are **three** service accounts (`csf-gateway@` 13 roles, `csf-worker@` 9,
>   `csf-ui@` 5), not six per-agent SAs, and **no impersonation** anywhere. Agent Identity is
>   only supported on Agent Runtime, so the specialists — being Cloud Run Jobs — are
>   ineligible by platform design, not by omission.
>
> Current topology: [architecture.md](architecture.md).

### Context
The Fortified Enterprise Fleet track requires an Agent Identity model — "one IAM identity per agent." Literal reading = 8 Cloud Run services (1 gateway + 1 coordinator + 6 specialists). Reality = 8× cold starts, 8× deploy pipelines, 8× monitoring targets in a 19-day sprint. Simplest reading = 1 monolith with attribution-only "identity" (Firestore field, no IAM isolation) — weak Fortified story.

### Decision
Ship **3 Cloud Run services** with **per-agent service-account impersonation** inside the specialists container:

| Service | Contents |
|---|---|
| `csf-gateway` | Streamlit + FastAPI (ingest, session, chat proxy, report) |
| `csf-coordinator` | Coordinator agent + Interview Director agent |
| `csf-specialists` | All 6 Function specialist agents, Pub/Sub-triggered |

Inside `csf-specialists`, the container's default SA is granted permission to impersonate 6 dedicated per-agent SAs (`csf-agent-{function}@…`). Every Firestore + Vertex call an agent makes is authenticated as its own SA. Cloud Trace records the impersonated identity per span, so per-agent activity is auditable in the trace waterfall.

### Alternatives considered
1. **8 Cloud Run services** (literal). Strongest Fortified compliance. 8× cold starts + 8× deploy scripts — real cost in a 19-day sprint. Rejected.
2. **1 monolith.** Simplest. Per-agent identity is just a Firestore field — weakest Fortified story. Rejected.

### Consequences
- ✅ Per-agent identity is real (own SA, own IAM policies, own audit trail in Cloud Trace)
- ✅ Only 3 deploy pipelines to maintain
- ✅ Coordinator + specialists can scale independently on cold starts
- ⚠ SA impersonation needs the `iam.serviceAccountTokenCreator` role granted from container SA to each agent SA — one extra infra step, documented in `infra/setup.sh`
- ⚠ A Fortified-track judge who reads strictly might prefer literal 8-service isolation. Talking point below covers this.

### Demo-Q&A talking points
- "Every specialist agent runs under its own IAM service account via impersonation — Cloud Trace shows exactly which agent identity authenticated which Firestore read or Gemini call. That's the audit trail a real security customer needs."
- "We considered fully separate Cloud Run services per agent but the 8× cold-start latency would have pushed our 15-minute demo target to something no CISO would sit through. The impersonation pattern is standard GCP practice for multi-tenant workloads."

### Revisit-when
- Post-hackathon, if scale grows (many concurrent assessments or agents need different resource profiles), split specialists into 6 Cloud Run services. No code change to the agents themselves — only Pub/Sub subscription binding.

---

## ADR-0005 — Model selection: `gemini-3.5-flash` + `gemini-3.7-flash` (no Pro tier available)   🟢

**Date:** 2026-08-14

### Context
Hackathon rules require **Gemini 3.5 or newer** via Gemini API or Vertex AI. Original plan targeted "Gemini 3.5 Flash + Gemini 3.5 Pro" (Flash for specialists, Pro for coordinator + LLM-as-Judge). A live probe against Vertex AI showed:

- ✅ `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.7-flash` — all available on the `global` endpoint
- ❌ `gemini-3.5-pro`, `gemini-3-pro`, `gemini-3.7-pro` — 404 on this project as of Aug 14, 2026

**The Gemini 3.x family currently ships Flash + Flash Lite only. No Pro tier exists.**

Regional availability: 3.x models are served **only via the `global` Vertex endpoint** for this project (not `us-central1`, `us-east4`, `europe-west1`, or `asia-northeast1` in our probe — Tokyo did return 200 for Flash but not for others). Setting `GOOGLE_CLOUD_LOCATION=global` is required for the SDK to route correctly.

### Decision
- **Flash slot (specialist scoring — ~22 calls/run):** `gemini-3.5-flash`. Baseline compliance with hackathon rule; thinking-model quality for scoring.
- **"Pro" slot (LLM-as-Judge + coordinator reasoning):** `gemini-3.7-flash`. Since no 3.x Pro exists, the newest Flash plays the smarter-reviewer role. Positioned in the demo as "faster model does the mechanical scoring, newer model reviews for defensibility."
- **Region:** `GOOGLE_CLOUD_LOCATION=global` for all Vertex AI calls. GCS bucket + Firestore stay in `us-central1` (region baked into resource names, not this env var).

### Alternatives considered
1. **Same `gemini-3.5-flash` for both Flash and Judge.** Simpler, one model, but the "second opinion" story weakens if scorer and judge are literally the same weights.
2. **`gemini-3.5-flash-lite` for scoring + `gemini-3.5-flash` for Judge.** Cheaper. Downside: Lite has no thinking tokens; scoring quality on multi-hop reasoning would drop.
3. **Wait for Gemini 3 Pro release.** Not a hackathon-timeline option.
4. **Fall back to `gemini-2.5-pro`.** Would satisfy the "Pro" tier need but breaks the "3.5 or newer" hackathon rule. Rejected.

### Consequences
- ✅ Fully compliant with hackathon requirement #1 (Gemini 3.5+)
- ✅ Two-tier "cheap scorer, smarter reviewer" story intact — even more defensible now that they're different model versions
- ✅ 3.7 Flash cost per call is comparable to 3.5 Flash (both Flash-tier), so Judge budget stays ~same as original 2.5 Pro assumption
- ⚠ Both are thinking models — the judge model burns ~60-100 "thoughts" tokens per call even for trivial prompts. Add to cost accounting later.
- ⚠ Dependency on `global` region — a regional-outage story is different from us-central1 outages. Not a demo-window concern.
- ⚠ Regional resources (Cloud Run in us-central1, Firestore in us-central1) still fine; only the Vertex/GenAI SDK follows `GOOGLE_CLOUD_LOCATION=global`.

### Demo-Q&A talking points
- "The 3.x family is Flash-only right now — no Pro. We use `gemini-3.5-flash` for the ~22 scoring calls per assessment because it's the compliance floor, and `gemini-3.7-flash` as the reviewer because it's the newest thing available. When Google ships Gemini 3 Pro, the Judge is a one-line config swap."
- "Every Gemini call goes through Vertex AI on the `global` endpoint — that's a hackathon-rule requirement plus a data-residency choice."

### Revisit-when
- The moment Gemini 3.x Pro (or `gemini-3.5-pro` / `gemini-3.7-pro`) becomes available on Vertex. Swap `GEMINI_PRO_MODEL` in `.env` + Secret Manager, redeploy. No code change.

---

## ADR-0006 — Multi-tenant support: org-tagged payload now, full refactor deferred   🟡

**Date:** 2026-08-15

### Context
The Fleet is pitched as an AI consultant that runs an assessment for a company. In production, the same company would run an assessment annually — ideally reusing uploaded policy docs across engagements, comparing year-over-year Tier movement, and being isolated from every other tenant's data. The demo scope is single-company (Northwind Financial), single session — but the data model has to be honest about the multi-tenant intent, or reviewers will spot session-scoping as a scale-limit rather than a demo simplification.

Two paths to answer this:

- **Option 1 (shipped now):** Add a stable `org_id` field to every point in Qdrant + every row in Firestore. Retrieval helpers gain a `search_org()` that spans all of an org's sessions. No collection-model changes, no dedupe across sessions, no auth. ~15 min of work.
- **Option 2 (production model, deferred):** Real multi-tenant refactor — orgs are a first-class Firestore collection, docs live under the org (not the session), sessions reference `org_id` + a subset of `doc_ids`, cross-session dedupe, per-org access control.

### Decision
Ship **Option 1** for the hackathon. Explicitly note **Option 2 as planned, not built.** No production customer is running the demo; the point today is that the data model doesn't lie about what it can support.

### What Option 2 will include (post-hackathon roadmap)

| Piece | Change |
|---|---|
| New collection | `organizations/{org_id}` with `{name, industry, size, applicable_regs, target_profile, created_at, contacts[]}` |
| Doc ownership | Move docs from `sessions/{sid}/documents/{did}` to `organizations/{org_id}/documents/{did}`. Chunks stay under the doc. |
| Session model | Session gets `org_id` (already added in Option 1) + `included_doc_ids: list[str]` — the subset of org docs relevant to this assessment. |
| Ingest | Upload endpoint moves under `/organizations/{org_id}/documents`. Dedupe checked at org level, not session level. Uploading the same file twice to Acme in different sessions returns the existing doc_id. |
| Retrieval | Vector Search primary filter becomes `org_id`; `session_id` becomes an optional secondary filter (used only when we want a session-scoped view, e.g. audit trail of what the specialists actually looked at during Run N). |
| Auth | Per-org IAM binding — a caller can only read/write within an org they belong to. Adds an `X-Org-Id` header or session cookie. Enforced at the gateway. |
| UI | Streamlit gets an org picker at session creation. New session either targets an existing org (reuses its doc pool) or creates one on the fly. |
| Historical view | New endpoint `GET /organizations/{org_id}/history` — timeline of past runs with Tier deltas. |
| Migration | One-shot script that walks existing `sessions/*/documents/*`, moves to `organizations/{slug(target_org)}/documents/*`, updates session refs. |

### Consequences of Option 1 (what's live now)
- ✅ Every point in Qdrant carries `org_id` — cross-session retrieval by org is one function call away
- ✅ Every document row carries `org_id` — future migration to Option 2 is a re-parent, not a re-tag
- ✅ Reviewer story: "payload supports multi-tenant; we just haven't wired the UI/dedupe/auth for it yet"
- ⚠ Docs are still uploaded per-session. Uploading `password_policy.pdf` in Session A and Session B for the same org creates two doc rows, two chunk sets, two Qdrant vector sets. Costs 2× ingest.
- ⚠ No auth boundary — anyone with a session URL still sees that session's data regardless of org
- ⚠ Session `org_id` is derived from `target_org` by slugification (`"Acme Corp" → "acme-corp"`). Typos in the name create separate "orgs". Not enforced against a real orgs collection because that collection doesn't exist yet.

### Demo-Q&A talking points
- "The payload is multi-tenant-ready — every chunk carries `org_id` in addition to `session_id`. What we haven't built yet is the org-scoped doc pool, dedupe across sessions, and the per-org access boundary. That's a Phase 6 refactor in the roadmap and it's tracked as ADR-0006 in the decision log."
- "The demo shows one org, one session, but the retrieval helper `search_org(org_id, query)` already exists and works — swapping the specialists over to that is a one-line change once the doc-reuse story lands."

### Revisit-when
- Any real design partner runs a second assessment (they will want doc reuse immediately)
- Cross-tenant workloads land in the same GCP project (need real IAM boundaries, not URL-guessability)

---

## ADR-0007 — Per-Subcategory CMMI scoring, Category CMMI as deterministic mean, recommendations at Subcategory   🟢

**Date:** 2026-08-15 (revised same day — original gap-only flavor superseded)

### Context
Original design (implicit) put both CMMI scoring **and** recommendations at the Category level. Two things broke that assumption once we started building against the domain expert's actual reference materials:

1. **The demo money-shot is a Subcategory.** `PR.AA-05` (MFA on privileged accounts) is what a CISO cares about — not "Category PR.AA needs work." Category-only recommendations are too vague to demo.
2. **The domain expert's `Implementation Examples` file is Subcategory-granular.** Every Subcategory carries `Ex1, Ex2, ...` concrete practices from NIST. That's the natural key for "have you done this specific thing? no → gap." Losing that granularity throws away her authored material.
3. **The domain expert's real-world consulting practice is incremental.** They never write "here's how to go from CMMI 2 to CMMI 5." She writes "here's what to do next to go from 2 to 3, and if you have appetite, from 3 to 4." Any "reach the maximum level" recommendation reads as fantasy, not consulting.

### Decision (revised)
- **LLM scores at Subcategory level.** The specialist agent's output has a `subcategory_scores: list[SubcategoryScore]` field where each entry carries `{subcategory_id, cmmi_level 1-5, confidence, evidence_status, expected_practice, notes}`. The Category CMMI is then a **deterministic Python-computed `round(mean(sub.cmmi_level for sub in subs))`**, NOT an LLM output. This matches the domain expert's real practice (her draft data in `CSF 2.0-Implementation_Examples.xlsx` scored at Subcategory with `"Category = avg"`).
- **The domain expert's rubric authoring stays at Category level** — ADR-0002 unchanged. One 5-level rubric per Category is applied by the LLM at each Subcategory ("does this specific Subcategory's practice meet Level X as described by the Category rubric?"). NIST Implementation Examples provide the concrete "what mature looks like" for each Subcategory.
- **Recommendation templates** (the domain expert's Wed Aug 19 deliverable) are keyed by `(subcategory_id, level_transition)` — e.g. `("PR.AA-05", "1→2")`, `("PR.AA-05", "2→3")`. Text describes the next 1-2 CMMI-level moves only. Never "reach 5."
- **Roadmap ranking** (report phase) uses target-based math: `priority = (target_tier - current_tier_for_function) × subcategory_importance`. Ranked at Subcategory level; templates supply the incremental text.
- **Radar chart** unchanged — Function/Tier level with target overlay.
- **LLM cost + latency unchanged** — still one LLM call per Category, one Category retrieval. The LLM just outputs richer structured data in the same call.

### Alternatives considered
1. **Both scoring AND recommendations at Subcategory.** Truest to the domain expert's practice but ~5× rubric authoring burden. Blows past 19-day timeline. Rejected (ADR-0002 already said no).
2. **Recommendations at Category with "which subcategories drove this score" as a footnote.** Half-measure. The report's actionability lives in the recommendation text; if that text says "Category PR.AA at CMMI 2," it's not a demo-worthy finding. Rejected.
3. **Recommendation text that describes reaching the target tier in full.** the domain expert's view: not how consulting works. Rejected.

### Consequences
- ✅ Demo money-shot works: click PR.AA-05 in the report → see current gap (no MFA) → see next-level remediation
- ✅ The domain expert's Implementation Examples file is used natively as agent context
- ✅ The domain expert's rubric authoring stays at Category granularity (unchanged from ADR-0002)
- ✅ Recommendation template count stays around 30 (per-Subcategory-of-interest for the demo, not all 106) — they pick the ~20-30 most-likely gap subcategories to write templates for; unmatched gaps get a generic fallback text
- ⚠ One extra field per Category-scoring output; the agent's LLM prompt gains a "identify weak Subcategories" instruction. Adds ~30% to prompt length; cost impact negligible at 22 calls/run.
- ⚠ Template lookup logic: report needs to match identified `subcategory_gaps[].subcategory_id` + `(current_level → next_level)` transition against the domain expert's template map. Missing template → generic fallback + log warning.
- ⚠ The domain expert decides which ~20-30 Subcategories to write templates for. The demo needs at least PR.AA-05 covered. Document this priority in the domain expert's working doc.

### Demo-Q&A talking points
- "We score at Category to keep the rubric authoring realistic, but we identify gaps and give recommendations at Subcategory — because a CISO doesn't act on 'improve PR.AA,' they act on 'MFA is missing on privileged accounts.' The agent uses NIST's official Implementation Examples as its reference for what specific practices should be in place per Subcategory."
- "Every remediation is incremental — 'to move from CMMI 2 to CMMI 3, do X.' Not 'here's how to reach CMMI 5.' That matches how to delivers these engagements: a customer can absorb one or two maturity steps per cycle, not a moonshot."

### Revisit-when
- If a customer wants CMMI scoring at Subcategory granularity, we already have the gap-identification infrastructure — just enforces one score per Subcategory in aggregation. Rubric authoring is the blocker, not the code.
