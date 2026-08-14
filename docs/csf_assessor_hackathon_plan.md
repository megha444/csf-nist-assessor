# CSF Assessor Fleet: 19-Day Hackathon Plan
**All Things Agentic Hackathon | Fortified Enterprise Fleet Track**
**Team: Megha (tech) + [Teammate name] (KPMG cybersec domain)**
**Timeline: Thu Aug 13 to Mon Aug 31, 2026 (submission 5 PM PDT / 8 PM ET Mon Aug 31)**
**Last updated: Thu Aug 13, 2026 (Category-scope amendment)**

---

## 0. Scope Amendment (Thu Aug 13, 2026)

After Day 1 architecture planning, one significant scope change was locked:

- **CMMI scoring is now per CSF Category (~22 total), NOT per Subcategory (~106).** Sakina's rubrics drop from ~500 cells to ~110 cells. Aggregation, agent scoring, report table, and Sakina's deliverables all rescale accordingly.
- Rationale: fits the 19-day timeline, preserves the two-layer story (Category CMMI → Function Tier), still produces defensible board-ready findings.
- The end-to-end system design is captured separately in `~/.claude/plans/now-lets-plan-the-mossy-glacier.md` and the day-to-day tracker in `task_list.md`. Section 8 below still references subcategory counts in some places — `task_list.md` is the working version.

---

## 1. Project Vision (one line for the demo)

*A multi-agent CSF 2.0 assessment fleet that replaces a $80K, 10-week Big 4 engagement with a $0.50, 15-minute run, without losing evidence-cited findings, defensible scoring, or the consultant's judgment.*

---

## 2. Success Criteria (what "done" means by Aug 31)

**Technical**
- 6 specialist agents (one per CSF 2.0 Function: Govern, Identify, Protect, Detect, Respond, Recover)
- Coordinator agent dispatching in parallel via Google ADK
- Adaptive interview flow (Level 1: conditional questions based on previous answers)
- Evidence extraction from uploaded policies with citations
- Two-layer scoring engine: CMMI 1-5 per **Category**, CSF Tier 1-4 per Function (aggregated from CMMI)
- Maturity report (executive summary, radar chart at Tier level, subcategory table at CMMI level, prioritized roadmap)
- Fortified track components: Agent Registry, Memory Bank, Agent Identity, Agent Gateway, Model Armor (or DLP fallback), Agent Observability
- Deployed on Google Cloud (Cloud Run + Firestore + Vertex AI)

