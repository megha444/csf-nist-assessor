# CSF Assessor Fleet — Session Handoff

Rewritten fresh Thu 2026-08-20 ~13:30 ET (previous version had grown into an unwieldy day-by-day log across Aug 15-20; this is a full rewrite organized by subsystem/current-state instead, for a new Claude session to pick up cleanly). If this file's own header date is now stale, trust the content over the date — but a session should still open by re-reading this in full before doing anything else.

---

## 1. What this project is

**CSF Assessor Fleet** — a multi-agent system that runs a NIST CSF 2.0 cybersecurity maturity assessment. Value proposition: replaces an $80K, 10-week Big 4 consulting engagement with a ~$0.50, ~15-minute automated run, while preserving evidence-cited findings, defensible scoring, and consultant judgment. Submitted to the **All Things Agentic Hackathon**, **Fortified Enterprise Fleet track**. Deadline **Mon 2026-08-31, 12:00 PM ET target / 8:00 PM ET hard deadline**.

**Repo:** `/Users/meghaagarwal/Desktop/Codes/Personal/csf-nist/`, branch `feat/ingest-pipeline`.

---

## 2. Team, division of labor, and how Megha works

**Megha** — sole technical lead. Fluent in Python and cloud infra. Writes all code.
**Sakina** (KPMG cybersecurity practitioner) — owns all domain content: CMMI rubrics, interview questions, Northwind reference documents, recommendation templates, exec-summary tone/wording.

**Hard rule:** Megha never invents domain content (rubric text, interview questions framed as if from a real consultant, exec summary language). Sakina never writes code. The one accepted exception: Megha authors clearly-labeled **synthetic stand-in data** (sample interview questions, synthetic Q&A test fixtures, preseed answers) when Sakina is running behind, explicitly as a temporary testing/regression harness — never presented as real client evidence, and never a substitute for CMMI rubrics specifically (those stay a hard blocking dependency).

**Sakina has been running 3-5+ days behind the plan's own dates throughout.** Don't assume the dated plan in `task_list.md` reflects reality for her items — check `Ref Docs/NIST Rubrics.xlsx`'s actual sheet list for ground truth on which Function rubrics exist.

**How Megha likes to work with Claude, learned over this session:**
- **Fast, iterative, hands-on.** Typical loop: Claude builds/fixes something → Megha tests it live in the running Streamlit app or via a real API call → reports back with a pasted error, traceback, or screenshot → Claude root-causes it (not a band-aid) → fixes → repeat. Expect several rounds of this per feature.
- **Verify for real, not just "no exception."** When something can be checked against live infra (Firestore, Cloud Trace, a real LLM call), actually check it — don't stop at "the code ran without crashing." Example from today: a Cloud Trace export looked broken on a first check (empty query result), and the honest move was to dig into *why* rather than declare success or failure prematurely — turned out to be indexing lag, confirmed by widening the query window and finding the real spans.
- **No browser access in this environment** — for any Streamlit/UI change, say so explicitly and ask Megha to verify visually rather than claiming a UI change "works." Syntax-checking a `.py` file is not the same as confirming it renders correctly.
- **Root-cause fixes, not workarounds.** E.g., a hung gateway process was force-killed and the actual race condition in the startup command was fixed (added a `sleep`), not just "restart and hope." A Streamlit fragment bug went through two real iterations to find the actual API constraint, not a workaround.
- **Keep `task_list.md` and this file continuously in sync**, not just at session end. Megha references both directly and expects them to reflect true current state at any point in time — mark items `[x]` the moment they're genuinely done and verified, with enough detail that a cold read explains *what* was built and *how it was confirmed*, not just "done."
- **Be honest about deprecated/imperfect choices** rather than hiding them — e.g., `SequentialAgent` (ADK) and `CloudTraceSpanExporter` (OpenTelemetry) are both flagged deprecated upstream but still used deliberately, with the reasoning written inline in the code, not swept under the rug.
- **Proportionate engineering** — this is a hackathon project on a hard deadline. Prefer the native/built-in mechanism over a custom one (e.g., ADK's own `retry_options` over hand-rolled retry logic; Streamlit's `st.fragment`/`run_every` over a manual polling loop) once it's confirmed to actually exist and work. Don't add abstractions, feature flags, or config options beyond what's asked.
- **A separate running doc, `docs/pipeline_walkthrough.md`**, was built up conversationally today/yesterday as a plain-language + code-pointer explanation of how the whole pipeline actually works (interview → scoring → aggregation → judge), for Megha's own understanding before planning further work. It's gitignored (intentionally personal, not shipped) but still on disk — **read it** for a deep, already-written explanation of Stages 2-6 before re-deriving anything from scratch. Stage 1 (ingest) and Stage 7 (report gen) were never filled in.
- **Edit summaries:** after a set of edits, Megha wants: what was built, what to expect, how to test it manually. This has been the standing pattern all session — keep doing it.

