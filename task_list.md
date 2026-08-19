# CSF Assessor Fleet — Task List

Source of truth: [docs/csf_assessor_hackathon_plan.md](docs/csf_assessor_hackathon_plan.md) + end-to-end system plan at `~/.claude/plans/now-lets-plan-the-mossy-glacier.md`
Legend: **[M]** = Megha (tech), **[T]** = Teammate (KPMG domain). Check off as completed.

**Scope note (from approved system plan):** rubrics are per **Category** (~22 total), NOT per Subcategory (~106). Sakina scores at Category level to save time. All "subcategory" task counts below have been rescaled.

---

## PHASE 1: Foundation (Thu Aug 13 → Sat Aug 15)

### Thu Aug 13
- [x] **[M]** by 10 AM ET — Devpost registration (both) + GCP $300 credit forms submitted
- [x] **[M]** by 12 PM ET — register for Aug 13 webinar (Long-Running Agents with ADK); attend live or watch recording by EOD
- [x] **[M]** by 3 PM ET — GCP project created + enable Vertex AI, Cloud Run, Firestore, Pub/Sub, Vector Search, Cloud SQL, Cloud Storage, Secret Manager
- [x] **[M]** by 3 PM ET — billing alerts set at $30, $60, $100, $140
- [x] **[M]** by 6 PM ET — GitHub repo created (private for now), Python 3.11 + poetry/uv scaffolded
- [x] **[M]** by 9 PM ET — ADK "hello world" agent running locally + deployed to Cloud Run
- [x] **[M]** follow-up — resolved by superseding: `adk-default-service-name` deleted (Aug 15), replaced by cleanly-named `csf-gateway` Cloud Run service via `infra/deploy_gateway.sh`. Hello-agent proof-of-life served its purpose.
- [ ] **[T]** by 12 PM ET — read hackathon Fortified track requirements end to end — **deprioritized Aug 18**: Sakina is running behind on rubrics/content already, not adding this to her plate right now. Means our Fortified-component list (Registry/Memory Bank/Identity/Gateway/Model Armor/Observability) is still only Megha's own Aug 12 interpretation, never independently verified against the official page. Low risk short-term (doesn't block any code), but worth a solo re-read by Megha before the Aug 22-24 Fortified-layer crunch in case the real requirements differ.
- [x] **[T]** by 9 PM ET — draft CMMI 1-5 rubric for 3 highest-priority Govern **Categories** (15 cells) — **delivered all 6 Govern Categories** in `Ref Docs/NIST Rubrics.xlsx` sheet Govern (5 levels each). Extracted to `csf_specialists/rubrics/govern.yaml`.
- [ ] **[T]** by 9 PM ET — draft 8 interview questions for Govern — **PENDING from Sakina**
- [x] **[T]** by 9 PM ET — confirm which regs apply to Northwind (GLBA, NYDFS, PCI, SOX, state insurance) — **resolved Aug 18, differently than this item assumed.** Answer isn't GLBA/NYDFS/PCI/SOX at all — the teammate's real 16-document delivery (Aug 15-17) confirms Northwind is UK dual-regulated: PRA/FCA, SM&CR, PRA PS6/21 & FCA PS21/3, SYSC 8/13, UK GDPR + DPA 2018 (ICO). Locked persona corrected — see `docs/HANDOFF.md`.
- [ ] **[Both]** by 9:30 PM ET — status shared in shared doc — **PENDING**

