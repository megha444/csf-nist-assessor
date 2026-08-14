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
- [ ] **[M]** follow-up — redeploy hello-agent under a clean service name (currently `adk-default-service-name` due to ADK CLI arg-parsing quirk swallowing `--service_name`); `gcloud run services delete adk-default-service-name --region=us-central1` then redeploy
- [ ] **[T]** by 12 PM ET — read hackathon Fortified track requirements end to end
- [ ] **[T]** by 9 PM ET — draft CMMI 1-5 rubric for 3 highest-priority Govern **Categories** (15 cells)
- [ ] **[T]** by 9 PM ET — draft 8 interview questions for Govern
- [ ] **[T]** by 9 PM ET — confirm which regs apply to Northwind (GLBA, NYDFS, PCI, SOX, state insurance)
- [ ] **[Both]** by 9:30 PM ET — status shared in shared doc

### Fri Aug 14
- [ ] **[M]** by 12 PM ET — ingest pipeline: FastAPI accepts PDF/DOCX, section-aware chunker, raw → Cloud Storage, chunks + metadata → Firestore
- [ ] **[M]** by 6 PM ET — Vertex AI Vector Search index created + embedding pipeline running (text-embedding-004)
- [ ] **[M]** by 9 PM ET — ingest tested with 3 SANS policy templates end to end
- [ ] **[T]** by 9 PM ET — complete CMMI rubric for remaining Govern Categories (~3 more, ~15 cells) + finish 8 Govern interview questions
- [ ] **[T]** by 9 PM ET — draft CMMI rubric for 3 highest-priority Identify Categories (~15 cells)
- [ ] **[T]** by 9 PM ET — draft 8 interview questions for Identify
- [ ] **[T]** by 9 PM ET — evidence taxonomy v1: table mapping doc types to Categories they satisfy

### Sat Aug 15 (weekend — deep work day)
- [ ] **[M]** by 3 PM ET — first Govern agent stub in ADK, wired to Vertex AI + Vector Search + Firestore
- [ ] **[M]** by 3 PM ET — Pydantic output schema: `{category_id, cmmi_level, confidence, evidence_citation, reasoning}`
- [ ] **[M]** by 9 PM ET — Govern agent runs on a single Category, returns valid structured output (quality not required yet)
- [ ] **[T]** by 12 PM ET — complete CMMI rubric for remaining Identify Categories
- [ ] **[T]** by 3 PM ET — Northwind Financial doc package delivered (5-7 policies, org chart, asset inventory, risk register, incident log, vendor list)
- [ ] **[T]** by 6 PM ET — golden test set v1 (5 Northwind policies + expert CMMI scores for all Govern Categories ≈ 30 tuples)
- [ ] **[T]** by 9 PM ET — review Megha's Govern agent output, flag every domain error in shared doc
- [ ] **[T]** by 9 PM ET — start Protect CMMI rubric (Categories, if time permits)

### Phase 1 Gate (Sat EOD Aug 15)
- [ ] GCP fully set up, credits active
- [ ] ADK hello-world deployed
- [ ] Ingest pipeline working end to end
- [ ] Govern + Identify CMMI rubrics locked (all Categories, ~40 cells)
- [ ] Interview questions locked for Govern + Identify (16 questions)
- [ ] Northwind Financial doc package received in full
- [ ] Golden test set v1 exists (~30 tuples for Govern)
- [ ] Govern agent produces structured output

---

## PHASE 2: Vertical Slice (Sun Aug 16 → Fri Aug 21)

### Sun Aug 16 (weekend — deep work day)
- [ ] **[Both]** 11:00 AM–12:30 PM ET — Sunday review: what shipped/slipped, rubric quality check, adjust Phase 2 plan
- [ ] **[M]** by 3 PM ET — interview agent using ADK: conversational, asks questions from bank, stores answers in Firestore per session
- [ ] **[M]** by 6 PM ET — Level 1 adaptive logic: LLM decides which questions to skip based on previous answers
- [ ] **[M]** by 8 PM ET — session state persistence via Firestore, tested end to end
- [ ] **[M]** by 9 PM ET — coordinator agent stub: routes to Govern only, publishes to Pub/Sub, subscribes to results
- [ ] **[T]** by 6 PM ET — CMMI rubric for all Protect Categories + 8 interview questions
- [ ] **[T]** by 9 PM ET — expand golden test set: 3 more Northwind policies scored across Govern + Identify (~50 tuples total)