---

## 3. Where things stand today (Thu Aug 20, ~1:30 PM ET)

**Live end-to-end demonstration exists and works,** including the full automated pipeline: upload docs → interview (AI picks Function + question) → "Run assessment" → dispatch (real Pub/Sub) → score (Gemini, retried on transient failure) → aggregate (Category CMMI → Function Tier) → **Judge** (independent defensibility review, also just wired in) → report (Streamlit native + downloadable HTML/Excel) — all traced to Cloud Trace as of today.

**3 of 6 Function specialist agents exist:** Govern, Identify, Protect. Each is a ~3-line config wrapper around one fully generic `SpecialistAgent` base class — adding a new Function is now a ~10-minute job **the moment its rubric lands from Sakina**. Detect, Respond, Recover do not exist yet — blocked purely on Sakina's rubrics, not on any remaining code work.

**Today's session (this session) did three things:**
1. Cleared **all 5** of yesterday's UI/UX backlog items (session-naming, doc-upload polling, Chat "Run assessment now" button + navigate-then-run ordering fix, and the Overview/per-Function radar chart redesign in both Streamlit and the exported HTML report) — see §7.6.
2. Found and fixed a real production bug: a `429 RESOURCE_EXHAUSTED` on "Run assessment," root-caused to zero retry logic anywhere in the codebase — fixed via ADK's native retry mechanism, applied everywhere an LLM gets called (§7.7).
3. Built and wired in **LLM-as-Judge** (§7.5) and **Agent Observability v1** (§7.8) — two previously-stubbed/never-started pieces, both verified against real infra, not just locally.

**Uncommitted right now** (see `git status` for the exact list — as of this writing: `csf_coordinator/interview.py`, `csf_specialists/agent_base.py`, `csf_specialists/scripts/export_html.py`, `csf_specialists/templates/report.html.j2`, `csf_ui/app.py`, `docs/HANDOFF.md`, `poetry.lock`, `pyproject.toml`, `task_list.md`, plus new untracked `csf_gateway/app/tracing.py`). Megha has been committing periodically herself via the IDE throughout the day (not something Claude has done) — check `git log` for the real commit boundary before assuming what's shipped vs. still local.

**The single biggest structural risk, unchanged for days:** the golden test set (Northwind docs + expert CMMI scores) has never been delivered by Sakina. Every phase gate in `task_list.md` has a CMMI-agreement-percentage target (60/70/80%) that is currently **unmeasurable** — there's no ground truth to compare against.

---

## 4. Locked architecture — read these first for design rationale

1. **`docs/decisions.md`** — 8 ADRs (Architecture Decision Records). Most-referenced:
   - ADR-0001: Qdrant Cloud on GCP us-east4 (not Vertex AI Vector Search)
   - ADR-0002: Score at Category level (~22 rubrics, not ~106 Subcategory-level)
   - ADR-0003: Gemini 3.5 Flash multimodal for PDF ingest
   - ADR-0004: 3 Cloud Run services + per-agent SA impersonation (Agent Identity — not yet built, see §7.9)
   - ADR-0005: `gemini-3.5-flash` (scoring) + `gemini-3.7-flash` (Judge — the "Pro slot," no Gemini 3.x Pro tier exists)
   - ADR-0006: Multi-tenant model, org_id shipped, full refactor deferred
   - ADR-0007 (revised): Per-Subcategory CMMI scoring, Category = round(mean); recommendations keyed by (subcategory_id, level_transition)
   - (An 8th, implicit in code comments rather than a numbered ADR: adaptive `top_k` for retrieval)