### Fri Aug 14
- [x] **[M]** by 12 PM ET — ingest pipeline: FastAPI `POST /sessions/{sid}/documents` accepts multipart PDF/DOCX with per-file `doc_types`, section-aware Gemini-multimodal parser + chunker (Phase E5), raw → GCS (`storage.upload_raw`), chunks + metadata → Firestore (`firestore_writer.write_document` + `write_chunks`). Full HTTP → GCS → Firestore → Qdrant flow verified.
- [x] **[M]** by 6 PM ET — Vector store ready + embedding pipeline running. Qdrant Cloud `csf_chunks` collection live (Phase A, superseded from Vertex — see [ADR-0001](docs/decisions.md)) + async embedder via google-genai using text-embedding-004 (Phase E7) + Qdrant upsert wrapper (Phase E8). Verified end-to-end by ingesting a real SANS PDF: chunks flow through embedder → Qdrant with correct 768-dim vectors and session-scoped payload filters.
- [x] **[M]** by 9 PM ET — ingest tested with 3 SANS policy templates end-to-end via `POST /sessions/{sid}/documents`. All 3 reached `ingest_status: ready` in ~26s (well under the informal 60s target). Duplicate + oversized + wrong-extension validation paths all verified in the same test.
- [x] **[T]** by 9 PM ET — complete CMMI rubric for remaining Govern Categories (~3 more, ~15 cells) + finish 8 Govern interview questions — **Rubric part: done** (all 6 Categories in `Ref Docs/NIST Rubrics.xlsx`). **Interview questions: PENDING from Sakina.**
- [x] **[T]** by 9 PM ET — draft CMMI rubric for 3 highest-priority Identify Categories (~15 cells) — **delivered all 3 Identify Categories** in the same file. Extraction pending on Megha side (Identify rubric YAML not yet built).
- [ ] **[T]** by 9 PM ET — draft 8 interview questions for Identify — **PENDING from Sakina**
- [ ] **[T]** by 9 PM ET — evidence taxonomy v1: table mapping doc types to Categories they satisfy — **PENDING from Sakina**. **When delivered → immediately wire into `vector_store.search_session(..., doc_type_filter=...)`** to filter Qdrant retrieval per-Category. `search_session` already accepts the parameter — just needs the taxonomy data to key off of. Biggest single precision-improvement lever available, larger than any `top_k` tuning. See `docs/govern_build_tasks.md` follow-ups.

### Sat Aug 15 (weekend — deep work day)
- [x] **[M]** by 3 PM ET — first Govern agent stub wired to Vertex AI (Gemini 3.5 Flash structured output) + Vector Search (Qdrant, session-scoped with adaptive top_k) + Firestore (optional persistence). `csf_specialists/agents/govern.py` importable, `govern_agent.score_category()` fully functional. Phases A-D per [docs/govern_build_tasks.md](docs/govern_build_tasks.md).
- [x] **[M]** by 3 PM ET — Pydantic output schema shipped early in [csf_gateway/app/schema.py](csf_gateway/app/schema.py): `ScoreOutput{category_id, function, cmmi_level, confidence, evidence_citations, interview_evidence, reasoning, no_doc_evidence}` + `EvidenceCitation`, `TierResult`, `JudgeResult`
- [x] **[M]** by 9 PM ET — Govern agent runs on a single Category, returns valid structured output. Verified on all 6 Govern Categories against a real session (b8bc86d2 with 3 SANS docs): CMMI 1-2 per Category, avg 1.3 → Tier 1, well-formed evidence_citations + subcategory_gaps in every response. 3× back-to-back GV.PO runs clean. Cost ~$0.06/full-Function-scoring.
- [x] **[T]** by 12 PM ET — complete CMMI rubric for remaining Identify Categories — **all 3 Identify Categories delivered** in `Ref Docs/NIST Rubrics.xlsx` sheet Identify (5 levels each).
- [ ] **[T]** by 3 PM ET — Northwind Financial doc package delivered (5-7 policies, org chart, asset inventory, risk register, incident log, vendor list) — **PENDING from Sakina**. Megha will seed sample Northwind pre-seed Q&A in Phase E to unblock Govern testing.
- [ ] **[T]** by 6 PM ET — golden test set v1 (5 Northwind policies + expert CMMI scores for all Govern Categories ≈ 30 tuples) — **PENDING from Sakina**
- [ ] **[T]** by 9 PM ET — review Megha's Govern agent output, flag every domain error in shared doc — pending Megha's Govern agent output first (blocks on M task)
- [ ] **[T]** by 9 PM ET — start Protect CMMI rubric (Categories, if time permits) — **PENDING from Sakina**