**Submission artifacts**
- Hosted URL (or clear proof it was deployed)
- GitHub repo (public), clean README with reproducibility instructions
- Architecture diagram
- 4-minute demo video
- Bonus: 1 blog post + 1 LinkedIn post (both hashtagged #AllThingsAgenticHackathon)

**Quality bar**
- Golden test set eval: 80%+ CMMI level agreement (per Category) with teammate's expert scores
- Every score cites the source document passage
- Demo runs end-to-end without a crash

---

## 3. Tech Stack (locked)

| Layer | Tech | Notes |
|---|---|---|
| LLM | Gemini 3.5 Flash (primary), Gemini 3.5 Pro (coordinator + LLM-as-Judge only) | Via Vertex AI, not raw Gemini API |
| Agent framework | Google ADK (Python) | Mandatory hackathon requirement, best pattern support |
| Compute | Cloud Run (FastAPI app) | Scales to zero |
| Async orchestration | Pub/Sub | Enables parallel Function agent dispatch |
| State/Registry | Firestore | Agent metadata, assessment state, interview transcripts |
| Structured data | Cloud SQL (Postgres) | Scored subcategories, longitudinal history |
| Vector search | Vertex AI Vector Search (serverless) | Evidence retrieval over policy docs |
| Object storage | Cloud Storage | Raw uploaded PDFs/DOCXs |
| PII protection | Vertex Model Armor (fallback: Cloud DLP API) | Inline scrub before every LLM call |
| Identity | IAM service accounts + workload identity | One per agent |
| Observability | Cloud Trace + Cloud Logging (OpenTelemetry) | Reasoning chain per agent |
| Secrets | Secret Manager | API keys, rubric templates |
| UI | Streamlit | Fastest path to shippable UI in 19 days |
| Document parsing | pypdf + python-docx | Ingest layer |
| Charts | Plotly | Radar chart (Tier) + heatmap (CMMI) |
| Eval | pytest + deepeval | Golden set + LLM-as-Judge |
| Scoring model | CMMI 1-5 per **Category**, CSF Tier 1-4 per Function (aggregated) | Two-layer, matches KPMG standard practice |

**No fine-tuning.** Structured prompts with few-shot from teammate's golden set.

---

## 4. Division of Labor (locked, no crossover)

### Megha owns (technical)
Architecture, all code, ADK orchestration, ingestion, evidence extraction, scoring engine (uses her rubrics), report generation, UI, deploy, demo video production, README, architecture diagram.

### Teammate owns (domain)
CSF 2.0 rubrics (~22 Categories, CMMI 1-5 levels each ≈ 110 cells), CSF Tier aggregation ranges, interview question bank (~50 questions total), evidence taxonomy (what doc types satisfy what Categories), demo target company documents, golden test set, findings and recommendation language templates, executive summary tone, domain accuracy review after every phase.

**Rule:** She never writes Python. Megha never invents rubrics. Cross that line and the moat collapses.

---

## 5. Target Company Persona (LOCKED, do not change after Sat Aug 15)

**Name:** Northwind Financial
**Industry:** Financial services (banking and insurance group)
**Size:** ~1,500 employees
**Applicable regs:** GLBA, NYDFS 500 (confirm with teammate), state insurance regs, PCI-DSS, SOX (confirm public/private with teammate)

**Maturity profile (target output):**
- Govern: Tier 3
- Identify: Tier 2
- Protect: Tier 2
- Detect: Tier 3
- Respond: Tier 2
- Recover: Tier 2

**Hook gap for demo drill-down:** MFA not enforced on privileged accounts (maps to PR.AA-05). Universally understood, technically specific, has clear cheap remediation.

**Narrative pattern:** Strong governance and detection tooling, weak follow-through on response and recovery. Classic pattern of "they have policies and alarms but haven't invested in what happens after alarm fires."

---

## 6. Scoring Model (locked)

**Executive layer:** CSF Tier 1-4 per Function. Shown on radar chart, executive summary. Board-friendly.

**Control layer:** CMMI 1-5 per **Category** (~22 total). Shown in findings table, drill-downs. Practitioner-friendly.

**Aggregation rule (draft, teammate confirms Thu Aug 20):**
- Per Function: mean CMMI over its Categories
- CMMI avg 1.0-1.9 = Tier 1 (Partial)
- CMMI avg 2.0-2.9 = Tier 2 (Risk Informed)
- CMMI avg 3.0-3.9 = Tier 3 (Repeatable)
- CMMI avg 4.0-5.0 = Tier 4 (Adaptive)

**CMMI rubric template pattern** (teammate applies per Category):
- Level 1 Initial: No formal [thing]. Ad-hoc. Individual-dependent.
- Level 2 Managed: [Thing] exists in some BUs or projects. Inconsistent.
- Level 3 Defined: [Thing] is documented, org-wide, with named owner.
- Level 4 Quantitatively Managed: [Thing] measured against KPIs. Metrics tracked.
- Level 5 Optimizing: [Thing] continuously improved from metrics, threat intel, incidents.

---

## 7. Calendar Reference

```
Aug 2026
Mo Tu We Th Fr Sa Su
                1  2
 3  4  5  6  7  8  9
10 11 12 13 14 15 16   ← Aug 12 Wed = today, hackathon runs from Thu Aug 13
17 18 19 20 21 22 23
24 25 26 27 28 29 30
31                      ← Aug 31 Mon = submission day, 5 PM PDT / 8 PM ET
```

**Weekend deep-work days (teammate free from KPMG):** Sat Aug 15, Sun Aug 16, Sat Aug 22, Sun Aug 23, Sat Aug 29, Sun Aug 30.
**Sunday reviews:** Sun Aug 16 and Sun Aug 23, both 11:00 AM ET, both mandatory.
**Submission day (Mon Aug 31):** teammate at KPMG most of day. Submission target: 12 PM ET (8 hrs before 8 PM ET deadline).

---

## 8. Phase-by-Phase Plan (with explicit dates on every task)

Working assumption: ~3.5 hrs/day weekdays + ~9 hrs one weekend day per person. ~200 total person-hours across 19 days.

**Daily 15-min sync: 7 AM ET.** (Megha adjusts to local timezone.)
**Sunday 90-min review: 11:00 AM ET, both.**
**Shared Google Doc:** single source of truth for rubrics, prompts, eval set, demo script.

---

### PHASE 1: Foundation (Thu Aug 13 to Sat Aug 15), 3 days

**Goal:** Environment ready, first rubrics locked, ingest pipeline works, demo doc package received.

#### Thu Aug 13

**Megha**
- [by 10 AM ET Thu Aug 13] Both registered on Devpost, both Google Cloud credit forms submitted ($300 total buffer)
- [by 12 PM ET Thu Aug 13] Register for Aug 13 webinar (Long-Running Agents with ADK); attend live 12 PM ET or watch recording by EOD
- [by 3 PM ET Thu Aug 13] GCP project created, enable Vertex AI, Cloud Run, Firestore, Pub/Sub, Vector Search, Cloud SQL, Cloud Storage, Secret Manager
- [by 3 PM ET Thu Aug 13] Billing alerts set at $30, $60, $100, $140
- [by 6 PM ET Thu Aug 13] GitHub repo created (private for now), Python 3.11 + poetry/uv scaffolded
- [by 9 PM ET Thu Aug 13] ADK "hello world" agent running locally, deployed to Cloud Run

**Teammate**
- [by 12 PM ET Thu Aug 13] Read hackathon Fortified track requirements end to end
- [by 9 PM ET Thu Aug 13] Draft CMMI 1-5 rubric for **5 highest-priority Govern subcategories** using the L1-L5 template pattern (25 cells, 3-5 lines each)
- [by 9 PM ET Thu Aug 13] Draft 8 interview questions for Govern
- [by 9 PM ET Thu Aug 13] Confirm which regs apply to Northwind Financial (GLBA, NYDFS, PCI, SOX, state insurance) so demo narrative can reference them

**Sync deliverable:** Both share status in shared doc [by 9:30 PM ET Thu Aug 13].

#### Fri Aug 14

**Megha**
- [by 12 PM ET Fri Aug 14] Ingest pipeline: FastAPI endpoint accepts PDF/DOCX, chunks via section-aware splitter, stores raw in Cloud Storage, chunks + metadata in Firestore
- [by 6 PM ET Fri Aug 14] Vertex AI Vector Search index created, embedding pipeline running (text-embedding-004)
- [by 9 PM ET Fri Aug 14] Ingest tested with 3 SANS policy templates end to end

**Teammate**
- [by 9 PM ET Fri Aug 14] Complete CMMI rubric for remaining 5 Govern subcategories (25 cells) + finish 8 Govern interview questions
- [by 9 PM ET Fri Aug 14] Draft CMMI 1-5 rubric for 5 highest-priority Identify subcategories (25 cells)
- [by 9 PM ET Fri Aug 14] Draft 8 interview questions for Identify
- [by 9 PM ET Fri Aug 14] Evidence taxonomy v1: table mapping doc types to subcategories they satisfy

#### Sat Aug 15 (weekend, teammate has full day)

**Megha (~9 hrs)**
- [by 3 PM ET Sat Aug 15] First Govern agent stub in ADK, wired to Vertex AI + Vector Search + Firestore
- [by 3 PM ET Sat Aug 15] Structured output schema (Pydantic): `{subcategory_id, cmmi_level, confidence, evidence_citation, reasoning}`
- [by 9 PM ET Sat Aug 15] Govern agent runs on a single subcategory, returns valid structured output (quality not required yet)

**Teammate (~6 hrs, weekend allows deeper work)**
- [by 12 PM ET Sat Aug 15] Complete CMMI rubric for remaining 5 Identify subcategories (25 cells)
- [by 3 PM ET Sat Aug 15] Northwind Financial document package delivered:
  - 5-7 policies (Info Sec Policy, Access Control, Data Classification, Vuln Mgmt Standard, IR Plan intentionally weak, BCP, Vendor Risk Mgmt)
  - Org chart snippet (fake names): CISO, IT Director, Compliance Officer, 3 BU heads
  - Asset inventory sample (10-20 rows: server names, owners, classifications)
  - Risk register excerpt (5-10 risks: description, owner, treatment status)
  - Incident log entry (1 fake incident from 6 months ago)
  - Vendor list (10 vendors, criticality tier, last review date)
- [by 6 PM ET Sat Aug 15] Golden test set v1: 5 Northwind policies + her expert-assigned CMMI scores for 10 Govern subcategories (50 tuples)
- [by 9 PM ET Sat Aug 15] Review Megha's Govern agent output, flag every domain error in shared doc
- [by 9 PM ET Sat Aug 15] Start CMMI rubric for Protect (get 5 subcategories done, 25 cells, if time permits)

**Phase 1 gate (Sat EOD Aug 15):**
- [ ] GCP fully set up, credits active
- [ ] ADK hello-world deployed
- [ ] Ingest pipeline working end to end
- [ ] Govern + Identify CMMI rubrics locked (20 subcategories, 100 cells total)
- [ ] Interview questions locked for Govern + Identify (16 questions)
- [ ] Northwind Financial doc package received in full
- [ ] Golden test set v1 exists (50 tuples for Govern)
- [ ] Govern agent produces structured output (quality not required yet)

**If any of these is not met, adjust Phase 2 scope during Sunday review Aug 16.**

---

### PHASE 2: Vertical Slice (Sun Aug 16 to Fri Aug 21), 6 days

**Goal:** Full end-to-end assessment for Govern function alone. Upload, interview, agent runs, report generated. Ugly but functional.

#### Sun Aug 16 (weekend, deep work day)

**Sunday review (both, 11:00 AM to 12:30 PM ET)**
- What shipped, what slipped
- Rubric quality check by teammate on Megha's agent outputs so far
- Adjust Phase 2 plan if slippage detected

**Megha (~7 hrs after review)**
- [by 3 PM ET Sun Aug 16] Interview agent using ADK: conversational, asks questions from bank, stores answers in Firestore per assessment session
- [by 6 PM ET Sun Aug 16] Level 1 adaptive logic: LLM decides which questions to skip based on previous answers
- [by 8 PM ET Sun Aug 16] Session state persistence via Firestore, tested end to end
- [by 9 PM ET Sun Aug 16] Coordinator agent stub: routes to Govern only, publishes to Pub/Sub, subscribes to results

**Teammate (~5 hrs after review)**
- [by 6 PM ET Sun Aug 16] CMMI 1-5 rubric for 10 Protect subcategories (50 cells) + 8 interview questions
- [by 9 PM ET Sun Aug 16] Expand golden test set: 3 more Northwind policies scored across Govern + Identify (~80 tuples total)

#### Mon Aug 17 (teammate at KPMG, evening work only)

**Megha**
- [by 6 PM ET Mon Aug 17] Scoring engine: consumes agent outputs, aggregates CMMI per subcategory, computes Function-level average
- [by 9 PM ET Mon Aug 17] Basic report generator v1: JSON output listing scored subcategories with CMMI level, evidence citations, reasoning

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Mon Aug 17] CMMI 1-5 rubric for 5 Detect subcategories (25 cells, half of Detect)
- [by 10 PM ET Mon Aug 17] Review Govern agent scores against golden set, flag disagreements in shared doc