2. **`docs/architecture.md`** — 6 Mermaid diagrams (system context, deployment, user journey, data flow, Fortified components, environments)
3. **`docs/lld.md`** — Firestore schema, Qdrant config, REST endpoints, Pydantic models, agent contract, sequence diagrams (including the Judge sequence, now implemented), env vars, testing map
4. **`docs/csf_assessor_hackathon_plan.md`** — canonical 19-day plan
5. **`docs/pipeline_walkthrough.md`** — gitignored, personal, but the most detailed plain-language explanation of Stages 2-6 that exists anywhere; read it
6. **`task_list.md`** — daily strategic checkbox tracker, kept continuously current

**Ref materials from Sakina** (gitignored, in `Ref Docs/`):
- `NIST Rubrics.xlsx` — **as of today: 3 sheets (Govern, Identify, Protect)**. Check this file's sheet list directly (`openpyxl.load_workbook(...).sheetnames`) any time you need current ground truth on rubric availability — faster and more reliable than trusting a stale doc.
- `CSF 2.0-Implementation_Examples.xlsx` — NIST's own official per-Subcategory examples, all 6 Functions (this one has always covered all 6, independent of Sakina's rubric delivery — don't confuse "examples exist" with "rubric exists").
- `02. Documents/` — the real 16-document Northwind package (delivered Aug 15-17, exceeded the original 5-7-doc ask). 14 of 16 are ingestable (`.xlsx` support added Aug 18); the 2 `.pptx` files remain explicitly deferred, not built.

---

## 5. Repo file map (everything that matters)