### Phase 1 Gate (Sat EOD Aug 15)
- [x] GCP fully set up, credits active — project, APIs, buckets, Firestore, Pub/Sub, Secret Manager, Artifact Registry all provisioned via `infra/setup.sh`; billing alerts live.
- [x] ADK hello-world deployed — superseded by `csf-gateway` on Cloud Run (deployed Aug 15, live at `https://csf-gateway-jdogd2dq2q-uc.a.run.app`). Original hello-agent removed.
- [x] Ingest pipeline working end to end — verified locally (Phase A-G, all Phase G test items green) AND against the deployed `csf-gateway` URL (H5 smoke test: SANS PDF → GCS → Gemini multimodal parse → chunker → embeddings → Qdrant + Firestore in ~15s).
- [ ] Govern + Identify CMMI rubrics locked (all Categories, ~40 cells) — **[T]** Sakina
- [ ] Interview questions locked for Govern + Identify (16 questions) — **[T]** Sakina
- [ ] Northwind Financial doc package received in full — **[T]** Sakina (Sat Aug 15 3 PM ET)
- [ ] Golden test set v1 exists (~30 tuples for Govern) — **[T]** Sakina (Sat Aug 15 6 PM ET)
- [x] Govern agent produces structured output — **[M]** verified Aug 15-16 across `b8bc86d2-...` and `23a53272-...` (persisted `run_id='phaseF'` run, Tier 3 result matching the locked target). **Caveat:** validated against Megha-authored preseed Q&A + partial real docs, not Sakina's actual Northwind doc package or golden test set — both still owed.

---

## PHASE 2: Vertical Slice (Sun Aug 16 → Fri Aug 21)

### Sun Aug 16 (weekend — deep work day)
- [ ] **[Both]** 11:00 AM–12:30 PM ET — Sunday review: what shipped/slipped, rubric quality check, adjust Phase 2 plan — **did not happen**, joint call, not something Megha can substitute
- [x] **[M]** by 3 PM ET — interview agent using ADK: conversational, asks questions from bank, stores answers in Firestore per session — done late (evening, not by 3 PM). Real ADK `LlmAgent` decision per turn (`csf_coordinator/interview.py`), `POST /sessions/{sid}/chat/{next,answer,finish}` (`csf_gateway/app/chat.py`). Not a fixed bank — mixes unused seed questions (`sample_data/govern_questions.json`) with NIST-grounded generated ones (`Provenance.live_chat_generated`), verified live: 6 seed + 6 generated over a real 12-turn interview.
- [x] **[M]** by 6 PM ET — Level 1 adaptive logic: LLM decides which questions to skip based on previous answers — same build as above (one LLM decision per turn does both). **Known limitation, logged as a TODO in `next_question.txt` + HANDOFF.md**: doesn't reliably prefer high-importance unused seed questions before generating new ones.
- [x] **[M]** by 8 PM ET — session state persistence via Firestore, tested end to end — `chat_state` (questions_asked/done/pending) round-trips through the session's Firestore doc on every turn; verified a full 12-question transcript persisted and readable back correctly, and that the safety cap (`MAX_QUESTIONS=12`) correctly short-circuits without an LLM call once hit.
- [x] **[M]** by 9 PM ET — coordinator agent stub: routes to Govern only, publishes to Pub/Sub, subscribes to results — done ahead of the other 3, and past "stub": real ADK `SequentialAgent` (`csf_coordinator/coordinator.py`) + real GCP Pub/Sub topics (not mocked), verified end-to-end round trip (dispatch → `csf_specialists/worker.py` scores → aggregate → Tier persisted).
- [x] **[T]** by 6 PM ET — CMMI rubric for all Protect Categories + 8 interview questions — **Rubric part: done Aug 19** (all 5 Protect Categories in `Ref Docs/NIST Rubrics.xlsx` sheet Protect, extracted via `infra/build_rubric_yaml.py --function protect` to `csf_specialists/rubrics/protect.yaml` + `csf_specialists/implementation_examples/protect.yaml`, 22 Subcategories/77 examples, clean extraction, no warnings). **Interview questions: still PENDING from Sakina** (deprioritized Aug 18, Megha proceeding with stand-ins where needed).
- [ ] **[T]** by 9 PM ET — expand golden test set: 3 more Northwind policies scored across Govern + Identify (~50 tuples total)