### Mon Aug 17 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — scoring engine: consumes agent outputs, aggregates CMMI per Category, computes Function-level average
- [ ] **[M]** by 9 PM ET — report generator v1: JSON output listing scored Categories with CMMI level, evidence citations, reasoning
- [ ] **[T]** by 10 PM ET — CMMI rubric for half of Detect Categories
- [ ] **[T]** by 10 PM ET — review Govern agent scores against golden set, flag disagreements

### Tue Aug 18 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — report generator v2: HTML output via Jinja2, Plotly radar chart embedded
- [ ] **[M]** by 9 PM ET — Streamlit app v1: upload docs, chat interview, view report
- [ ] **[T]** by 10 PM ET — complete Detect Categories rubric + 8 Detect interview questions

### Wed Aug 19 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — templatize Govern agent config-driven so remaining Functions plug in via config
- [ ] **[M]** by 9 PM ET — LLM-as-Judge pass on Govern agent outputs (Gemini Pro grades CMMI defensibility)
- [ ] **[T]** by 10 PM ET — CMMI rubric for all Respond Categories + 8 Respond interview questions
- [ ] **[T]** by 10 PM ET — recommendation templates: 30 standard remediation templates for CMMI L1/L2 findings

### Thu Aug 20 (teammate: evening only)
- [ ] **[Both]** 12–1:30 PM ET — Aug 20 webinar (Self-Evolving Agents), live or recording
- [ ] **[M]** by 6 PM ET — confidence threshold logic: below 0.6, agent flags "insufficient evidence"
- [ ] **[M]** by 9 PM ET — deploy Identify agent (config-based off Govern template)
- [ ] **[T]** by 10 PM ET — CMMI rubric for all Recover Categories + 8 Recover interview questions **(COMPLETES ALL 6 FUNCTIONS)**
- [ ] **[T]** by 10 PM ET — confirm CSF Tier aggregation ranges (CMMI avg → Tier mapping)

### Fri Aug 21 (teammate: evening only)
- [ ] **[M]** by 3 PM ET — vertical slice integration: upload → interview → Govern scores CMMI → aggregates to Tier → LLM-as-Judge validates → report with radar
- [ ] **[M]** by 9 PM ET — fix all breakages found during first end-to-end run
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
- [ ] **[M]** by 9 PM ET — Agent Registry in Firestore: each agent publishes metadata (name, version, capabilities, owner Function, IAM identity)
- [ ] **[T]** by 3 PM ET — review outputs from Identify, Protect, Detect on Northwind docs
- [ ] **[T]** by 6 PM ET — review outputs from Respond + Recover on Northwind docs
- [ ] **[T]** by 9 PM ET — golden test set expansion to ~66 tuples covering all 22 Categories

### Sun Aug 23 (weekend — deep work day)
- [ ] **[Both]** 11:00 AM–12:30 PM ET — Sunday review: vertical slice + fleet running, CMMI agreement ≥ 70%?, adjust Phase 4
- [ ] **[M]** by 3 PM ET — Agent Identity: IAM service account per agent, workload identity binding
- [ ] **[M]** by 6 PM ET — Memory Bank: per-assessment canonical target-org state in Firestore (or Vertex Memory Bank if stable)
- [ ] **[M]** by 9 PM ET — Model Armor / Cloud DLP: PII scrub before every LLM call, log redactions
- [ ] **[T]** by 6 PM ET — draft demo script v1 (4 min, word-for-word)
- [ ] **[T]** by 9 PM ET — pre-write 4 interview answers Northwind would give during demo

### Mon Aug 24 (teammate: evening only)
- [ ] **[M]** by 6 PM ET — Agent Gateway: single FastAPI ingress that authenticates, rate-limits, routes to agents
- [ ] **[M]** by 9 PM ET — Agent Observability: OpenTelemetry spans per agent call, exported to Cloud Trace
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
