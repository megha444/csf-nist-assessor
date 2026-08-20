# CSF Assessor Fleet — Session Handoff

Written Sat 2026-08-15 ~19:00 ET so a fresh Claude Code session can pick up cleanly.
Last updated Sun 2026-08-16 — Phases E, F, G all complete (see §2).

---

## 1. What this project is (1 paragraph)

**CSF Assessor Fleet** — a multi-agent system that runs a NIST CSF 2.0 cybersecurity maturity assessment. Value proposition: replaces an $80K, 10-week Big 4 engagement with a ~$0.50, ~15-minute automated run, while preserving evidence-cited findings, defensible scoring, and consultant judgment. Submitted to the **All Things Agentic Hackathon**, **Fortified Enterprise Fleet track**. Deadline **Mon 2026-08-31 12:00 PM ET target / 8:00 PM ET hard deadline** (10 days from now).

**Team:** Megha (sole tech lead — Python, cloud infra, ADK) + Sakina (KPMG cybersecurity practitioner — owns all domain content: rubrics, interview questions, Northwind docs, recommendation templates, exec summary tone). **Hard rule (feedback-division-of-labor):** Megha never invents domain content; Sakina never writes code.

**Repo:** `/Users/meghaagarwal/Desktop/Codes/Personal/csf-nist/` on branch `feat/ingest-pipeline`.

---

## 2. Where we are TODAY (Sat Aug 15, end of day)

**Active workstream:** Sat Aug 15 Govern agent build (see `docs/govern_build_tasks.md` for the full tracker). Currently:
- ✅ Phase A (schema extension, `SubcategoryScore` model, ADR-0007)
- ✅ Phase B (Sakina's Govern + Identify rubrics extracted to YAML, all 6 Functions' NIST examples extracted)
- ✅ Phase C (`csf_specialists/` package scaffold — `agent_base.py`, `agents/govern.py`, `prompts/score.txt`)
- ✅ Phase D (`score_category` full pipeline: retrieval → prompt → Gemini structured-output → optional Firestore persist)
- ✅ Subcategory-focused refactor pass — LLM now scores each Subcategory (not just Category); Category CMMI is deterministic `round(mean(subs))`. See ADR-0007 (revised).
- ✅ **Phase E** (sample Govern questions + Northwind preseed Q&A + loader script — see §5 below)
- ✅ **Phase F** (fresh session, real docs, persisted 6-Category run — see §5 below)
- ✅ **Phase G** (housekeeping — this update)

**Live end-to-end demonstration exists:** deployed `csf-gateway` on Cloud Run handles ingest, and the Govern specialist scores all 6 Categories × 31 Subcategories against a real Northwind session in ~90s for ~$0.06 total. Sample output:

| Category | Cat CMMI | conf | # subs | Sub CMMIs |
|---|---:|---:|---:|---|
| GV.OC | 1 | 0.85 | 5 | `[1, 2, 2, 1, 1]` |
| GV.RM | 1 | 0.80 | 7 | `[1, 1, 1, 2, 2, 1, 1]` |
| GV.RR | 2 | 0.80 | 4 | `[2, 2, 1, 1]` |
| GV.PO | 1 | 0.90 | 2 | `[1, 1]` |
| GV.OV | 1 | 0.90 | 3 | `[1, 1, 1]` |
| GV.SC | 1 | 0.90 | 10 | `[1×10]` |

Govern Function score = mean(31 Subs) = 1.19 → Tier 1 (Partial). Low scores are correct — the test session has only 3 generic SANS PDFs, no interview answers yet. Phase E fixes the "no answers" part.

**Phase E result (Aug 16):** preseeded 21 Northwind Govern Q&A into session `b8bc86d2-...` via `csf_specialists/scripts/preseed_govern.py`, then re-ran scoring adhoc (no `run_id`, so `runs/adhoc/scores/` above is still the pre-preseed snapshot — Phase F will do a persisted run). Confirms Phase E actually moves the needle:

| Category | Before (docs only) | After (docs + 21 preseed answers) |
|---|---|---|
| GV.SC | CMMI 1, `[1×10]`, all absent | **CMMI 2**, mixed `absent`/`partial`, `interview_evidence` cites the 4 GV.SC answer ids by name |
| GV.RM | CMMI 1 | **CMMI 3** — matches the locked Northwind target (Govern=Tier 3) |

`_fetch_answers` filters by Function only (not Category), so every Govern answer is visible to every Category's prompt — the LLM picks what's relevant per Category itself (see D3). Sample data intentionally calibrated: GV.OC/RM/RR/PO/OV answers read as CMMI ~3 (documented, org-wide processes), GV.SC answers read as CMMI ~2 with specific, named gaps (vendor tiering by dollar value not criticality, no due diligence under $250K, no post-onboarding reassessment) — a second demo-worthy finding alongside PR.AA-05.

---

## 3. Locked architecture (read these docs first, then any other)

**In priority order:**

1. **`docs/decisions.md`** — 7 ADRs. Most-referenced:
   - ADR-0001: Qdrant Cloud on GCP us-east4 (not Vertex AI Vector Search)
   - ADR-0002: Score at Category level (~22 rubrics, not ~106)
   - ADR-0003: Gemini 2.5 Flash multimodal for PDF ingest (one call replaces pypdf/pdfplumber/OCR stack)
   - ADR-0004: 3 Cloud Run services + per-agent SA impersonation
   - ADR-0005: `gemini-3.5-flash` + `gemini-3.7-flash` on `global` endpoint (Gemini 3.x has no Pro tier)
   - ADR-0006: Multi-tenant model — org_id shipped, full refactor deferred (Option 1)
   - **ADR-0007 (revised): Per-Subcategory CMMI scoring, Category = round(mean); recommendations at Subcategory keyed by (subcategory_id, level_transition), incremental text N→N+1 or N+2 only**