```
csf-nist/
├── task_list.md                    daily tracker — READ THIS + this file first, every new session
├── test_commands.md                 gitignored, Megha's personal scratch of copy-pasteable test commands
├── docs/
│   ├── HANDOFF.md                   this file
│   ├── pipeline_walkthrough.md      gitignored — deep plain-language pipeline explanation (Stages 2-6)
│   ├── decisions.md                 8 ADRs
│   ├── architecture.md              Mermaid diagrams
│   ├── lld.md                       schemas + contracts + sequence diagrams
│   ├── csf_assessor_hackathon_plan.md   canonical 19-day plan
│   └── tier vs cmmi.md              why Tier (1-4) and CMMI (1-5) are different scales
├── pyproject.toml + poetry.lock     deps — google-adk, fastapi, qdrant-client, google-genai, python-docx,
│                                    streamlit, plotly, jinja2, opentelemetry-* (added today)
├── .env / .env.example              Qdrant URL/key, GCP project, model IDs (gitignored)
├── infra/
│   ├── setup.sh                     GCP bootstrap — buckets, Firestore, Pub/Sub (7 topics), Secret Manager,
│   │                                 Cloud Trace API enablement (all Day 1, already done)
│   ├── qdrant_setup.py               creates csf_chunks collection + payload indexes
│   ├── build_rubric_yaml.py          --function <name>|all — extracts Sakina's xlsx → YAML. Idempotent,
│   │                                 safe to re-run any time a rubric sheet is added.
│   └── deploy_gateway.sh             gcloud run deploy for csf-gateway
├── csf_gateway/                     THE DEPLOYED SERVICE (Cloud Run)
│   └── app/
│       ├── main.py                   FastAPI app, mounts all routers
│       ├── config.py                 Pydantic Settings — get_settings(), model names, GCP project
│       ├── llm.py                    NEW today — gemini_model(name) wraps a model name with ADK retry/backoff.
│       │                             USE THIS, not a bare model-name string, at every LlmAgent(model=...) call.
│       ├── tracing.py                NEW today — get_tracer(name), Cloud Trace export, Agent Observability v1
│       ├── csf_catalog.py            22 CSF Categories with keywords, Function name/code maps
│       ├── doctype_taxonomy.py       hardcoded doc types + Function map
│       ├── schema.py                 all Pydantic DTOs — ScoreOutput, SubcategoryScore, TierResult,
│       │                             JudgeResult, Defensibility, EvidenceCitation, PreseedRecord, etc.
│       ├── sessions.py                session CRUD + list + FastAPI router
│       ├── documents.py               batch upload + per-doc status polling (progress_pct)
│       ├── chat.py                    interview chat — /next (AI auto-picks Function), /answer, /finish, /history
│       ├── qna.py                     freeform Q&A document upload+extraction (POST /sessions/{sid}/qna)
│       └── ingest/                    async pipeline
│           ├── storage.py             GCS raw upload
│           ├── dedupe.py              SHA256 dedupe per session
│           ├── pdf_parser.py          Gemini multimodal → markdown
│           ├── docx_parser.py         python-docx → markdown (null-checks para.style, a real bug found once)
│           ├── xlsx_parser.py         openpyxl → markdown (.pptx NOT built, deferred)
│           ├── chunker.py             section-aware + page markers
│           ├── tagger.py              keyword → candidate_categories
│           ├── embedder.py            text-embedding-004, batched
│           ├── vector_store.py        Qdrant wrapper — search_session, search_org
│           ├── firestore_writer.py    document + chunks + status transitions
│           └── orchestrator.py        glues ingest together (asyncio.create_task)
├── csf_coordinator/                  orchestration (dispatch → aggregate → judge)
│   ├── coordinator.py                 run_assessment() — ADK SequentialAgent: CreateRunStep → DispatchStep(s)
│   │                                  → CollectResultsStep → AggregateStep(s) → JudgeStep(s) [new today]
│   ├── steps.py                       the individual BaseAgent step classes, incl. JudgeStep [new today]
│   ├── interview.py                   Interview Director — decide_next_question / decide_next_question_auto
│   ├── pubsub_client.py               thin Pub/Sub publish/pull wrapper
│   └── prompts/next_question.txt      Interview Director's literal prompt (has a known TODO, see §9)
├── csf_specialists/                  specialist agents + shared scoring/judging logic
│   ├── loaders.py                     load_rubric / load_implementation_examples, LRU-cached
│   ├── agent_base.py                  SpecialistAgent class — score_category (now span-wrapped, see §7.8)
│   ├── aggregate.py                   cmmi_to_tier + aggregate_function (Category-weighted) + persist_tier
│   ├── judge.py                       NEW yesterday, wired in today — LLM-as-Judge, see §7.5
│   ├── worker.py                      Pub/Sub pull-side consumer, one process per Function (--function <fn>)
│   ├── agents/
│   │   ├── govern.py / identify.py / protect.py    3-line config wrappers, one per live Function
│   │   └── __init__.py                AGENTS registry — coordinator/worker key off this, not hardcoded names
│   ├── qna_extractor.py               ADK structured-output extraction of Q&A pairs from a questionnaire doc
│   ├── prompts/
│   │   ├── score.txt                   scoring prompt (rubric applied per-Subcategory)
│   │   ├── judge.txt                   NEW yesterday — Judge's literal prompt
│   │   └── qna_extract.txt             Q&A extraction prompt
│   ├── rubrics/                        {function}.yaml, Sakina-authored, extracted via build_rubric_yaml.py
│   │   └── govern.yaml, identify.yaml, protect.yaml   (detect/respond/recover: waiting on Sakina)
│   ├── implementation_examples/        {function}.yaml, NIST's own, ALL 6 already extracted (independent
│   │                                    of rubric availability — source xlsx always had all 6)
│   ├── sample_data/                    Megha-authored stand-ins (labeled, temporary, see §2's hard rule)
│   │   ├── govern_questions.json        8 seed questions, 4 of Govern's 6 Categories — Identify has NONE
│   │   ├── northwind_preseed_govern.json  21 already-answered Q&A, loaded via preseed_govern.py
│   │   └── northwind_qna_sample.docx    25-pair synthetic questionnaire (14 Govern + 11 Identify),
│   │                                    built today for testing the Q&A upload/extraction path
│   ├── templates/report.html.j2         Jinja2 — exported HTML report (redesigned today, see §7.6)
│   └── scripts/
│       ├── preseed_govern.py            loads a PreseedRecord JSON into sessions/{sid}/answers/
│       ├── export_json.py               report v1 — pure-data JSON builder, everything else builds on this
│       ├── export_excel.py              client-facing Excel export
│       └── export_html.py               report v2 — HTML + Plotly, redesigned today (per-Function radars)
├── csf_ui/app.py                     Streamlit app — THE live UI, `poetry run streamlit run csf_ui/app.py`
│                                      (port 8501). Redesigned multiple times today, see §7.6.
├── SANS-Security-Policy-Templates-main/   generic test-doc corpus (gitignored pattern SANS-*)
├── Ref Docs/                          Sakina's real source files, gitignored
└── 02. Documents/                     the real 16-doc Northwind package, gitignored
```