### Mon Aug 17 (teammate: evening only)
- [x] **[M]** by 6 PM ET — scoring engine: consumes agent outputs, aggregates CMMI per Category, computes Function-level average — **done a day early**, Aug 16: `csf_specialists/aggregate.py`, verified Tier 3 on real data.
- [x] **[M]** by 9 PM ET — report generator v1: JSON output listing scored Categories with CMMI level, evidence citations, reasoning — `csf_specialists/scripts/export_json.py`. Also includes the aggregated Tier + full per-Subcategory findings (observations/gap/recommendation) as a foundation for v2/v3. Verified against real persisted data.
- [x] **[M]** NEW, moved up from Thu Aug 20 — Identify agent genericization (`csf_specialists/agents/identify.py` + rubric already extracted). Base class already supports any Function; no reason to wait until Thu when it's now cheap. **Aug 17 resequencing** (see note below Fri Aug 21 gate) pulled this and one Fortified item forward to de-risk the Aug 22-24 crunch. **Verified live**: all 3 ID Categories (7+10+4=21 Subs) scored correctly on real doc evidence (`no_doc_evidence=False` throughout), plus `aggregate.py`/`export_json.py`/`export_excel.py` all generalized to `function="identify"` with zero code changes — confirms today's pipeline isn't Govern-specific. Tier 1 (avg_cmmi 1.67) — honest low result, no Identify-specific preseed exists yet.
- [ ] **[T]** by 10 PM ET — CMMI rubric for half of Detect Categories
- [ ] **[T]** by 10 PM ET — review Govern agent scores against golden set, flag disagreements

### Tue Aug 18 (teammate: evening only)
- [x] **[M]** unplanned, ahead of scheduled items — `.xlsx` ingest support (`csf_gateway/app/ingest/xlsx_parser.py`). Unblocks 3 of the 5 previously-unsupported real Northwind files (Vendor List, Enterprise Risk Register, Regulatory Requirements Register). Verified end-to-end incl. a live `GV.SC` scoring run citing all 3 as evidence. `.pptx` (2 remaining files) explicitly deferred, not built — see `docs/HANDOFF.md`.
- [x] **[M]** by 6 PM ET — report generator v2: HTML output via Jinja2, Plotly radar chart embedded — `csf_specialists/scripts/export_html.py` + `csf_specialists/templates/report.html.j2`. Reuses `export_json.build_report` (same Firestore read, no second query path). **Two radars**, matching the plan's own two-layer scoring model (§2/§3/§10): a Tier radar (one spoke per Function, r=Tier 1-4, the board-level view) and a Category radar (one spoke per Category grouped by Function, r=CMMI 1-5, the practitioner drill-down). First pass had collapsed both into one Category-only radar — caught during the Aug 18 realign check and split same day. Per-Category cards: CMMI pill (own 5-color ramp, distinct from the 4-color Tier ramp), confidence, `no_doc_evidence` flag, reasoning, full Subcategory table (observations/gap/recommendation), evidence citations, interview evidence ids. Verified against real persisted data — single-Function run (`23a53272-.../phaseF`, 6 Govern Categories) and a 2-Function run (`f56a9039-.../f15764f4-...`, Govern+Identify, 9 Categories) — via headless-Chrome screenshots. Two real bugs caught and fixed along the way: Tier badge was dumping the raw Firestore dict instead of the `tier` int, and the missing Tier-level radar itself.
- [x] **[M]** by 9 PM ET — Streamlit app v1: upload docs, chat interview, view report — `csf_ui/app.py`, `poetry run streamlit run csf_ui/app.py` (port 8501). Talks to the gateway over HTTP for session/document/chat (those own real async background work tied to the gateway's own event loop); calls `csf_coordinator.run_assessment` and `csf_specialists.scripts.export_html` directly as library functions for run/report (no server-side state of their own, HTTP would add nothing). "Run assessment" spawns one one-shot `worker.py --function <fn>` subprocess per live agent right before calling `run_assessment`, since nothing else would consume its Pub/Sub dispatch otherwise (see `csf_coordinator/steps.py`'s `CollectResultsStep`, up to a 900s wait). Report route is the embedded static HTML from today's `export_html.py` via `st.components.v1.html` — native `st.plotly_chart` charts are the Aug 21-22 follow-up (line below), not v1 scope. Verified with a full Playwright-driven browser run: session create → real XLSX upload → interview Q&A → live assessment run (both `govern` and `identify` workers actually dispatched, scored, and published over real Pub/Sub) → Tier metrics displayed (Govern Tier 1/avg 1.00, Identify Tier 1/avg 1.33) → report generated and embedded. Two real bugs caught and fixed during testing: (1) the document-upload multipart call passed `doc_types` as a list of tuples, which httpx's multipart encoder can't handle alongside `files` — fixed to the dict-of-list form `{"doc_types": [...]}`, confirmed against httpx's own request encoder before and after; (2) no visual feedback while `/chat/next` was making its LLM call, which read as "broken" under a fast/impatient test — added a spinner.
- [ ] **[M]** NEW, pulled forward from Mon Aug 24 — Agent Observability v1: OpenTelemetry spans around the ADK calls in `agent_base.py` + `interview.py`. Cheapest real Fortified win (purely additive logging, no new IAM/security model) — doing it now while touching agent code anyway, rather than saving it for the Aug 24 crunch.
- [ ] **[T]** by 10 PM ET — complete Detect Categories rubric + 8 Detect interview questions