2. **`docs/architecture.md`** — 6 Mermaid diagrams (system context, deployment topology, user journey, data flow, Fortified components, environments)
3. **`docs/lld.md`** — Firestore schema, Qdrant config, REST endpoints, Pydantic models, agent contract, algorithms with code sketches, sequence diagrams, env vars, Sakina deliverable formats, testing map
4. **`docs/csf_assessor_hackathon_plan.md`** — canonical 19-day plan (§0 has the Aug 13 Category-scope amendment)
5. **`docs/govern_build_tasks.md`** — today's active tracker (Phases A-G)
6. **`docs/ingest_tasks.md`** — completed ingest tracker for reference (Phases A-H all ✅)
7. **`task_list.md`** — daily strategic checkbox tracker

**Ref materials from Sakina** (gitignored, in `Ref Docs/`):
- `NIST Rubrics.xlsx` — 3 sheets so far (Govern, Identify, Protect — Protect added Aug 19); 6 + 3 + 5 Categories with 5-level CMMI text
- `CSF 2.0-Implementation_Examples.xlsx` — NIST-provided per-Subcategory examples, all 6 Functions

---

## 4. Repo file map (the ~20 files that matter)

```
csf-nist/
├── task_list.md                    strategic daily tracker (see Sat Aug 15)
├── docs/
│   ├── HANDOFF.md                  this file
│   ├── decisions.md                7 ADRs
│   ├── architecture.md             Mermaid diagrams
│   ├── lld.md                      schemas + contracts
│   ├── csf_assessor_hackathon_plan.md  canonical plan
│   ├── govern_build_tasks.md       today's tracker (Phases A-G)
│   └── ingest_tasks.md             completed ingest tracker
├── pyproject.toml + poetry.lock    deps (google-adk, fastapi, qdrant-client, google-genai, python-docx, etc.)
├── .env                            gitignored — Qdrant URL/key, GCP project, model IDs
├── .env.example
├── Dockerfile + .dockerignore + .gcloudignore   Cloud Run build config
├── infra/
│   ├── setup.sh                    GCP bootstrap (buckets, Firestore, Pub/Sub, etc.)
│   ├── qdrant_setup.py             creates csf_chunks collection + payload indexes
│   ├── build_rubric_yaml.py        --function <name>|all — extracts Sakina's xlsx to YAML
│   └── deploy_gateway.sh           gcloud run deploy for csf-gateway
├── csf_gateway/                    THE DEPLOYED SERVICE (Cloud Run)
│   └── app/
│       ├── main.py                 FastAPI: /health, /sessions/*, /documents/*
│       ├── config.py               Pydantic settings, loads .env
│       ├── csf_catalog.py          22 CSF Categories with keywords
│       ├── doctype_taxonomy.py     15 hardcoded doc types + Function map
│       ├── schema.py               all Pydantic DTOs (ScoreOutput, SubcategoryScore, etc.)
│       ├── sessions.py             session CRUD + list + FastAPI router
│       ├── documents.py            batch upload + status polling
│       ├── chat.py                 interview chat — /next (AI auto-picks Function), /answer, /finish, /history
│       ├── qna.py                  Aug 19 — freeform Q&A document upload+extraction (POST /sessions/{sid}/qna)
│       └── ingest/                 async pipeline (10 modules)
│           ├── storage.py          GCS raw upload
│           ├── dedupe.py           SHA256 dedupe per session
│           ├── pdf_parser.py       Gemini 3.5 Flash multimodal → markdown
│           ├── docx_parser.py      python-docx → markdown
│           ├── xlsx_parser.py      openpyxl → markdown (Aug 18; .pptx not yet built)
│           ├── chunker.py          section-aware + page markers
│           ├── tagger.py           keyword → candidate_categories (word-boundary regex)
│           ├── embedder.py         text-embedding-004 batched
│           ├── vector_store.py     Qdrant wrapper — search_session, search_org, delete_*
│           ├── firestore_writer.py document + chunks + status transitions
│           └── orchestrator.py     glues it all together (called via asyncio.create_task)
├── csf_specialists/                specialist agents (not yet deployed as its own service)
│   ├── __init__.py
│   ├── loaders.py                  load_rubric + load_implementation_examples (cached)
│   ├── agent_base.py               SpecialistAgent class (retrieval, prompt, Gemini, persist)
│   ├── aggregate.py                cmmi_to_tier + aggregate_function (Category-weighted, lld.md §8.2) + persist_tier
│   ├── agents/govern.py            govern_agent singleton
│   ├── qna_extractor.py            Aug 19 — ADK structured-output extraction of Q&A pairs from a completed questionnaire, classified against the full 6-Function catalog
│   ├── prompts/
│   │   ├── score.txt               2.4KB scoring prompt template
│   │   └── qna_extract.txt         Aug 19 — QnA extraction prompt (catalog block + document text)
│   ├── rubrics/
│   │   ├── govern.yaml             Sakina, all 6 Categories, 5 levels each
│   │   └── identify.yaml           Sakina, all 3 Categories
│   ├── sample_data/                Megha-authored stand-ins (Phase E), Sakina refines later
│   │   ├── govern_questions.json   8 sample interview questions, 4 priority Categories
│   │   └── northwind_preseed_govern.json  21 Northwind Q&A, all 6 Categories
│   ├── templates/
│   │   └── report.html.j2          Jinja2 template for report v2 (Aug 18) — radar + per-Category detail
│   ├── scripts/
│   │   ├── preseed_govern.py       loads a PreseedRecord JSON file into sessions/{sid}/answers/
│   │   ├── export_json.py          report v1 — JSON, all Functions in a run
│   │   ├── export_excel.py         client-facing Excel, one row per Subcategory
│   │   └── export_html.py          report v2 (Aug 18) — HTML + embedded Plotly radar, built on export_json.build_report
│   └── implementation_examples/    NIST Ex1/Ex2/... per Subcategory, all 6 Functions
│       ├── govern.yaml   (31 subs, 119 examples)
│       ├── identify.yaml (21, 74)
│       ├── protect.yaml  (22, 77)
│       ├── detect.yaml   (11, 37)
│       ├── respond.yaml  (13, 38)
│       └── recover.yaml  (8, 18)
├── csf_ui/                          Streamlit app v2 (Aug 19, redesigned from Aug 18's v1) — `poetry run streamlit run csf_ui/app.py`, port 8501
│   └── app.py                       multi-session sidebar; per-session Docs/Chat/Reports views; chat-native AI-driven interview; tabbed native-Plotly reports
├── hello_agent/                    still around, superseded by csf-gateway
├── SANS-Security-Policy-Templates-main/  ingest test corpus
└── Ref Docs/                       Sakina's source xlsx (gitignored)
```