#### Tue Aug 18 (teammate at KPMG, evening work only)

**Megha**
- [by 6 PM ET Tue Aug 18] Report generator v2: HTML output via Jinja2 template, Plotly radar chart embedded
- [by 9 PM ET Tue Aug 18] Streamlit app v1: upload docs, chat interview, view report

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Tue Aug 18] Complete Detect rubric (remaining 5 subcategories, 25 cells) + 8 Detect interview questions

#### Wed Aug 19 (teammate at KPMG, evening work only)

**Megha**
- [by 6 PM ET Wed Aug 19] Templatize Govern agent config-driven so remaining Functions plug in via config
- [by 9 PM ET Wed Aug 19] LLM-as-Judge pass on Govern agent outputs (Gemini Pro grades CMMI defensibility)

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Wed Aug 19] CMMI rubric for Respond (10 subcategories, 50 cells) + 8 Respond interview questions
- [by 10 PM ET Wed Aug 19] Recommendation template: for each CMMI Level 1 or Level 2 finding, standard remediation language (30 templates)

#### Thu Aug 20 (teammate at KPMG, evening work only)

**Both attend Aug 20 webinar** (Self-Evolving Agents), 12 PM to 1:30 PM ET (both catch recording if KPMG blocks live).

**Megha**
- [by 6 PM ET Thu Aug 20] Confidence threshold logic: below 0.6, agent flags "insufficient evidence" instead of scoring
- [by 9 PM ET Thu Aug 20] Deploy Identify agent (config-based off Govern template)

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Thu Aug 20] CMMI rubric for Recover (10 subcategories, 50 cells) + 8 Recover interview questions (COMPLETES ALL 6 FUNCTIONS)
- [by 10 PM ET Thu Aug 20] Confirm CSF Tier aggregation ranges (CMMI avg to Tier mapping)