### Wed Aug 19 (teammate: evening only)
- [x] **[M]** unplanned, user-driven redesign of Streamlit app v1 into v2 — `csf_ui/app.py` rebuilt around 5 changes requested after using v1 live: (1) sessions persist and are browsable (new `GET /sessions` + `sessions.list_sessions()`, sidebar session list, switching never loses a session), (2) interview reads as a real chat (`st.chat_message`/`st.chat_input`, no manual "get next question" button — auto-continues after every answer), (3) the AI picks which Function a question is about, never the user (new `interview.decide_next_question_auto` — cross-Function `need_score` comparison, reuses the existing per-Function coverage formula rather than a new gap-analysis system; `POST /chat/next`'s `function` param is now optional, backward compatible), plus freeform Q&A document upload (`POST /sessions/{sid}/qna`, new `csf_specialists/qna_extractor.py` — one ADK structured-output call classifies an arbitrary completed questionnaire against the full 6-Function catalog; verified against both a real blank Northwind template, which correctly extracted zero rather than hallucinating, and a synthetic completed one, which correctly classified 3/3 pairs including the exact PR.AA money-shot area), (4) every session shows Docs/Chat/Reports as its own view (`st.segmented_control`, not native `st.tabs` — those can't be set programmatically, which the Docs→"Next"→Chat flow needs), (5) reports restructured as tabs — Overview (both radars natively via `st.plotly_chart`, reusing `export_html.py`'s already-pure-data `build_report`/`_build_context`/`_tier_radar_figure`/`_category_radar_figure`, no Jinja involved) + one tab per scored Function, plus "Download HTML" and new "Download Excel" buttons (`export_excel.py`'s functions written to a `BytesIO`, no temp file). One real Streamlit bug hit and fixed along the way: mutating a widget's `session_state` key after that widget already rendered in the same script run raises `StreamlitAPIException` — fixed via an `on_click` callback for the Docs view's "Next → Chat" button. One backend robustness gap found via real testing (not manufactured): `/chat/next` had no guard against being called while a question was already pending, which a duplicate call (observed live) could silently overwrite — added a check that returns the existing pending question instead of recomputing. Verified with a full Playwright browser walkthrough: new session → upload → chat auto-asks with no Function picker anywhere → answer → QnA doc extraction → run assessment (real Pub/Sub dispatch, both workers) → tabbed report with working native radars → both downloads captured and validated → switched sessions and confirmed zero stale-data bleed.
- [ ] **[M]** NEW, found via live testing — session-creation UI has no company-name input, always defaults to "Northwind Financial" even though the backend already supports a custom `target_org`. See `docs/HANDOFF.md` §7 for fix detail.
- [ ] **[M]** NEW, found via live testing — Docs view has no auto-polling/progress bar; "Refresh status" button is inert. Gateway already has a per-doc progress endpoint built for 1-2s polling that the UI never calls. See `docs/HANDOFF.md` §7.
- [ ] **[M]** NEW, found via live testing — add a "Run assessment now" button to the Chat view (currently only in Reports). See `docs/HANDOFF.md` §7.
- [ ] **[M]** NEW, found via live testing — Overview report tab should show only the 6-Function Tier radar; each per-Function tab should get its own Category-level radar (currently Overview shows both, with the Category radar merging every scored Function into one overlaid chart). Applies to both the Streamlit Reports view and the exported HTML report. See `docs/HANDOFF.md` §7.
- [ ] **[M]** NEW, found via live testing — exported HTML report's two radar charts overlap/bleed into each other (fixed-width Plotly divs vs. a flexbox layout with no max-width), and a Function with <3 scored Categories renders as a degenerate empty-looking circle. See `docs/HANDOFF.md` §7.
- [ ] **[M]** by 6 PM ET — templatize Govern agent config-driven so remaining Functions plug in via config
- [ ] **[M]** by 9 PM ET — LLM-as-Judge pass on Govern agent outputs (Gemini Pro grades CMMI defensibility)
- [ ] **[T]** by 10 PM ET — CMMI rubric for all Respond Categories + 8 Respond interview questions
- [ ] **[T]** by 10 PM ET — recommendation templates: 30 standard remediation templates for CMMI L1/L2 findings