---

## 5. Phase E + F — DONE (sample data authoring + end-to-end test)

**Goal:** author ~8 sample Govern interview questions + ~20 Northwind pre-seed Q&A so `_fetch_answers` returns real content. Currently sessions have no answers loaded, so scoring relies solely on docs and skews low.

**Delivered (per `docs/govern_build_tasks.md` Phase E):**
- [x] E1. `csf_specialists/sample_data/govern_questions.json` — 8 questions, 2 each on GV.OC/GV.RM/GV.RR/GV.SC (the 4 demo-priority Categories). Shape: `{id, question, function, category_hint, importance, expected_answer_type}` — a lighter-weight standalone shape, not `PreseedRecord` (no `answer` yet; this is the unanswered bank).
- [x] E2. `csf_specialists/sample_data/northwind_preseed_govern.json` — 21 Q&A pairs (3-4 per Category, all 6 covered), validated against the real `PreseedRecord` model. Category_hints checked against actual Subcategory ids in `implementation_examples/govern.yaml` — no typos. Calibrated to the locked Northwind profile: GV.OC/RM/RR/PO/OV answers read CMMI ~3, GV.SC answers read CMMI ~2 with named gaps (dollar-value vendor tiering instead of criticality, no due diligence under $250K, no post-onboarding reassessment).
- [x] E3. `csf_specialists/scripts/preseed_govern.py` — validates + batch-writes a `PreseedRecord` JSON file into a session's `answers/` subcollection, sets `preseed_loaded=True`. Idempotent (stable ids). `--dry-run` flag validates without touching Firestore.
- [x] Verified live against `b8bc86d2-...` — see the Phase E result table in §2 above. GV.SC moved CMMI 1→2 with real cited evidence; GV.RM landed at CMMI 3, matching the target profile.

**Bounded by:** Sakina is behind schedule and hasn't delivered interview questions OR Northwind docs. Sample data authored by Megha is a temporary stand-in per the "sample data wherever needed" agreement. Sakina refines/replaces later.

**Phase F result (Aug 16):** fresh session `23a53272-6cd8-40b8-a363-f826eb76aa6d` (target_org `"Test1"` — not renamed, cosmetic only), 3 real docs uploaded (`Information_Security_Policy.docx`, `acquisition_assessment_policy.pdf`, `risk_assessment_policy.pdf`), preseed loaded, all 6 Categories scored with a persisted `run_id='phaseF'`:

| Category | CMMI | conf | subs | non-present | evidence citations | interview evidence |
|---|---:|---:|---:|---:|---:|---:|
| GV.OC | 3 | 0.90 | 5 | 3 | 3 | 5 |
| GV.RM | 3 | 0.90 | 7 | 3 | 3 | 10 |
| GV.RR | 4 | 0.90 | 4 | 2 | 3 | 4 |
| GV.PO | 4 | 0.90 | 2 | 0 | 2 | 3 |
| GV.OV | 4 | 0.90 | 3 | 1 | 2 | 5 |
| GV.SC | 2 | 0.90 | 10 | 10 | 3 | 4 |

**Aggregation check:** Category-weighted mean (`lld.md §8.2`) = 3.333 → **Tier 3**, matching the locked Northwind Govern target exactly. Subcategory-weighted mean (31 Subs pooled, the Aug 15 ad hoc method) = 2.613 → **Tier 2**. **The two methods disagree by a full Tier on real data** — see §8 gotchas, needs a decision before real aggregation code (Aug 18-19).

One real bug surfaced and got fixed along the way: `docx_parser.py` crashed on a `.docx` with unstyled paragraphs (`para.style is None`) — see §8. And one content discovery worth knowing about: the uploaded `.docx` turned out to be real, already-written Northwind content (not a SANS template) that describes Northwind as UK-regulated (PRA/FCA), conflicting with the locked persona's US regs — see §8 and `docs/govern_build_tasks.md`'s Sakina deliverable table.

Full detail (F1-F7, discovered follow-ups) in `docs/govern_build_tasks.md`.

---

## 6. Deployed system

- **Cloud Run URL:** `https://csf-gateway-jdogd2dq2q-uc.a.run.app`
- **Health check:** `curl -s $URL/health | python3 -m json.tool` — currently returns `{"app":"ok", "qdrant":"ok (N points)", "status":"healthy"}`
- **Swagger UI:** `$URL/docs` — session create, doc upload with file picker (Swagger schema fix in place so multi-file works)
- **GCP project:** `csf-assessor-hackathon`
- **Firestore:** native mode, project default database. Sessions live at `sessions/{session_id}`; scores at `sessions/{sid}/runs/{run_id}/scores/{category_id}`
- **Qdrant Cloud cluster** (managed by Qdrant Solutions on GCP us-east4, url + api key in `.env`) — collection `csf_chunks`, ~200+ points across all test sessions
- **Vertex models used:** `gemini-3.5-flash` (specialist scoring), `gemini-3.7-flash` (planned for Judge — 3.x has no Pro tier), `text-embedding-004` (embeddings)
- **Region gotcha:** Vertex AI calls use `GOOGLE_CLOUD_LOCATION=global` because Gemini 3.x isn't served on regional endpoints for this project. GCS/Firestore stay us-central1 (region baked into resource names).
- **Deployed cost so far:** trivial. Cloud Run scales to zero when idle.

---

## 7. Task list state (Sat Aug 15 EOD)