#### Fri Aug 21 (teammate at KPMG, evening work only)

**Megha**
- [by 3 PM ET Fri Aug 21] Vertical slice integration: upload docs, interview, Govern agent scores at CMMI, aggregates to Tier, LLM-as-Judge validates, report generated with radar chart
- [by 9 PM ET Fri Aug 21] Fix all breakages found during first end-to-end run

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Fri Aug 21] Executive summary language templates: one paragraph per Tier per Function (24 templates)
- [by 10 PM ET Fri Aug 21] Run vertical slice on Northwind docs, score Govern output herself, log disagreements

**Phase 2 gate (Fri EOD Aug 21):**
- [ ] Vertical slice: end-to-end Govern assessment works
- [ ] CMMI agreement rate with teammate ≥ 60% (targeting 80% by week 3)
- [ ] All 6 Function CMMI rubrics locked (60 subcategories, 300 cells)
- [ ] All 6 Function interview questions locked (~50 questions)
- [ ] CSF Tier aggregation ranges confirmed
- [ ] Executive summary templates ready
- [ ] Report renders with radar chart, CMMI table, evidence citations

**Slippage decision:** If Phase 2 gate fails, cut Fleet from 6 to 4 Functions (Govern + Identify + Protect + Detect). Drop Respond and Recover to Phase 5 stretch.

