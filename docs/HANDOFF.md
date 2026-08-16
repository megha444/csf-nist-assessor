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
- `NIST Rubrics.xlsx` — 2 sheets so far (Govern, Identify); 6 + 3 Categories with 5-level CMMI text
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
│       ├── sessions.py             session CRUD + FastAPI router
│       ├── documents.py            batch upload + status polling
│       └── ingest/                 async pipeline (10 modules)
│           ├── storage.py          GCS raw upload
│           ├── dedupe.py           SHA256 dedupe per session
│           ├── pdf_parser.py       Gemini 3.5 Flash multimodal → markdown
│           ├── docx_parser.py      python-docx → markdown
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
│   ├── agents/govern.py            govern_agent singleton
│   ├── prompts/score.txt           2.4KB scoring prompt template
│   ├── rubrics/
│   │   ├── govern.yaml             Sakina, all 6 Categories, 5 levels each
│   │   └── identify.yaml           Sakina, all 3 Categories
│   ├── sample_data/                Megha-authored stand-ins (Phase E), Sakina refines later
│   │   ├── govern_questions.json   8 sample interview questions, 4 priority Categories
│   │   └── northwind_preseed_govern.json  21 Northwind Q&A, all 6 Categories
│   ├── scripts/
│   │   └── preseed_govern.py       loads a PreseedRecord JSON file into sessions/{sid}/answers/
│   └── implementation_examples/    NIST Ex1/Ex2/... per Subcategory, all 6 Functions
│       ├── govern.yaml   (31 subs, 119 examples)
│       ├── identify.yaml (21, 74)
│       ├── protect.yaml  (22, 77)
│       ├── detect.yaml   (11, 37)
│       ├── respond.yaml  (13, 38)
│       └── recover.yaml  (8, 18)
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

### Megha ⏳ pending (in priority order)
1. Decide the aggregation formula (Category- vs Subcategory-weighted — see §8) and build `aggregate_function` for real — was Aug 18-19 in the plan, but we now have real data to build/test it against
2. Genericize the Govern agent shape for Identify/Protect/etc — the base class already supports it; just need `csf_specialists/agents/identify.py` and rubric YAML (Identify rubric already extracted; other 4 wait on Sakina)
3. Judge / report — Aug 18-25 in the plan
4. Deploy `csf_specialists` as its own Cloud Run service — Aug 22 in the plan

### Sakina ⏳ pending (ALL still owed; she's been catching up on rubrics only)
- **URGENT — confirm Northwind's actual regulatory jurisdiction.** `SANS-Security-Policy-Templates-main/10. Information_Security_Policy.docx` turned out to be real Northwind content (not a template) describing Northwind as UK dual-regulated (PRA/FCA). The locked demo persona says US-regulated (GLBA/NYDFS 500/PCI-DSS/SOX). One of these is wrong — needs resolving before the demo narrative locks further.
- Interview questions (all 6 Functions, ~8 each)
- Northwind Financial doc package (5-7 policies + org chart + asset inventory + risk register + IR log + vendor list) — was Sat 3 PM
- Golden test set v1 (Northwind + expert CMMI scores) — was Sat 6 PM
- **Evidence taxonomy v1** (doc_type → Category map) — was Fri 9 PM, **highest-leverage delivery** (unlocks `search_session(..., doc_type_filter=...)` for retrieval precision)
- Protect / Detect / Respond / Recover CMMI rubrics
- Recommendation templates keyed by (subcategory_id, transition) — due Wed Aug 19
- Executive summary templates (24 = 4 Tiers × 6 Functions) — due Fri Aug 21
- Northwind reg confirmation (GLBA/NYDFS/PCI/SOX)

---

## 8. Known gotchas from today (don't re-learn them)

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
- **Two different Function-aggregation formulas exist in the docs and disagree.** `lld.md §8.2`'s `aggregate_function` is Category-weighted (mean of the 6 Category `cmmi_level`s). The Aug 15 ad hoc "1.19" figure was Subcategory-weighted (all 31 Subs pooled). On real Phase F data these land on different Tiers (3 vs. 2) — not hypothetical. Pick one before building real aggregation code.

---

## 9. Useful test sessions (already in Firestore + Qdrant)

- `23a53272-6cd8-40b8-a363-f826eb76aa6d` — target_org `"Test1"` (not renamed — rename before demo use). **Best test session as of Phase F**: 3 real docs including the discovered Northwind-authored `Information_Security_Policy.docx` (not generic SANS), 21 preseed answers loaded, `runs/phaseF/scores/` has all 6 Govern Categories persisted. Supersedes `b8bc86d2-...` below for anything demo-quality.
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

**Step 4:** Phases E-G are all done. Two things are open, undecided as of this handoff:
1. **Aggregation formula decision** (§8) — Category-weighted vs. Subcategory-weighted, they disagree by a full Tier on real data.
2. **Fork: genericize to Identify agent, or build real `aggregate_function` code** — both are viable next steps; no decision made yet, see §7 pending list.

Also open with Sakina: the regulatory-jurisdiction conflict (§7 Sakina pending list) — needs her input, not something to resolve unilaterally.

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

> Read `docs/HANDOFF.md`. The Govern specialist agent build for the CSF Assessor Fleet hackathon (deadline Mon Aug 31) is fully done through Phase G — Phases A-F verified end-to-end on a real session (`23a53272-...`, real docs, persisted `run_id='phaseF'`, Tier 3 result matching the locked target). Two open items: (1) pick a Function-aggregation formula — `lld.md §8.2`'s Category-weighted method vs. the ad hoc Subcategory-weighted one, they disagree by a full Tier on real data (see §8) — and (2) decide the next build target: genericize to the Identify agent, or build real aggregation code now that we have data to test it against (see §7). Also flag to Sakina: found a real regulatory-jurisdiction conflict (UK PRA/FCA vs. the locked US-regs persona) in content she may have authored — needs her input before the demo narrative locks further.