### Megha ✅ done today
- Extended `ScoreOutput` schema with `SubcategoryScore` (ADR-0007 code)
- Extracted Sakina's Govern + Identify rubrics + all 6 Functions' NIST examples to YAML
- Built `csf_specialists/agent_base.SpecialistAgent` + `agents/govern.py` + prompt template
- Wired `score_category` end-to-end: retrieval → prompt → Gemini structured-output → optional Firestore persist
- Subcategory-focused refactor: LLM scores per-Subcategory, Category = round(mean)
- Adaptive `top_k = max(10, 2 × n_subs)`
- Removed cosmetic `snippet max_length=300` cap that was flakily breaking parses
- Phase E: authored `sample_data/govern_questions.json` (8 questions) + `sample_data/northwind_preseed_govern.json` (21 Q&A) + `scripts/preseed_govern.py` loader; verified live — GV.SC CMMI 1→2, GV.RM CMMI 3
- Phase F: fresh session, 3 real docs uploaded + scored end-to-end with a persisted `run_id`; fixed a real `docx_parser.py` bug found along the way (`para.style` can be `None`)
- Phase G: this handoff update — logged the docx bug, the `.doc`-format gap, the `session.doc_ids` gap, the aggregation-formula discrepancy (Category- vs Subcategory-weighted, disagree by a full Tier on real data), and the PRA/FCA content conflict