---

### PHASE 3: Fleet + Fortified Layer (Sat Aug 22 to Wed Aug 26), 5 days

**Goal:** All 6 Function agents live and parallel. Full Fortified track components integrated.

#### Sat Aug 22 (weekend, deep work day)

**Megha (~9 hrs)**
- [by 12 PM ET Sat Aug 22] Deploy Protect + Detect specialist agents (all 4 primary Functions live)
- [by 4 PM ET Sat Aug 22] Deploy Respond + Recover agents (all 6 live)
- [by 7 PM ET Sat Aug 22] Full parallel coordinator via Pub/Sub: dispatches to all 6 agents, waits for completion, aggregates
- [by 9 PM ET Sat Aug 22] Agent Registry in Firestore: publish each Function agent with metadata (name, version, capabilities, owner Function, IAM identity)

**Teammate (~5 hrs)**
- [by 3 PM ET Sat Aug 22] Review outputs from Identify, Protect, Detect on Northwind docs (from Fri deploys)
- [by 6 PM ET Sat Aug 22] Review outputs from Respond + Recover on Northwind docs
- [by 9 PM ET Sat Aug 22] Golden test set expansion to 100 tuples covering all 6 Functions

#### Sun Aug 23 (weekend, deep work day)

**Sunday review (both, 11:00 AM to 12:30 PM ET)**
- Vertical slice + full fleet running
- CMMI agreement rate on golden set (target ≥ 70% by end of Phase 3)
- Adjust Phase 4 scope based on gaps

**Megha (~6 hrs after review)**
- [by 3 PM ET Sun Aug 23] Agent Identity: IAM service account per agent, workload identity binding
- [by 6 PM ET Sun Aug 23] Memory Bank: per-assessment canonical target-org state in Firestore (or Vertex Memory Bank if API stable)
- [by 9 PM ET Sun Aug 23] Model Armor / Cloud DLP: PII scrubbing pipeline before any LLM call, log redactions

**Teammate (~4 hrs after review)**
- [by 6 PM ET Sun Aug 23] Draft demo script v1 (4 minutes, word-for-word)
- [by 9 PM ET Sun Aug 23] Pre-write 4 interview answers Northwind would give during the demo

#### Mon Aug 24 (teammate at KPMG, evening only)

**Megha**
- [by 6 PM ET Mon Aug 24] Agent Gateway: single FastAPI ingress that authenticates, rate-limits, routes to agents
- [by 9 PM ET Mon Aug 24] Agent Observability: OpenTelemetry spans per agent call, exported to Cloud Trace

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Mon Aug 24] Executive summary written for Northwind (3 paragraphs, sets tone the agent should match)

#### Tue Aug 25 (teammate at KPMG, evening only)