---

## 6. Deployed system

- **Cloud Run URL:** `https://csf-gateway-jdogd2dq2q-uc.a.run.app` (may be stale relative to local — most of today's work was tested locally, not redeployed)
- **GCP project:** `csf-assessor-hackathon`
- **Firestore:** native mode, default database. `sessions/{sid}`, scores at `sessions/{sid}/runs/{rid}/scores/{category_id}`, tiers at `.../tiers/{function}`, **judge verdicts at `.../judge/{category_id}`** (new today)
- **Qdrant Cloud** (GCP us-east4) — collection `csf_chunks`
- **Models:** `gemini-3.5-flash` (scoring/interview/Q&A extraction), `gemini-3.7-flash` (Judge — the "Pro slot"), `text-embedding-004` (embeddings). All model construction should go through `csf_gateway/app/llm.py`'s `gemini_model()` now, not a bare string.
- **Region gotcha:** Vertex calls use `GOOGLE_CLOUD_LOCATION=global` — Gemini 3.x isn't served regionally on this project.
- **Local dev ports:** gateway on 8090, Streamlit on 8501. Standard startup sequence is in `test_commands.md` — **includes a `sleep 1` between kill-old-process and start-new** (a real race condition bit us today; don't remove that sleep).
- **Cloud Trace:** now actually receiving spans (verified today via direct API query) — `csf.specialist.score_category` and `csf.interview.decide_next_question`, with ADK's own auto-instrumented spans nested underneath for free.

---

## 7. Subsystem status (what's built, how it works, how it's verified)

### 7.1 Ingest (Stage 1 — the one part `docs/pipeline_walkthrough.md` never covered)
Upload → GCS raw storage → dedupe (SHA256) → parse (Gemini multimodal for PDF, python-docx, openpyxl for xlsx) → section-aware chunk → keyword-tag candidate Categories → embed (text-embedding-004) → Qdrant upsert + Firestore metadata. `.pptx` explicitly deferred. Works end-to-end, verified many times since Aug 14.

### 7.2 Interview / question selection
Cross-Function need-ranking (`importance / (1 + coverage)`) picks which Function gets asked about; one LLM call per turn picks a seed question, generates a new one, or declares done. Full detail — including the "why a new ADK session every turn" design rationale (Firestore as source of truth, Cloud Run scale-to-zero safety) and 3 identified-but-not-yet-implemented caching opportunities — is in `docs/pipeline_walkthrough.md` Stage 2. **Known gap, not fixed:** doesn't reliably prefer high-importance unused seed questions over generating new ones (TODO left inline in `next_question.txt`).

### 7.3 Rubric usage + scoring
One `SpecialistAgent` per Function scores every Subcategory individually against the Category-level rubric text (Sakina writes rubrics at Category granularity to keep authoring effort down; the same text gets reapplied per Subcategory). Category CMMI is a deterministic `round(mean(subcategory scores))`, overriding whatever the LLM proposed — auditable, not a black box. Full detail in `pipeline_walkthrough.md` Stage 3&4.

### 7.4 Aggregation
Category CMMI (1-5) → Function Tier (1-4, NIST's own scale — a genuinely different concept, see `docs/tier vs cmmi.md`). Category-weighted mean with a confidence penalty (2+ low-confidence Categories knocks the Tier down by one). Deliberately NOT Subcategory-weighted — the two methods disagree by a full Tier on real data; Category-weighting won because it matches the system's architectural intent, not because of which number it produced. Full detail in `pipeline_walkthrough.md` Stage 5.

### 7.5 LLM-as-Judge — built yesterday, wired into the automated pipeline today
**Goal:** an independent second model reviews the first model's own score for defensibility (does the cited evidence support the claimed level, are citations specific, is confidence calibrated) — a genuine second opinion, not a rubber stamp. Proven live: caught a real internal-consistency defect (a Subcategory scored CMMI 4 despite the specialist's own gap text admitting it didn't meet the Level 4 bar).
- `csf_specialists/judge.py` — `judge_category` / `judge_run`, same ADK pattern as `agent_base.py`.
- `JudgeStep` in `csf_coordinator/steps.py`, composed into `coordinator.py`'s `run_assessment` sequence after `AggregateStep` — **now runs automatically on every "Run assessment"**, no manual step needed.
- Persists to `sessions/{sid}/runs/{rid}/judge/{category_id}`.
- **Not yet done:** neither `export_html.py` nor `export_json.py` reads the `judge/` collection — verdicts are persisted but invisible in every report/UI surface today. This is the natural next piece of this feature.
- **Real cost, not hidden:** roughly doubles LLM call volume per Function scored (documented in `coordinator.py`'s own docstring).

### 7.6 Streamlit UI + exported HTML report — today's biggest chunk of work
All 5 items from yesterday's live-testing backlog are done and verified (syntax + live browser confirmation from Megha), plus one follow-up fix:
1. **Session-naming** — sidebar "+ New session" is now a form (text input + submit), not a bare button; backend already supported `target_org`.
2. **Docs auto-polling** — live progress bars per in-flight document, polling only while something's actually in flight. **Took two real iterations** to get right — see §9's gotchas, this is a genuinely useful lesson on `st.fragment`.
3. **Chat "Run assessment now" button** — plus a same-day follow-up: navigation to Reports now happens *before* the assessment runs (not after), via a two-step flag pattern (`on_click` sets `session_state` flags only; the Reports view itself does the actual slow work).
4. + 5. **Radar chart redesign**, Streamlit + exported HTML both: Overview/header shows one Tier radar only; each Function gets its *own* Category radar (previously all Functions were incorrectly overlaid on one shared chart). Also fixed a real Plotly layout bug (charts weren't respecting their container width — `config={"responsive": True}` was missing) and a degenerate-single-Category rendering bug (was an invisible zero-area shape, now a marker point).

### 7.7 Reliability fix — retry/backoff on every LLM call
Found via a live `429 RESOURCE_EXHAUSTED` failure (triggered by Protect joining the agent registry — 3 concurrent workers instead of 2 — plus Judge roughly doubling call volume, landing the same week). Root cause: `LlmAgent(model="gemini-...")` — a bare string — resolves to zero retries in ADK, not even the framework's advertised defaults. Fixed via `csf_gateway/app/llm.py`'s `gemini_model()`, which wraps a model name in ADK's own native `Gemini(..., retry_options=HttpRetryOptions(...))`. Applied at **all four** `LlmAgent` construction sites (`agent_base.py`, `judge.py`, `interview.py`, `qna_extractor.py`) — not just where the error surfaced.

### 7.8 Agent Observability v1 — built today, one of the 6 Fortified components
`csf_gateway/app/tracing.py`'s `get_tracer()` — Cloud Trace export via OpenTelemetry, wrapped so a tracing failure can never break the pipeline it's observing. Applied to `agent_base.py::score_category` and `interview.py::decide_next_question` via a thin-wrapper pattern (renamed the originals to `_..._impl`, added span-wrapping public methods on top — avoided reindenting either ~100-line body). **Verified for real** via a direct Cloud Trace API query (not just "didn't crash") — spans genuinely land, and nest nicely under ADK's own auto-instrumented spans for free. `CloudTraceSpanExporter` is deprecated upstream but fully functional — same "proportionate, not gold-plated" call already made for `SequentialAgent` elsewhere in this codebase.

### 7.9 Fortified track components — full status
| Component | Status |
|---|---|
| Agent Observability | ✅ built + verified today (§7.8) |
| Agent Registry | ❌ not started. Design: each agent self-registers metadata into Firestore on construction — cheap, same pattern as the Protect agent's own genericization. Planned Sat Aug 22. |
| Agent Runtime | ❌ not started as a *tracked* item — 7th component, previously missing from this table entirely (see caveat below). Ingest pipeline already qualifies as-is (`asyncio.create_task` + Docs-view status polling) — no new code needed there. Assessment-run pipeline doesn't yet: `coordinator.run_assessment()` is internally parallel (Pub/Sub fan-out to specialist workers) but externally blocking — the Reports view calls it synchronously and spinners for up to 900s. Plan: a `run_id`-returning endpoint + backgrounded coordinator + Reports-view polling, same pattern already proven for Docs. Planned Mon Aug 24 (`task_list.md`). |
| Agent Identity | ❌ not started. Per-agent IAM SA impersonation. Planned Sun Aug 23. |
| Memory Bank | ❌ not started as its own thing — arguably partially covered by `runs/{run_id}.snapshot` (doc_ids/answer_ids), built Aug 17; worth confirming if that counts before building more. Planned Sun Aug 23. |
| Agent Gateway | ❌ not started. Single authenticating/rate-limiting FastAPI ingress. Planned Mon Aug 24. |
| Model Armor / Cloud DLP | ❌ not started. PII scrub before every LLM call. Planned Sun Aug 23. |

**Caveat resolved Aug 20:** this list was Megha's own reading of the hackathon requirements from Aug 12, never independently re-verified against the actual official spec. Verified today against the live Devpost page — it was undercounting: the real spec names **7** components, not 6, grouped as Discovery & Lifecycle (Agent Registry), Core Execution & State (**Agent Runtime** + Memory Bank), Security & Governance (Agent Identity, Agent Gateway, Model Armor), and Telemetry (Agent Observability). Agent Runtime is now added to this table and to `task_list.md`'s Mon Aug 24 + Phase 3 Gate entries. Everything else on this page (model version, ADK, GCP infra choices, submission requirements) was already compliant.

---

## 8. Task list state — see `task_list.md` for full detail, this is just the headline

**Megha, done and verified today:** all 5 UI/UX backlog items, the navigate-then-run Chat/Reports fix, the retry/backoff reliability fix, LLM-as-Judge pipeline wiring, Agent Observability v1, and a full audit pass over `task_list.md` correcting several stale unchecked items (Northwind doc package delivery, Govern+Identify rubrics locked, two Phase 2 Gate lines).

**Megha, next up (today's remaining plan item):** confidence threshold logic — below 0.6, flag "insufficient evidence." Worth checking scope first: `aggregate_function` already does something like this at the *Function* level; this task may really be about the *Subcategory* level or report-surfacing, not new logic from scratch.

**Sakina, still owed (checked directly against `Ref Docs/NIST Rubrics.xlsx` as of today):**
- Detect, Respond, Recover CMMI rubrics — hard blocker, Megha cannot substitute. Respond was due Tue night, Recover due tonight (Thu); neither has landed as of this writing.
- Interview questions for every Function (Megha is running entirely on her own stand-in seed questions).
- Evidence taxonomy v1 (doc type → Category map) — still the single biggest untapped retrieval-precision lever, flagged since Aug 14.
- Golden test set v1 — **never delivered at any point.** This is the standing structural risk (see §3).
- Recommendation templates, executive summary templates — due later, not yet delivered.

---

## 9. Known gotchas (don't re-learn these)

- **`LlmAgent(model="gemini-...")` with a bare string = zero retries.** Use `csf_gateway/app/llm.py`'s `gemini_model()` at every construction site.
- **`st.rerun(scope="fragment")` cannot bootstrap its own polling loop.** Two layers: (1) plain `st.rerun()` inside a fragment still defaults to `scope="app"`. (2) Even `scope="fragment"` explicitly raises `StreamlitAPIException` unless the *current* execution is already a fragment-triggered rerun — a fragment's first/full-script run doesn't count. The only sanctioned way to auto-poll a fragment is its own `run_every=` parameter; "stop polling once done" needs a cheap pre-check *outside* the fragment to decide `run_every="2s"` vs. `None` for that render. Working example: `csf_ui/app.py`'s `_render_docs_status`.
- **Gemini 3.x is a thinking model** — unbounded thinking can burn 20k+ tokens and truncate JSON mid-object. Fixed via `thinking_config=ThinkingConfig(thinking_budget=8000)` + generous `max_output_tokens`.
- **Don't add length caps to LLM-produced Pydantic fields** (e.g. `EvidenceCitation.snippet`) — stochastically rejects valid output when Gemini's snippet runs long.
- **Adaptive `top_k = max(10, 2 × n_subs)`** per Category — small Categories get 10 chunks, GV.SC-sized ones get 20.
- **Qdrant client version-mismatch warning** — silenced with `check_compatibility=False` on every `QdrantClient()`.
- **Port 8090 startup race** — killing the old gateway and immediately starting a new one can race (old process hasn't released the socket yet), leaving a hung process that accepts TCP but never answers HTTP. `test_commands.md`'s startup sequence now has a `sleep 1` for this — don't remove it. If it happens anyway: `lsof -i :8090`, `kill -9 <pid>`.
- **Scripts nested under a subpackage** (e.g. `csf_specialists/scripts/`) can't `import csf_gateway` when run as `python path/to/script.py` — Python puts the script's own dir on `sys.path[0]`, not the repo root. Insert `Path(__file__).resolve().parents[N]` onto `sys.path` before local imports (see `preseed_govern.py` for the pattern).
- **`docx_parser.py`'s paragraph style can be `None`** for programmatically-generated `.docx` files — null-check before `.name`.
- **`.doc` (legacy binary Word) is accepted by upload validation but not actually parseable** — `python-docx` only reads `.docx`.
- **Streamlit: mutating a widget's `session_state` key after that widget has already rendered in the same script run raises `StreamlitAPIException`.** Must go through that widget's `on_click` callback instead. Applies to `active_view` (the `segmented_control` at the top of `csf_ui/app.py`) specifically, multiple times today.
- **`/chat/next` guards against duplicate calls** — returns the existing pending question instead of recomputing, since a duplicate call while a question is already pending could otherwise silently swap it out.
- **Seed questions vs. preseed answers are different mechanisms**, same word "seed," easy to conflate — see `pipeline_walkthrough.md` Stage 2's "Deep dive" section.
- **`csf_specialists/implementation_examples/*.yaml` (NIST's own examples) has always covered all 6 Functions** — don't confuse "examples exist for Function X" with "rubric exists for Function X." Only the rubric depends on Sakina's current delivery pace.

---

## 10. Test sessions available (already in Firestore + Qdrant)

- **`23a53272-6cd8-40b8-a363-f826eb76aa6d`** — best general-purpose test session. Real Northwind-authored docs + generic SANS docs, 21 Govern preseed Q&A loaded. Has multiple persisted runs including `phaseF` (6 Govern Categories) and at least one fresh run from today's live pipeline test (`444681e5-...`, Govern-only, includes real Judge output). **Most-used session this whole project — default to this one for adhoc testing.**
- **`f56a9039-877e-4a24-adc6-efafa22d104b`** — 2-Function (Govern+Identify) test session, run `f15764f4-e54d-4cb2-ab0d-42b0e5a3a473` has 9 persisted Category scores (6+3). Good for testing multi-Function rendering (used today to verify the radar redesign).
- **`b8bc86d2-10ce-4c43-ad3e-081ad9203d7f`** — Northwind Financial, generic SANS docs only, has an `adhoc` scores snapshot from early Govern testing.
- Others exist (`715a261b-...` Acme Corp, `58e14048-...` Beta Industries) for multi-org isolation testing — lower priority.
- List all sessions: `GET /sessions` on the running gateway, or the Streamlit sidebar.

---

## 11. Immediate next steps for a new session

1. Read this file in full, then `task_list.md`, then `docs/pipeline_walkthrough.md` if deeper pipeline understanding is needed.
2. Check `git status`/`git log` to see what's actually committed vs. still local — this file may be ahead of or behind the real repo state depending on when Megha last committed.
3. Check `Ref Docs/NIST Rubrics.xlsx`'s sheet list directly — the single fastest way to know if Sakina has delivered anything new (Detect/Respond/Recover) since this was written.
4. Confirm the local dev environment still boots cleanly (gateway + Streamlit, per `test_commands.md`) before assuming anything works.
5. Natural next pieces of work, roughly in order of value: (a) surface Judge's defensibility verdict in the report (pipeline wiring is done, report-reading isn't — §7.5), (b) the confidence-threshold task Megha was about to start, (c) whichever new Function rubric Sakina has delivered — build its agent the same way Protect was (§7.9's Registry note applies too, if that's picked up), (d) if genuinely stuck for something to do, the Fortified components in §7.9 are all real, all unstarted, and all reasonably well-scoped in `task_list.md`.