- Built `csf_specialists/aggregate.py`: Category-weighted `aggregate_function` (per `lld.md §8.2`) is now real code, not just a doc sketch. Verified against `sessions/23a53272-.../runs/phaseF`: Tier 3, matches the locked Northwind target. Persists to `runs/{run_id}/tiers/{function}`.
- Extended `SubcategoryScore` with `observations`/`gap`/`recommendation` (was one blended `notes` field) + built `csf_specialists/scripts/export_excel.py` — client-facing Excel, one row per Subcategory (Function/Category/Subcategory/Notes-Observations/GapsFindings/Recommendations/Scores).
- **Retrofitted the whole pipeline onto real Google ADK** (was calling `google.genai` directly everywhere — hackathon requires ADK, not just Vertex AI): `csf_specialists/agent_base.py`'s scoring call now runs through an ADK `LlmAgent`+`Runner`; built `csf_coordinator/` (new package) — real Pub/Sub coordinator (`SequentialAgent` composing `DispatchStep`/`CollectResultsStep`/`AggregateStep`) dispatching through the 7 GCP topics `infra/setup.sh` already provisioned, plus `csf_specialists/worker.py` as the pull-side consumer. Verified end-to-end against real GCP infra, not mocked.
- Built the **interview agent**: `csf_coordinator/interview.py`, one ADK LLM decision per turn — mixes unused seed questions with NIST-grounded generated ones (explains `Provenance.live_chat_generated`, which had sat unused in the schema all day), `POST /sessions/{sid}/chat/{next,answer,finish}` in `csf_gateway/app/chat.py`. This also completed "Level 1 adaptive logic" and "session persistence" — all 4 of Sun Aug 16's `[M]` tasks are now done (see `task_list.md`).
- **Aug 17:** Identify agent genericized off the Govern template (`csf_specialists/agents/identify.py`), verified live on real doc evidence — see `task_list.md`'s Mon Aug 17 entry.
- **Aug 18:** `csf_gateway/app/ingest/xlsx_parser.py` — openpyxl → markdown, one heading + table per non-empty sheet, same contract as `docx_parser.py`. Wired into `orchestrator.py` (new `.xlsx` branch) and `documents.py` (extension/content-type allowlist). Verified end-to-end against 3 of the teammate's real files (`Vendor_List.xlsx`, `Enterprise_Risk_Register_Extract.xlsx`, `Regulatory_Requirements_Register.xlsx`): all reached `ingest_status=ready`, and a live `GV.SC` scoring run against the fresh session cited all 3 as evidence (CMMI=2, conf=0.85, `no_doc_evidence=False`). `Regulatory_Requirements_Register.xlsx` turned out to be the strongest single piece of evidence for the Aug 18 UK-jurisdiction correction — it has a section literally titled "Regimes Assessed and Confirmed Not Applicable" explicitly ruling out GLBA/NYDFS/SOX/PCI-DSS with rationale. 14 of the 16 real Northwind files are now ingestable; **`.pptx` support (`Internal_Audit_Report`, `Risk_Appetite_Statement`) explicitly deferred as future scope**, not built.
- **Aug 18 (later):** Report generator v2 — `csf_specialists/scripts/export_html.py` + `csf_specialists/templates/report.html.j2` (Jinja2, added `jinja2`/`plotly` to `pyproject.toml`). Renders one HTML file per run: exec-style header, **two Plotly radars** (a Tier radar — one spoke per Function, r=Tier 1-4, the board-level view the plan's §2/§3/§10 actually call for — plus a Category radar — one spoke per Category grouped by Function, r=CMMI 1-5, the practitioner drill-down), per-Function Tier cards, and per-Category detail (CMMI pill, confidence, `no_doc_evidence` flag, reasoning, full Subcategory table, evidence citations, interview evidence ids). Built as a rendering layer on `export_json.build_report` — same Firestore read v1 already does, no second query path. Verified against real persisted runs (1-Function `23a53272-.../phaseF` and 2-Function `f56a9039-.../f15764f4-...`) via headless-Chrome screenshots. Two real bugs caught and fixed: the Tier badge was interpolating the raw Firestore tier dict instead of its `tier` int field, and the first pass had collapsed both radars into one Category-only chart (caught during an Aug 18 plan-vs-build realign check, split same day).
- **Aug 18 (evening):** Streamlit app v1 — `csf_ui/app.py` (added `streamlit` to `pyproject.toml`; this pulled in a `starlette` downgrade for a dependency conflict, confirmed the gateway still imports/runs fine after). Upload → interview → run assessment → embedded static report, in one linear page. Session/document/chat go over HTTP to the already-running gateway (their async background work is tied to the gateway's own event loop); run-assessment and report generation call `csf_coordinator.run_assessment` / `csf_specialists.scripts.export_html` directly as library functions, same pattern the export scripts already use. "Run assessment" spawns one one-shot `worker.py --function <fn>` subprocess per live agent right before calling `run_assessment` — otherwise nothing would consume its Pub/Sub dispatch and the button would hang for up to 900s (see `csf_coordinator/steps.py`). Verified with a full Playwright-driven browser run covering every step, including a real live assessment run (both workers actually dispatched/scored/published) and report generation. Two real bugs found and fixed during testing: the upload call's multipart `data` was shaped as a list of tuples, which httpx can't encode alongside `files` (fixed to `{"doc_types": [...]}`, confirmed against httpx's own encoder); and no loading feedback during `/chat/next`'s LLM call, which read as broken under fast interaction (added a spinner). Native `st.plotly_chart` charts and a fully live-integrated report view (vs. today's embedded static HTML) are the already-logged Aug 21-22 follow-up in `task_list.md`.
- **Aug 19:** Streamlit v1 → v2, user-driven redesign after using v1 live (see `task_list.md`'s Wed Aug 19 entry for the full breakdown). Five changes: sessions persist and are browsable (`GET /sessions`, sidebar list); the interview is a real chat (`st.chat_message`/`st.chat_input`, fully auto-continuing); the AI — never the user — picks which Function a question is about (`interview.decide_next_question_auto`, new cross-Function `need_score` comparison layered on the existing per-Function formula, `/chat/next`'s `function` param now optional); a session is Docs/Chat/Reports as its own view (`st.segmented_control`, chosen specifically because native `st.tabs` can't be set programmatically and the Docs→Chat "Next" flow needs that); and Reports is now Overview + one native tab per scored Function (reusing `export_html.py`'s pure-data functions directly, no Jinja), with both HTML and a new Excel download. Also new: freeform Q&A document upload (`POST /sessions/{sid}/qna` → `qna_extractor.py`, one ADK call classifies an arbitrary completed questionnaire against all 6 Functions) — verified against a real Northwind blank template (correctly extracted zero, no hallucination) and a synthetic completed one (3/3 correctly classified, including landing on the PR.AA identity/access area). One Streamlit platform gotcha hit: you cannot mutate a widget's `session_state` key after that widget has already rendered in the same script run (`StreamlitAPIException`) — any state change that needs to affect a widget defined earlier in the script must go through that widget's `on_click` callback instead of a plain post-button assignment. One backend robustness gap found via real testing, not hypothetical: `/chat/next` had no guard against a duplicate call while a question was already pending — harmless this time (the LLM's decision was deterministic given unchanged coverage, so it just re-returned the same question) but a latent risk if it ever weren't — fixed by returning the existing pending question instead of recomputing.

- **Aug 19 (later):** Protect specialist agent plugged in the moment Sakina's Protect rubric landed — `csf_specialists/agents/protect.py`, identical 3-line config-wrapper pattern to Govern/Identify, registered in `agents/__init__.py`'s `AGENTS` dict. Confirms the base class genericized on Aug 17 really does need zero Function-specific code: only a rubric + examples YAML pair and a 3-line wrapper file. Verified live against `23a53272-...`: all 5 Protect Categories score cleanly, 22 total Subcategory scores (6+2+4+6+4, matches the rubric's own shape exactly), honest CMMI=1 across the board since that session has no Protect-specific document evidence — same "don't fabricate, just say what's there" behavior already validated for Identify. This was Wed Aug 19's "templatize Govern agent config-driven" plan item — turned out to already be true architecturally; this was the first real proof of it. **Detect/Respond/Recover agents are now the same 10-minute job the moment their rubrics land** — no longer a Sat Aug 22 unknown, just waiting on Sakina.

- **Aug 19 (later still):** LLM-as-Judge — `csf_specialists/judge.py` + `csf_specialists/prompts/judge.txt`. Same ADK pattern as `agent_base.py`/`aggregate.py`: reads one persisted `ScoreOutput` + the Category's own rubric text, and asks `gemini-3.7-flash` (the "Pro slot," ADR-0005) to critique — NOT re-score — on evidence-to-level match, citation specificity, confidence calibration, and internal consistency between the Category-level reasoning and its own Subcategory entries. Deliberately doesn't re-run retrieval; works from what the specialist already wrote, the way a human QA reviewer would. Persists to `sessions/{sid}/runs/{rid}/judge/{category_id}`, matching the Firestore layout already sketched in `docs/lld.md` §10's sequence diagram. `JudgeResult`/`Defensibility` schema and `gemini_pro_model` config both already existed (shipped Day 1) but were unused until now. **Verified live** against all 6 real persisted Govern Categories (`23a53272-.../phaseF`): 5 came back `high`, 1 `medium` (GV.RR) — and it's a real catch, not a false positive: GV.RR-01 was scored CMMI 4 even though the specialist's own gap text admits coverage gaps aren't actively tracked/closed against target dates, which the rubric itself defines as the Level 4 bar; it also caught two Subcategories citing `[7]`/`[9]` that never made it into the Category-level citation list. **Not yet wired into the automated pipeline** — `csf_coordinator/coordinator.py`'s `SequentialAgent` doesn't call it yet (the lld.md sequence diagram shows it running in parallel with `AggregateStep`, but no `JudgeStep` exists); today's verification was a direct standalone call, same as how `aggregate.py` was built and proven before its own `AggregateStep` wiring landed. Also not yet surfaced in either report (`export_html.py`/`export_json.py` don't read the `judge/` subcollection at all yet).

- **Aug 20:** Judge wired into the automated pipeline — new `JudgeStep` in `csf_coordinator/steps.py` (mirrors `AggregateStep`'s shape exactly: reads `session_id`/`run_id`/`function`, calls `judge_run`), appended after the `AggregateStep` loop in `csf_coordinator/coordinator.py`'s `run_assessment` composition. Runs sequentially after Aggregate rather than in parallel (per `docs/lld.md`'s original `par aggregate + judge` sketch) — deliberate simplification, documented in `coordinator.py`'s own docstring: ADK's `ParallelAgent` isn't used anywhere else in this codebase, and the real time cost is Judge's LLM calls either way, not which order the two run in. **Verified with a full real end-to-end run** (not just a standalone call): fresh `run_id`, real worker subprocess consuming a real Pub/Sub dispatch, all 6 Govern Categories scored → aggregated (Tier 3) → judged automatically, all 6 `judge/{category_id}` docs confirmed persisted in Firestore with no manual `judge_run()` call. One real cost worth knowing: Judge roughly doubles LLM calls per Function (12 instead of 6 for Govern), so "Run assessment" now takes noticeably longer — flagged directly in `coordinator.py`, not a silent regression.

### Megha ⏳ pending (in priority order)
1. Tuning pass on the Interview Director's prompt (`csf_coordinator/prompts/next_question.txt`) — doesn't reliably prefer high-importance unused seed questions before generating new ones; TODO left in the file
2. Surface Judge's `defensibility`/`judge_notes` in the report — pipeline wiring is done (see Aug 20 entry above), but neither `export_html.py` nor `export_json.py` reads the `judge/` subcollection yet, so today's defensibility verdicts are persisted but invisible to anyone reading a report.
3. Deploy `csf_specialists`/`csf_coordinator` as real Cloud Run services — Aug 22 in the plan (today's Pub/Sub coordinator + interview agent are both still local-process stubs — real topics, but no deployed push-triggered services yet)
4. `.pptx` ingest support (`pptx_parser.py`) — future scope, not scheduled. The 2 remaining files (`Internal_Audit_Report`, `Risk_Appetite_Statement`) likely lean on slide layout/charts more than the xlsx registers did; text-frame extraction via `python-pptx` is the starting point, with Gemini-vision-on-slide-image (same pattern as `pdf_parser.py`) as a fallback if extraction reads thin.

### Megha ⏳ backlog — UI/UX fixes found via live testing (Aug 19, not yet prioritized against the list above)

1. **No company-name input on session creation.** `csf_ui/app.py:134-137`'s "+ New session" button always POSTs `{}` to `/sessions`, so `create_session()` (`csf_gateway/app/sessions.py:47-71`) falls through to its own `target_org="Northwind Financial"` default every time. The backend already accepts `target_org`/`org_id` (`CreateSessionRequest`, `csf_gateway/app/schema.py:118-125`) — this is UI-only: add a text input before the POST.

2. **No auto-polling on Docs upload.** `csf_ui/app.py:165-210` fetches the bulk document list once per script run; the "Refresh status" button (`app.py:200`) is an inert no-op (relies on Streamlit's default rerun-on-click, no `st.rerun()`/loop/spinner). The gateway already has `GET /sessions/{sid}/documents/{doc_id}/status` (`csf_gateway/app/documents.py:205-220`, `_PROGRESS_PCT` map at lines 46-54) explicitly built "cheap enough for 1-2s polling" — the UI never calls it. Fix: poll that endpoint per in-flight doc and render `st.progress(progress_pct)`.

3. **No "run assessment" trigger on the Chat view.** It only exists in Reports (`csf_ui/app.py:278-285`), gated on `if not run_id`, and spawns one `worker.py --function <fn>` subprocess per live agent (lines 84-109) before calling `csf_coordinator.run_assessment` — necessary so something consumes the Pub/Sub dispatch (same reason logged Aug 18). Chat view (lines 219-268) has no trigger. Fix: add a button in Chat that calls the same `_run_assessment_sync(sid)` helper, then switch the segmented control to Reports.

4. **Overview radar scope is wrong.** `_tier_radar_figure` (`export_html.py:65-83`, one spoke per Function, Tier 1-4) belongs on Overview alone. `_category_radar_figure` (`export_html.py:86-107`) currently loops over *every* scored Function and overlays all of them on one shared polar chart — it's not per-Function. Both are placed together on the Overview tab (`csf_ui/app.py:315-316`); the per-Function tabs (lines 318-347) show only tables, no chart. Fix: keep only the Tier radar on Overview; add a Function-scoped category radar (filter the existing loop, or a new `_category_radar_figure_single(report, function)`) and render it inside each per-Function tab instead. Related edge case in the same function: when a Function has only 1 scored Category, `theta = ordered_ids + ordered_ids[:1]` (lines 94-96) produces two identical-angle points, which Plotly renders as a degenerate/empty-looking circle instead of a polygon (needs ≥3 distinct angles) — worth guarding regardless of the scope fix.

5. **Exported HTML report — same scope issue, plus a real layout bug.** `report.html.j2`'s `.radar-block` (lines 54-60) is `flex: 1 1 360px` with no `max-width`/`overflow` constraint; neither `_tier_radar_figure`/`_category_radar_figure` nor the `to_html()` calls (`export_html.py:154-155`) set `autosize`/`responsive`, so each Plotly div renders at its ~700px default width regardless of the 360px flex basis and bleeds into the sibling column. Fix: pass `config={"responsive": True}` (or `fig.update_layout(autosize=True)`) and add `max-width: 100%; min-width: 0` to `.radar-block`. Apply the same Overview/per-Function split from item 4 here too, so the exported report structurally matches the redesigned Streamlit Reports view.

---

### Sakina ⏳ pending (she's been catching up on rubrics + docs only; running 3-5 days behind the plan's own dates)
- ~~URGENT — confirm Northwind's actual regulatory jurisdiction~~ — **RESOLVED Aug 18: UK.** The teammate's full 16-document Northwind package (delivered Aug 15-17 into `02. Documents/`) consistently and deliberately describes Northwind as UK dual-regulated (PRA/FCA), including a filed SM&CR Statement of Responsibilities for a named CISO. The locked persona (memory + `docs/csf_assessor_hackathon_plan.md §5`) has been corrected to match. Old US-regs assumption (GLBA/NYDFS 500/PCI-DSS/SOX) is wrong, superseded.
- ~~Northwind Financial doc package~~ — **RESOLVED.** Delivered Aug 15-17, 16 real documents in `02. Documents/`. (This line previously and incorrectly still listed it as owed — stale, fixed Aug 18.)
- **Deprioritized Aug 18 (Megha's decision, not chasing further for now):** interview questions (all 6 Functions), evidence taxonomy v1 (doc_type → Category map), golden test set v1 (Northwind + expert CMMI scores). All three are genuinely still owed and genuinely valuable (evidence taxonomy in particular remains the biggest untapped retrieval-precision lever), but with Sakina running behind, Megha is proceeding independently using the existing Megha-authored stand-ins (`sample_data/govern_questions.json`, `northwind_preseed_govern.json`) rather than blocking on them. These stand-ins double as an interim internal testing/regression harness (structural checks — schema validity, retrieval sanity, run-to-run consistency — not true CMMI-accuracy validation, which still needs Sakina's expert judgment) until her real deliverables land and get merged in. This does **not** extend to CMMI rubrics — those stay a hard blocking dependency Megha cannot substitute for (division-of-labor hard rule: she never invents domain content).
- ~~Protect CMMI rubric~~ — **delivered Aug 19** (`Ref Docs/NIST Rubrics.xlsx` sheet Protect, 5 Categories, extracted to `csf_specialists/rubrics/protect.yaml` + `implementation_examples/protect.yaml`). Detect / Respond / Recover CMMI rubrics — still genuinely blocking; Sat Aug 22's agent deployments need these to exist first.
- Recommendation templates keyed by (subcategory_id, transition) — due Wed Aug 19
- Executive summary templates (24 = 4 Tiers × 6 Functions) — due Fri Aug 21
- ~~Northwind reg confirmation~~ — **RESOLVED Aug 18** (UK PRA/FCA, not the old US GLBA/NYDFS/PCI/SOX guess — see §7 Megha pending list)

---

## 8. Known gotchas from today (don't re-learn them)

- **`LlmAgent(model="gemini-...")` — passing a bare model-name string means ZERO retries.** ADK resolves a string via `LLMRegistry.new_llm()` into a plain `Gemini(model=name)` with `retry_options=None`, so a single transient `429 RESOURCE_EXHAUSTED` kills the entire call immediately. Fixed Aug 20 in `csf_gateway/app/llm.py`'s `gemini_model()` — wraps the name in `Gemini(model=name, retry_options=types.HttpRetryOptions(attempts=5, ...))`, ADK's own built-in retry, not custom code. Every `LlmAgent(model=...)` construction site in the codebase must go through this helper, not a bare string. Root cause discovered Aug 20 when Protect joining `AGENTS` (3 concurrent workers instead of 2) plus Judge doubling per-Function call count landed the same week and tripped the project's Vertex AI quota for the first time.
- **Gemini 3.x is a thinking model** — unbounded thinking can burn 20k+ tokens and truncate JSON mid-object. Fixed with `thinking_config=ThinkingConfig(thinking_budget=8000)` + `max_output_tokens=24000` in `agent_base.py`. If future scoring flakes with `response.parsed=None`, check the actual `usage.thoughts_token_count` in the error message.
- **`EvidenceCitation.snippet` had `max_length=300`** — stochastically rejected valid LLM output when Gemini chose a longer snippet. Removed. Don't add length caps to LLM-produced fields.
- **Adaptive `top_k = max(10, 2 × n_subs)`** per Category. GV.SC gets 20 chunks; small Categories get 10. Configured in `agent_base.py:score_category`.
- **Qdrant client version-mismatch warning** is silenced with `check_compatibility=False` on every `QdrantClient()` instantiation.
- **Uvicorn on port 8080 is often occupied** on Megha's dev machine → we use port 8090 for local runs. Always `lsof -ti:8090 | xargs kill 2>/dev/null` before booting.
- **Multi-file upload from Swagger UI** sends comma-joined `doc_types` (`"A,B,C"` as one field) instead of separate entries. The `POST /documents` route handles both forms.
- **Legacy Qdrant chunks (from pre-org_id runs) have `org_id=None`** — invisible to `search_org()` (correct behavior). Purge with `IsNullCondition` filter if desired.
- **Sakina's rubric uses "Organisational" (British)** — preserved as-is; not a bug.
- **`importance` per Category defaulted to 2** — Sakina should mark high-priority Categories as 3 (e.g. `GV.SC` for supply chain). Non-blocking.
- **Scripts nested under `csf_specialists/scripts/` (two dirs deep) can't `import csf_gateway` when invoked as `python path/to/script.py`** — Python puts the script's own directory on `sys.path[0]`, not the repo root, so the top-level package import fails. `preseed_govern.py` fixes this by inserting `Path(__file__).resolve().parents[2]` onto `sys.path` before the local imports. Copy that pattern for any future one-off script living under a subpackage.
- **`docx_parser.py`'s `_paragraph_to_md` assumed `para.style` is never `None`** — it can be, for paragraphs without a named Word style (common in programmatically-generated/externally-exported `.docx`). Crashed with `AttributeError: 'NoneType' object has no attribute 'name'` on a real file where 10/27 paragraphs had `style=None`. Fixed: null-check `para.style` itself, not just `.style.name`.
- **`.doc` (legacy binary Word) is accepted by upload validation but not actually parseable** — `python-docx` only reads modern `.docx`. Not fixed (would need a conversion step like LibreOffice headless). If Sakina ever sends a true old-format `.doc`, tell her to re-save as `.docx` or `.pdf` instead.
- **`sessions/{sid}.doc_ids` is never populated by `documents.py` on upload** — confirmed empty on a session with 3 real documents in the `documents` subcollection. Nothing reads it today, but `lld.md`'s `runs/{run_id}.snapshot.doc_ids` provenance field implies something eventually will.
- **RESOLVED — Function-aggregation formula.** `lld.md §8.2`'s Category-weighted `aggregate_function` is now real code: `csf_specialists/aggregate.py`. Chosen over the Aug 15 ad hoc Subcategory-weighted "1.19" figure because it matches the original architectural intent (ADR-0002: Category is the scoring/reporting unit; Judge + report consume `ScoreOutput` at Category granularity), not because of which number it produces. Verified against `sessions/23a53272-.../runs/phaseF`: avg_cmmi=3.333 → Tier 3, persisted to `runs/phaseF/tiers/govern`.
- **TODO — Interview Director doesn't reliably prefer high-importance unused seed questions before generating.** Observed live (session `f56a9039-...`): it generated new questions for importance=2 Subcategories while two importance=3 seed questions (`GVQ-07`/`GV.SC-04`, `GVQ-08`/`GV.SC-06`) sat unused. `csf_coordinator/prompts/next_question.txt`'s `seed_questions_block` isn't ranked/annotated with `need_score` the way `coverage_block` is — likely fix: sort or label it the same way, or add an explicit "check the seed bank against the top-ranked Subcategory first" step. TODO comment left in the prompt file itself.

---

## 9. Useful test sessions (already in Firestore + Qdrant)

- `23a53272-6cd8-40b8-a363-f826eb76aa6d` — target_org `"Test1"` (not renamed — rename before demo use). **Best test session for demo-quality Govern data**: 3 real docs including the discovered Northwind-authored `Information_Security_Policy.docx` (not generic SANS), 21 preseed answers loaded, `runs/phaseF/{scores,tiers}/` has all 6 Govern Categories + Tier persisted (re-scored post-ADK-retrofit, currently Tier 1-3 depending on run — LLM sampling variance across re-runs, not a bug).
- `f56a9039-877e-4a24-adc6-efafa22d104b` — target_org `"test-2"`. Clean-room pipeline proof: 3 generic (non-Northwind) SANS docs, **no preseed**, scored docs-only via the real coordinator/Pub/Sub/worker round trip (Tier 1, honestly low — no company-specific evidence). Also has a full real 12-turn interview transcript in `answers/` (6 seed + 6 generated questions, `chat_state.done=true`) — best session for testing/demoing the interview agent, since it's already got a complete real transcript to inspect.
- `b8bc86d2-10ce-4c43-ad3e-081ad9203d7f` — Northwind Financial, 3 generic SANS docs (Encryption Policy + Access Control + IR Plan). Has `runs/adhoc/scores/` populated with 6 Govern scores from Aug 15 testing (pre-preseed) and 21 preseed answers loaded loose in `answers/` (Phase E verification — not scored with a persisted `run_id`).
- `715a261b-bbaf-423b-82f7-5d9f25bcee39` — Acme Corp, 1 Encryption Policy. Multi-org test session.
- `58e14048-b1ed-4cfb-abf6-6445fe33126b` — Beta Industries (org_id=beta-inc), 1 IR Plan. Multi-org test.
- List more via: `poetry run python -c "import asyncio; from google.cloud.firestore import AsyncClient; from csf_gateway.app.config import get_settings; async def m(): [print(s.id, s.to_dict().get('target_org')) async for s in AsyncClient(project=get_settings().google_cloud_project).collection('sessions').limit(20).stream()]; asyncio.run(m())"`

---

## 10. Fastest way to get productive in the new session

**Step 1 (2 min):** load memory (`MEMORY.md` will auto-inject) + open `docs/HANDOFF.md` (this file) + `docs/govern_build_tasks.md` (the tracker).

**Step 2 (verify the world still works):**
```bash
cd /Users/meghaagarwal/Desktop/Codes/Personal/csf-nist
lsof -ti:8090 | xargs kill 2>/dev/null; true
poetry run uvicorn csf_gateway.app.main:app --port 8090 --log-level warning &
sleep 3
curl -s http://localhost:8090/health | python3 -m json.tool
kill %1 2>/dev/null; wait
```
Expect `{"status":"healthy", "qdrant":"ok (N points)", ...}`.

**Step 3 (verify Govern agent still works):**
```bash
poetry run python -c "
import asyncio
from csf_specialists.agents.govern import govern_agent
async def m():
    r = await govern_agent.score_category('GV.OC', 'b8bc86d2-10ce-4c43-ad3e-081ad9203d7f')
    print(f'CMMI={r.cmmi_level} conf={r.confidence:.2f} subs={len(r.subcategory_scores)}')
asyncio.run(m())
"
```
Expect `CMMI=1 conf=0.85 subs=5` if preseed hasn't been loaded into this session yet, or `CMMI=1 conf≈0.85+, interview_evidence non-empty` if it has (preseed was loaded into `b8bc86d2-...` during Phase E — GV.OC wasn't part of the before/after table in §2, so its exact numbers may have shifted too; GV.SC and GV.RM are the two verified data points).

**Step 4:** Phases E-G are all done. The two forks originally flagged here are both resolved as of Aug 17: aggregation formula decided (Category-weighted, `csf_specialists/aggregate.py`, see §8) and the Identify agent has been genericized and verified (`csf_specialists/agents/identify.py`, see `task_list.md`'s Mon Aug 17 entry). Current open item: whether to build `.xlsx`/`.pptx` ingest support before testing the full 16-document Northwind package, or test with the 11 supported `.docx` files first (see §12).

The regulatory-jurisdiction conflict is now resolved — UK (PRA/FCA), confirmed by the teammate's real 16-document delivery, locked persona corrected (see §7). `csf_specialists/sample_data/northwind_preseed_govern.json` still has 3 old US-regs-flavored answers (NWP-GV-02/03/15) — left as-is (historical artifact, already served its purpose), just don't preseed it into new sessions that also use the real 16-doc package, to avoid two contradictory Q&A voices in the same session.

---

## 11. Memory setup

The `~/.claude/projects/-Users-meghaagarwal-Desktop-Codes-Personal-csf-nist/memory/MEMORY.md` file auto-injects at session start. It currently indexes:
- `user_megha.md` — Megha's role, fluency level
- `project_csf_assessor_fleet.md` — project overview + deadline
- `tech_stack_locked.md` — Google ADK + Vertex + Qdrant + GCP
- `feedback_division_of_labor.md` — Megha/Sakina hard rule
- `project_northwind_demo_persona.md` — locked demo target + PR.AA-05 money-shot
- `reference_plan_doc.md` — pointer to the 19-day plan
- `feedback_edit_summaries.md` — hard rule to close every edit with what-was-built / what-to-expect / how-to-test-manually

---

## 12. One-line summary for the new session's first message

**Paste this into the new Claude Code session:**

> Read `docs/HANDOFF.md`. All 4 of Sun Aug 16's `[M]` tasks are done, Identify agent is generalized and verified alongside Govern (`csf_specialists/agents/identify.py`, `csf_coordinator.run_assessment()` runs both), and the regulatory-jurisdiction question is resolved: Northwind is UK-regulated (PRA/FCA/SM&CR), confirmed by the teammate's real 16-document package in `02. Documents/` (delivered Aug 15-17) — the locked persona has been corrected to match. `.xlsx` ingest support was added Aug 18 (`csf_gateway/app/ingest/xlsx_parser.py`), so 14 of 16 real Northwind files are now ingestable; the remaining 2 `.pptx` files (`Internal_Audit_Report`, `Risk_Appetite_Statement`) are deferred as future scope, not yet supported. Also: don't preseed `northwind_preseed_govern.json` into any new session that also uses the real doc package — it still has old US-regs-flavored answers, kept as a historical artifact, not patched.