**Megha**
- [by 6 PM ET Tue Aug 25] Report generator v3: executive summary, Function-level radar chart (Tier), subcategory table (CMMI), prioritized roadmap (top 10 gaps)
- [by 9 PM ET Tue Aug 25] Cost dashboard: tokens used, cost per assessment, latency per agent

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Tue Aug 25] Findings, gaps, roadmap wording refinements based on latest agent outputs

#### Wed Aug 26 (teammate at KPMG, evening only)

**Megha**
- [by 9 PM ET Wed Aug 26] Final integration pass: full 6-agent fleet running end-to-end with all Fortified components live
- [by 9 PM ET Wed Aug 26] First automated golden test set eval run, log baseline scores

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Wed Aug 26] Full re-run of assessment on Northwind docs with all 6 agents, score every output, log disagreements

**Phase 3 gate (Wed EOD Aug 26):**
- [ ] All 6 Function agents deployed, running in parallel via coordinator
- [ ] Agent Registry, Memory Bank, Agent Identity, Agent Gateway, Model Armor (or DLP), Observability all working
- [ ] Report renders with executive summary, radar chart, CMMI table, roadmap
- [ ] CMMI agreement ≥ 70%

---

### PHASE 4: Polish + Eval (Thu Aug 27 to Sat Aug 29), 3 days

**Goal:** Fix everything the teammate flagged. Ship eval numbers. Polish UI + report.

#### Thu Aug 27 (teammate at KPMG, evening only)

**Both attend Aug 27 webinar** (Agent Memory), 12 PM to 1:30 PM ET (catch recording if KPMG blocks live).

**Megha**
- [by 6 PM ET Thu Aug 27] Fix top 10 domain errors teammate flagged
- [by 9 PM ET Thu Aug 27] Golden test set eval automated: report retrieval@5, CMMI agreement rate, confidence calibration numbers in README
- [by 9 PM ET Thu Aug 27] Prompt caching for repeated rubric context per Function agent

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Thu Aug 27] Draft LinkedIn post (both) and blog post outline
- [by 10 PM ET Thu Aug 27] Review polished report for tone, structure, wording

#### Fri Aug 28 (teammate at KPMG, evening only)

**Megha**
- [by 6 PM ET Fri Aug 28] UI polish: radar chart interactive, drill-down into reasoning chain, evidence citations clickable, cost + latency badge
- [by 9 PM ET Fri Aug 28] Architecture diagram (excalidraw or draw.io): Fortified components labeled (Registry, Runtime, Memory, Identity, Gateway, Model Armor, Observability)

**Teammate (evening ~2 hrs)**
- [by 10 PM ET Fri Aug 28] Blog post draft (domain angle): "How AI can compress a $80K CSF assessment into 15 minutes without losing rigor"

#### Sat Aug 29 (weekend, both available all day)

**Megha (~8 hrs)**
- [by 12 PM ET Sat Aug 29] Reproducibility check: clone fresh from repo, follow README, deploy from scratch. Fix every broken step.
- [by 4 PM ET Sat Aug 29] README polish: architecture diagram, spin-up instructions, tech stack, eval numbers, cost per assessment, limitations, future work
- [by 7 PM ET Sat Aug 29] Blog post draft (technical angle): "Multi-agent Fortified fleet on Google ADK, lessons learned"
- [by 9 PM ET Sat Aug 29] **Backup demo recording session:** Do a full 4-min take end-to-end. If it's good, use it. If not, tomorrow's the real take.