### Thu Aug 20 (teammate: evening only)
- [ ] **[Both]** 12–1:30 PM ET — Aug 20 webinar (Self-Evolving Agents), live or recording
- [ ] **[M]** by 6 PM ET — confidence threshold logic: below 0.6, agent flags "insufficient evidence"
- [ ] ~~**[M]** by 9 PM ET — deploy Identify agent~~ — **moved to Mon Aug 17** (Aug 17 resequencing) — check that day's checkbox instead, not this one.
- [ ] **[T]** by 10 PM ET — CMMI rubric for all Recover Categories + 8 Recover interview questions **(COMPLETES ALL 6 FUNCTIONS)**
- [ ] **[T]** by 10 PM ET — confirm CSF Tier aggregation ranges (CMMI avg → Tier mapping)

### Fri Aug 21 (teammate: evening only)
- [ ] **[M]** by 3 PM ET — vertical slice integration: upload → interview → Govern scores CMMI → aggregates to Tier → LLM-as-Judge validates → report with radar
- [ ] **[M]** by 9 PM ET — fix all breakages found during first end-to-end run
- [ ] **[M]** NEW, added Aug 18, flexible Aug 21-22 — refine report generator v2 (`csf_specialists/scripts/export_html.py` + `report.html.j2`, built today as a functional first pass): make it more comprehensive to view (drill-down/collapsible Category detail instead of one long scroll, roadmap-style gap prioritization, better print/scan layout) and integrate it into the Streamlit UI as a live view (`st.plotly_chart` for the radar / embedded HTML) rather than only a downloadable file. Do after the Streamlit app + vertical slice both exist, since this is UI-integration work, not a standalone script change.
- [ ] **[T]** by 10 PM ET — executive summary language templates: one paragraph per Tier per Function (24 templates)
- [ ] **[T]** by 10 PM ET — run vertical slice on Northwind docs, score Govern output herself, log disagreements

### Phase 2 Gate (Fri EOD Aug 21)
- [ ] Vertical slice: end-to-end Govern assessment works
- [ ] CMMI agreement rate with teammate ≥ 60% (targeting 80% by week 3)
- [ ] All 6 Function CMMI rubrics locked (~22 Categories, ~110 cells)
- [ ] All 6 Function interview questions locked (~50 questions)
- [ ] CSF Tier aggregation ranges confirmed
- [ ] Executive summary templates ready
- [ ] Report renders with radar chart, CMMI table, evidence citations

**Slippage rule:** if Phase 2 gate fails, cut Fleet from 6 to 4 Functions (Govern + Identify + Protect + Detect).

---

## PHASE 3: Fleet + Fortified Layer (Sat Aug 22 → Wed Aug 26)