**Teammate (~6 hrs)**
- [by 2 PM ET Sat Aug 29] Practice demo script solo (out loud, 3 times)
- [by 5 PM ET Sat Aug 29] Full run-through of demo script on Zoom together (1 hr), refine
- [by 9 PM ET Sat Aug 29] Available for the backup recording session (Megha's evening slot)

**Phase 4 gate (Sat EOD Aug 29):**
- [ ] CMMI agreement ≥ 80% on golden set
- [ ] README complete, reproducible from clean clone
- [ ] Architecture diagram done
- [ ] Demo script rehearsed at least 3 times
- [ ] Both blog posts drafted
- [ ] At least one demo take recorded (backup)

---

### PHASE 5: Demo + Submit (Sun Aug 30 to Mon Aug 31), 2 days

**Critical constraint:** Mon Aug 31 is a KPMG workday for teammate. She's available evenings only. Do the heavy lifting Sunday.

#### Sun Aug 30 (weekend, both available all day)

**Megha**
- [by 11 AM ET Sun Aug 30] Review Sat backup take, decide if we need Take 2
- [by 1 PM ET Sun Aug 30] Record demo Take 2 (both on Zoom, OBS or Loom, split-screen of 6 agents in parallel = money shot)
- [by 3 PM ET Sun Aug 30] Review Take 2, note fixes for Take 3
- [by 5 PM ET Sun Aug 30] Record demo Take 3 if needed
- [by 8 PM ET Sun Aug 30] Edit final video (Descript or CapCut, 4 min, clear audio)
- [by 10 PM ET Sun Aug 30] Upload final video to YouTube (unlisted)

**Teammate**
- [available 11 AM to 8 PM ET Sun Aug 30] Present her portion during each take, review each cut, approve final
- [by 10 PM ET Sun Aug 30] Publish blog post on Medium
- [by 10 PM ET Sun Aug 30] Publish LinkedIn post with #AllThingsAgenticHackathon (Megha does the same)

#### Mon Aug 31 (teammate at KPMG most of day, submission target 12 PM ET)

**Megha (morning)**
- [by 9 AM ET Mon Aug 31] Final smoke test on deployed Cloud Run URL
- [by 9 AM ET Mon Aug 31] Ensure GitHub repo is public or shared with testing@devpost.com and cloudhackathons@google.com
- [by 10 AM ET Mon Aug 31] Publish own blog post on dev.to (technical angle)
- [by 11 AM ET Mon Aug 31] Fill out Devpost submission form draft (all fields, everything ready to submit)

**Both (submission window 11 AM to 12 PM ET Mon Aug 31, quick call to submit together)**
- Verify Devpost form:
  - Category: **Fortified Enterprise Fleet**
  - Also apply for: **Best Architectural Design**, **Startup Excellence** (if either has corporate email)
  - Hosted URL
  - Text description (features, tech, data sources, findings, learnings)
  - GitHub URL
  - Architecture diagram
  - 4-min demo video URL
- **Submit by 12 PM ET Mon Aug 31.** Absolute deadline is 8 PM ET (5 PM PDT). 8-hour buffer.

**Megha (afternoon, after submission confirmed)**
- Shut down non-essential Cloud services to preserve remaining credits
- Take screenshots of submitted state for records

---

## 9. Weekly Checkpoint Snapshot

| Date | Target State |
|---|---|
| Sun Aug 16 (Week 1 end) | Foundation done, Govern + Identify rubrics locked, ingest working, Northwind docs received, adaptive interview agent shipped |
| Sun Aug 23 (Week 2 end) | Vertical slice working, all 6 Function rubrics locked, full fleet + coordinator running, Fortified layer partially built |
| Mon Aug 31 (submission) | Submitted by 12 PM ET (8 hrs before deadline) |

If Sunday Aug 23 shows <60% of Phase 2 gate met, execute contingency: **drop from 6 to 4 Functions**. Hard rule.

---

## 10. Demo Script Structure (4 minutes, ~600 words spoken)

**0:00 to 0:30, Problem framing (Teammate)**
"CSF assessments at a Big 4 firm cost $80K and take 10 weeks. Every regulated company needs one. Northwind Financial, our demo target, is a 1,500-person banking and insurance group subject to GLBA and NYDFS 500. Most companies like them can't afford these assessments annually. I've done these engagements at KPMG. The process is repeatable. It's not the analysis that takes 10 weeks. It's the coordination."

**0:30 to 1:00, Solution framing (Megha)**
"We built a fleet of 6 specialist AI agents, one per CSF 2.0 Function, coordinated by a supervisor agent, running on Google Cloud with the Agent Development Kit. Each agent has its own memory, its own CMMI rubric, its own tools. Same rigor, 1/1000th the time and cost."

**1:00 to 3:00, Live demo**
- Upload Northwind's 7 documents
- Answer 3 pre-scripted interview questions (mention "system asks 30 in a full run")
- Split-screen: 6 agents working in parallel, each showing reasoning chain
- Click into Protect agent, show CMMI 2 score on PR.AA-05, show evidence citation
- Show final report: executive summary, radar chart (Tier), Category table (CMMI), prioritized roadmap
- Highlight the MFA gap with recommendation

**3:00 to 3:30, Architecture snapshot (Megha)**
- Diagram on screen: Cloud Run + Vertex AI + Firestore + Pub/Sub
- Fortified components labeled: Registry, Memory Bank, Agent Identity, Agent Gateway, Model Armor, Observability
- Show Cloud Run console live (proves deployment on GCP)
- Show cost per assessment: ~$0.47

**3:30 to 4:00, Impact + close (Teammate + Megha)**
- "$80K to $0.50. 10 weeks to 15 minutes. Same rubric. Cited evidence. Auditable."
- "We're not replacing consultants. We're compressing the mechanical layer so consultants can focus on the judgment layer."
- Close with GitHub link + hosted URL

---

## 11. Risk Register (with triggers and actions)

| # | Risk | Trigger | Action |
|---|---|---|---|
| 1 | Rubric bottleneck | Govern + Identify CMMI rubrics not locked by Sat Aug 15 EOD | Use public NIST Tier descriptions as fallback skeleton, teammate refines later |
| 2 | Evidence extraction quality | Retrieval@5 <70% by Fri Aug 21 | Add BM25 alongside dense, section-aware chunking, lower confidence threshold |
| 3 | Scoring inconsistency | Same input scored differently across 3 runs | Temperature 0.1, strict Pydantic schema, LLM-as-Judge second pass, few-shot from golden set |
| 4 | Demo docs look fake | Teammate rejects sample policy quality | Pull from SANS templates + CSA CAIQ + real anonymized examples from her past work |
| 5 | ADK learning curve | Coordinator + parallel dispatch not working by Sun Aug 23 | Fall back to sequential dispatch, note in README as tradeoff for hackathon timeline |
| 6 | Model Armor API unavailable | Blocked on access by Thu Aug 20 | Use Cloud DLP API as substitute, document choice in README |
| 7 | Cost blowout | Credits >$50 by Tue Aug 19 | Prompt caching for rubrics, max token caps 1500 Flash / 3000 Pro, scale-to-zero enforced |
| 8 | Video recording tanks | Bad take Sun Aug 30 | Backup recording Sat Aug 29 evening + 2 more Sunday takes = 3 shots total |
| 9 | Integration hell late | Rubric format doesn't match agent input format | Vertical slice by Fri Aug 21 forces early integration |
| 10 | Both burn out | Sunday Aug 16 review shows <40% progress | Cut scope aggressively, drop to 4 Functions, drop LLM-as-Judge, keep demo simple |
| 11 | Teammate KPMG workload spike | She misses a rubric deadline by more than 24 hrs | Megha uses public NIST + Claude to draft skeleton, teammate approves/edits within 12 hrs |
| 12 | Monday submission delay | Teammate can't join Mon Aug 31 12 PM ET submission call | Megha submits solo with pre-agreed form contents, teammate confirms async |

---

## 12. Submission Checklist (Mon Aug 31)

- [ ] Devpost submission form filled
- [ ] Category selected: Fortified Enterprise Fleet
- [ ] Also submitted for: Best Architectural Design, Startup Excellence (if applicable)
- [ ] Hosted URL live (or Cloud Console screenshots in demo prove it ran)
- [ ] GitHub URL live, README complete, reproducibility instructions tested
- [ ] Private repo shared with testing@devpost.com AND cloudhackathons@google.com
- [ ] Architecture diagram uploaded
- [ ] Demo video (4 min) uploaded to YouTube, link in submission
- [ ] Text description filled: features, tech, data sources, findings, learnings
- [ ] Bonus: 1 blog post published (Medium or dev.to) with hackathon language
- [ ] Bonus: 1 LinkedIn post published with #AllThingsAgenticHackathon
- [ ] Cloud services shut down post-recording to preserve credits

---

## 13. Post-Hackathon (Sep 1+)

If it wins or comes close:
- Flagship portfolio project on resume (all 3 versions)
- Blog series content for weekly LinkedIn posts (Month 5 of career plan)
- Talking point in FDE/Solutions Engineer interviews at security-focused AI companies (Wiz, Vanta, Drata, Snyk, Secureframe, CrowdStrike)
- Potential startup pitch if both interested
- Live demo at any interview loop

If it doesn't win, it still becomes all of the above minus the prize money.

---

*Plan created Wed Aug 12, 2026. Updated Wed Aug 12 with corrected day-of-week labels, Sunday reviews moved to actual Sundays (Aug 16, Aug 23), submission timeline adjusted for Mon Aug 31 KPMG workday constraint. Update this doc as reality changes. Sunday reviews mandatory.*