### Sat Aug 22 (weekend — deep work day)
- [ ] **[M]** by 12 PM ET — deploy Protect + Detect specialist agents (4 primary Functions live)
- [ ] **[M]** by 4 PM ET — deploy Respond + Recover agents (all 6 live)
- [ ] **[M]** by 7 PM ET — full parallel coordinator via Pub/Sub: dispatches to all 6 agents, waits, aggregates
- [ ] **[M]** by 9 PM ET — Agent Registry in Firestore: each agent publishes metadata (name, version, capabilities, owner Function, IAM identity) — cheap/incremental; consider having each new Function agent self-register on deploy instead of one big-bang implementation this day.
- [ ] **[T]** by 3 PM ET — review outputs from Identify, Protect, Detect on Northwind docs
- [ ] **[T]** by 6 PM ET — review outputs from Respond + Recover on Northwind docs
- [ ] **[T]** by 9 PM ET — golden test set expansion to ~66 tuples covering all 22 Categories

### Sun Aug 23 (weekend — deep work day)
- [ ] **[Both]** 11:00 AM–12:30 PM ET — Sunday review: vertical slice + fleet running, CMMI agreement ≥ 70%?, adjust Phase 4
- [ ] **[M]** by 3 PM ET — Agent Identity: IAM service account per agent, workload identity binding — the hardest of the 3 originally crammed here; now has the day mostly to itself after Registry/Observability moved out (Aug 17 resequencing)
- [ ] **[M]** by 6 PM ET — Memory Bank: per-assessment canonical target-org state in Firestore (or Vertex Memory Bank if stable) — arguably partially exists already via `runs/{run_id}.snapshot` (doc_ids/answer_ids), built Aug 17; confirm if that counts or needs more
- [ ] **[M]** by 9 PM ET — Model Armor / Cloud DLP: PII scrub before every LLM call, log redactions — the other hard one; still same day as Identity, but no longer sharing with Registry too
- [ ] **[T]** by 6 PM ET — draft demo script v1 (4 min, word-for-word)
- [ ] **[T]** by 9 PM ET — pre-write 4 interview answers Northwind would give during demo

### Mon Aug 24 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — Agent Gateway: single FastAPI ingress that authenticates, rate-limits, routes to agents
- [ ] ~~**[M]** by 9 PM ET — Agent Observability: OpenTelemetry spans per agent call, exported to Cloud Trace~~ — **moved to Tue Aug 18** (Aug 17 resequencing), freeing this day down to just Gateway hardening
- [ ] **[T]** by 10 PM ET — executive summary written for Northwind (3 paragraphs, sets tone the agent should match)

### Tue Aug 25 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — report generator v3: exec summary + radar (Tier) + Category table (CMMI) + prioritized roadmap (top 10 gaps)
- [ ] **[M]** by 9 PM ET — cost dashboard: tokens used, cost per assessment, latency per agent
- [ ] **[T]** by 10 PM ET — findings, gaps, roadmap wording refinements based on latest agent outputs

### Wed Aug 26 (teammate: evening only)
- [ ] **[M]** by 9 PM ET — final integration pass: full 6-agent fleet end-to-end with all Fortified components live
- [ ] **[M]** by 9 PM ET — first automated golden test set eval run, log baseline scores
- [ ] **[T]** by 10 PM ET — full re-run of assessment on Northwind, score every output, log disagreements

### Phase 3 Gate (Wed EOD Aug 26)
- [ ] All 6 Function agents deployed, running in parallel via coordinator
- [ ] Agent Registry, Memory Bank, Agent Identity, Agent Gateway, Model Armor (or DLP), Observability all working
- [ ] Report renders with exec summary, radar chart, CMMI table, roadmap
- [ ] CMMI agreement ≥ 70%

---

## PHASE 4: Polish + Eval (Thu Aug 27 → Sat Aug 29)

### Thu Aug 27 (teammate: evening only)
- [ ] **[Both]** 12–1:30 PM ET — Aug 27 webinar (Agent Memory), live or recording
- [ ] **[M]** by 6 PM ET — fix top 10 domain errors teammate flagged
- [ ] **[M]** by 9 PM ET — golden test set eval automated: retrieval@5, CMMI agreement rate, confidence calibration → README
- [ ] **[M]** by 9 PM ET — prompt caching for repeated rubric context per Function agent
- [ ] **[T]** by 10 PM ET — draft LinkedIn post (both) and blog post outline
- [ ] **[T]** by 10 PM ET — review polished report for tone, structure, wording

### Fri Aug 28 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — UI polish: radar interactive, drill-down into reasoning chain, evidence citations clickable, cost + latency badge
- [ ] **[M]** by 9 PM ET — architecture diagram (excalidraw/draw.io): Fortified components labeled
- [ ] **[T]** by 10 PM ET — blog post draft (domain angle): "$80K CSF assessment → 15 minutes without losing rigor"

### Sat Aug 29 (weekend — both available all day)
- [ ] **[M]** by 12 PM ET — reproducibility check: clone fresh, follow README, deploy from scratch; fix every broken step
- [ ] **[M]** by 4 PM ET — README polish: architecture diagram, spin-up, tech stack, eval numbers, cost, limitations, future work
- [ ] **[M]** by 7 PM ET — blog post draft (technical angle): "Multi-agent Fortified fleet on Google ADK, lessons learned"
- [ ] **[M]** by 9 PM ET — backup demo recording session: full 4-min take end-to-end
- [ ] **[T]** by 2 PM ET — practice demo script solo (out loud, 3 times)
- [ ] **[T]** by 5 PM ET — full run-through of demo script on Zoom together (1 hr), refine
- [ ] **[T]** by 9 PM ET — available for backup recording session

### Phase 4 Gate (Sat EOD Aug 29)
- [ ] CMMI agreement ≥ 80% on golden set
- [ ] README complete, reproducible from clean clone
- [ ] Architecture diagram done
- [ ] Demo script rehearsed at least 3 times
- [ ] Both blog posts drafted
- [ ] At least one demo take recorded (backup)

---

## PHASE 5: Demo + Submit (Sun Aug 30 → Mon Aug 31)

### Sun Aug 30 (weekend — both available all day)
- [ ] **[M]** by 11 AM ET — review Sat backup take, decide if Take 2 needed
- [ ] **[M]** by 1 PM ET — record demo Take 2 (both on Zoom, OBS or Loom, split-screen of 6 agents = money shot)
- [ ] **[M]** by 3 PM ET — review Take 2, note fixes for Take 3
- [ ] **[M]** by 5 PM ET — record demo Take 3 if needed
- [ ] **[M]** by 8 PM ET — edit final video (Descript or CapCut, 4 min, clear audio)
- [ ] **[M]** by 10 PM ET — upload final video to YouTube (unlisted)
- [ ] **[T]** 11 AM–8 PM ET — present her portion during each take, review each cut, approve final
- [ ] **[T]** by 10 PM ET — publish blog post on Medium
- [ ] **[T]** by 10 PM ET — publish LinkedIn post with #AllThingsAgenticHackathon (Megha does the same)

### Mon Aug 31 (submission day — teammate at KPMG most of day)
- [ ] **[M]** by 9 AM ET — final smoke test on deployed Cloud Run URL
- [ ] **[M]** by 9 AM ET — GitHub repo public OR shared with testing@devpost.com + cloudhackathons@google.com
- [ ] **[M]** by 10 AM ET — publish own blog post on dev.to (technical angle)
- [ ] **[M]** by 11 AM ET — Devpost submission form draft filled (all fields ready)
- [ ] **[Both]** 11 AM–12 PM ET — quick call, verify Devpost form, submit
- [ ] **[M]** afternoon — shut down non-essential Cloud services to preserve credits
- [ ] **[M]** afternoon — screenshots of submitted state for records

### Submission Checklist
- [ ] Devpost form filled
- [ ] Category selected: **Fortified Enterprise Fleet**
- [ ] Also submitted for: Best Architectural Design, Startup Excellence (if applicable)
- [ ] Hosted URL live (or Cloud Console screenshots in demo prove it ran)
- [ ] GitHub URL live, README complete, reproducibility tested
- [ ] Private repo shared with testing@devpost.com AND cloudhackathons@google.com
- [ ] Architecture diagram uploaded
- [ ] Demo video (4 min) uploaded to YouTube, link in submission
- [ ] Text description filled: features, tech, data sources, findings, learnings
- [ ] 1 blog post published (Medium or dev.to) with hackathon language
- [ ] 1 LinkedIn post published with #AllThingsAgenticHackathon
- [ ] Cloud services shut down post-recording to preserve credits
- [ ] **SUBMITTED by 12 PM ET** (hard deadline 8 PM ET)
