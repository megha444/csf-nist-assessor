# CSF Assessor Fleet

**A multi-agent NIST CSF 2.0 cybersecurity maturity assessment, run by six specialist agents on Google Cloud.**

Upload your security policies, answer a short interview, and get a board-ready maturity
assessment — evidence-cited, independently reviewed, and scored against the same rubric a
consultant would use.

🔗 **[Live app](https://csf-ui-jdogd2dq2q-uc.a.run.app)** · 🎥 **Demo video — _link to be added_** · 📄 **[Sample report (PDF)](docs/sample_report_northwind.pdf)**

Built for the **All Things Agentic Hackathon** · *Fortified Enterprise Fleet* track.

---

## The problem

A NIST CSF 2.0 maturity assessment from a Big 4 firm costs roughly **$80,000 and takes ~10
weeks**. It produces a defensible, evidence-cited report — and then goes stale, because nobody
pays for it twice a year.

This fleet does the same assessment in **~15 minutes for roughly $0.50 of model spend**, and is
cheap enough to re-run quarterly. It keeps the parts that made the engagement worth paying for:

- **Evidence citations** — every score points at the document that justifies it
- **Defensible scoring** — a CMMI 1–5 rubric per subcategory, not a vibe
- **Independent review** — a second model audits the first one's reasoning
- **Progress over time** — the next run knows what the last one found

---

## Trying it — what to expect, and how long

Real work is happening on real infrastructure, so this is not instant. **Measured timings from
production runs:**

| Step | How long | What you'll see |
|---|---|---|
| Upload a document | ~5–10s each | Per-document status flips to `ready` as ingest completes |
| Interview / questionnaire | a few minutes, your pace | — |
| **Run assessment** | **~10–14 minutes** | See the status sequence below |
| Report + PDF | a few seconds | Renders from Firestore |

When you press **Run assessment**, the status moves through:

```
pending  →  dispatched (0/6)  →  ready_for_report (6/6)
   ~10s        ~8-12 min             done
```

> **`dispatched · 0/6` for several minutes is normal — it is not stuck.** Six specialist agents
> are scoring 22 CSF Categories in parallel on Cloud Run Jobs, each retrieving evidence and
> calling Gemini. The counter only moves as each *Function* finishes and reports back, so it
> sits at `0/6` and then climbs quickly near the end. A cold start on the worker can add up to
> ~4 minutes on the first run of the day.

If you want to watch it work rather than wait: **Cloud Run → Jobs → `csf-worker` → Executions**
shows six executions appearing within a second or two of each other, and **Cloud Trace** shows
the scoring spans landing live.

---

## Measured against an expert

The fleet's scores were compared, blind, against a golden set authored by a cybersecurity
practitioner: CMMI scores for **all 106 NIST CSF 2.0 subcategories** on the same evidence the
agents saw. **The golden set ships in this repo**, so these numbers can be independently
re-derived.

| Level | Metric | Result |
|---|---|---|
| **Function / Tier** | agreement with the expert | **100% — 6 / 6 functions** |
| **Subcategory** | within ±1 CMMI level | **100%** (106 / 106) |
| Subcategory | exact match | 61.3% |
| Subcategory | mean absolute error | 0.39 |
| Evidence | cited the expert's primary document | 53.6% |

> **The fleet agrees with an expert on the maturity Tier for all six NIST CSF functions.**

**Read this honestly.** Tier agreement is the stable result — 6/6 on *every* run measured.
Exact-match moves a point or two between runs because the models are non-deterministic
(60.4–62.3% observed), so it is reported rather than headlined. CMMI scoring is judgement-based:
we publish exact match, within-±1 **and** mean absolute error so you can see the shape of the
disagreement, not just a flattering number.

📊 **[Full evaluation](docs/eval_results.md)** · 📗 **[Golden set](docs/Golden%20Set.xlsx)** · reproduce with
`python -m csf_specialists.scripts.eval_golden --session <SID> --run <RID>`

---

## Architecture

![System architecture](docs/architecture-system.svg)

A request flows through five tiers:

1. **`csf-ui`** (Cloud Run · Streamlit) — session, upload, interview, report
2. **`csf-gateway`** (Cloud Run · FastAPI) — API-key auth, rate limiting, Model Armor
   screening, document ingest. Returns a `run_id` immediately and never blocks
3. **`csf-coordinator`** (Vertex AI **Agent Engine**) — the orchestrator, running under a
   **native SPIFFE agent identity**: `CreateRun → Dispatch ×6 → CollectResults → Aggregate ×6
   → Judge ×6 → Narrative`
4. **`csf-worker`** (Cloud Run **Job**, 6 parallel executions) — one specialist per CSF
   Function, each retrieving evidence from Qdrant and scoring its Categories with Gemini
5. **Firestore** — the source of truth. Every tier writes here; the UI polls it

Orchestration runs on Agent Runtime; scoring fans out over Pub/Sub to Cloud Run Jobs. That
split is deliberate — a six-way batch fan-out belongs on Jobs, not on a runtime built for
long-lived conversational agents.

📐 **[Full architecture](docs/architecture.md)**

---

## What makes it different

**An independent Judge that caught a real bug in its own pipeline.** A second model
(`gemini-3.7-flash`) reviews every Category score for defensibility. It flagged a genuine,
reproducible internal inconsistency in the specialist's scoring — the numeric score didn't
match the written reasoning beside it. Not a staged demo: a real defect, found on real output.

**It tells you when to distrust it.** Findings below 60% self-rated confidence are flagged
*"insufficient evidence"* across all report surfaces, rather than presenting a weak score as a
strong one. *(Verified against synthetic low-confidence input; real runs cluster at 80–95%.)*

**It remembers your last assessment.** Cross-run history per organisation means the second
report says *"Govern improved from Tier 2 → Tier 3 since your last assessment"* and flags
whether previously-identified gaps were actually closed.

**Board-ready output, not a JSON dump.** A generated executive narrative plus PDF, HTML and
Excel exports — see the [sample report](docs/sample_report_northwind.pdf).

**Untrusted input is screened at all three tiers.** Google's Model Armor runs on the gateway
(interview answers, uploaded questionnaires), the worker (scoring prompts) and the coordinator
(judge and narrative prompts) — injection, jailbreak, malicious-URL and RAI screening, plus a
deterministic PII scrub.

---

## Fortified Enterprise Fleet — GEAP adoption

![Fortified component adoption](docs/architecture-fortified.svg)

| # | Component | Status | Where it lives |
|---|---|---|---|
| 1 | **Agent Runtime** | 🟢 native · live | Coordinator on Vertex AI Agent Engine — every assessment executes there |
| 2 | **Agent Identity** | 🟢 native · live | SPIFFE principal on the Coordinator, IAM-bound as `principal://` — plus three least-privilege service accounts |
| 3 | **Agent Registry** | 🟢 native · live | The Coordinator was **auto-registered by the platform**; specialists registered explicitly |
| 4 | **Model Armor** | 🟢 native · live | All three tiers |
| 5 | **Agent Observability** | 🟢 native · live | Custom `csf.*` spans + ADK's native `--otel_to_cloud` → Cloud Trace |
| 6 | **Agent Gateway** | 🟡 native · built + measured · **detached** | Egress mediation on a dedicated engine — see [limitations](#known-limitations-and-why) |
| 7 | **Memory Bank** | ⚪ reasoned decline | Hand-rolled cross-run Tier history — see [limitations](#known-limitations-and-why) |

---

## Quickstart

**Prerequisites:** Python 3.11, Poetry, a GCP project with Vertex AI enabled, and a Qdrant
Cloud cluster.

```bash
git clone <this-repo> && cd csf-nist
poetry install

cp .env.example .env          # fill in project, buckets, Qdrant URL + key, gateway API key
gcloud auth application-default login

# terminal 1 — API
poetry run uvicorn csf_gateway.app.main:app --port 8090

# terminal 2 — UI
GATEWAY_URL=http://localhost:8090 poetry run streamlit run csf_ui/app.py
```

Open http://localhost:8501, create a session, upload evidence, and run an assessment.

> Scoring dispatches to the `csf-worker` Cloud Run Job, so a local run still uses cloud
> Firestore, Pub/Sub, Qdrant and Vertex AI. "Local" means the gateway and UI run on your
> machine, not that the system runs offline. Timings match the deployed app — a full
> assessment is still ~10–14 minutes, and `dispatched · 0/6` for most of it is expected.

**If a run really is stuck**, the distinguishing check is: open **Cloud Run → Jobs →
`csf-worker` → Executions**. If all six show *Succeeded* but Firestore `scores` is still 0
after ~4 minutes, that is a genuine stall. Workers still running means it is simply in
progress. A stale Pub/Sub backlog from earlier testing is the usual culprit — clear it with:

```bash
for s in csf-results-sub csf-dispatch-{govern,identify,protect,detect,respond,recover}-sub; do
  gcloud pubsub subscriptions seek $s --time=$(date -u +%Y-%m-%dT%H:%M:%SZ); done
```

## Deploy

```bash
bash infra/setup_service_accounts.sh        # 3 least-privilege service accounts
bash infra/deploy_coordinator_engine.sh     # Coordinator → Vertex AI Agent Engine
bash infra/deploy_all.sh                    # gateway → worker → UI
poetry run python infra/register_agent_registry.py   # register the fleet in Agent Registry
```

## Verify it really runs on Google Cloud

```bash
bash infra/verify_deployment.sh             # read-only; safe to run any time
```

Reports live Cloud Run revisions and the identity each runs as, the Agent Engine and its
identity type, the least-privilege IAM split, Agent Registry contents, Pub/Sub topics,
Firestore data, and Cloud Trace spans.

Two console notes that trip people up:
- **Agent Engine → Sessions** shows nothing until you enter a user id — use **`csf-gateway`**
- **Agent Registry has no console page** without Gemini Enterprise. Use
  `GET /agents` on the gateway, which merges the native registry with our own metadata

---

## Known limitations, and why

Each of these is a decision with evidence behind it, not an omission.

**Agent Gateway is built and measured, but detached from the demo path.** It works: 50 of 50
inspected requests matched a specific registered destination, TLS-intercepted, authorised
against the SPIFFE agent identity, with default-deny demonstrated by its own failure mode. It
was detached after measuring a **~305s ceiling on gateway-mediated runs against a 590s
unmediated control run** that completed fully. The measurement is solid; the underlying
*mechanism* was not isolated, and we don't claim it was. Re-attaching is one environment
variable.

**Memory Bank is hand-rolled, deliberately.** Native `agentengine://` memory is ADK
session/conversational memory — a different data model from cross-run maturity-Tier history.
Adopting it would have removed the "improved since your last assessment" capability, not added
to it.

**Agent Registry has zero bindings, and that is correct.** `bindings.create` requires an
`auth_provider` — a Binding models OAuth credential delegation. Our Coordinator dispatches over
Pub/Sub under its own identity; there is no delegated credential to model.

**Certificate token-binding is disabled on the agent identity.** With Google's default policy
on, every Firestore call failed `401`. A probe tested four paths independently: Firestore
rejected bound tokens over sync gRPC, async gRPC **and** plain HTTPS REST, while Pub/Sub
accepted them — a service-side gap, not a transport issue. Google's documentation names this
opt-out as the remedy for exactly this error. The cost: a leaked token becomes replayable. What
is retained: per-agent identity, no impersonation, no long-lived keys.

**The six specialists are not on Agent Runtime.** A six-way parallel fan-out of short batch
jobs suits Cloud Run Jobs. It is also why they cannot hold an agent identity — Agent Identity
is supported only on Agent Runtime and Gemini Enterprise.

**Network-layer auth is app-level.** Both Cloud Run services are deployed
`--allow-unauthenticated`; enforcement is `X-API-Key` plus per-instance rate limiting. The rate
limiter does not share state across replicas.

**Accuracy is validated, not benchmarked.** One organisation, one expert practitioner.
Evidence-doc precision (53.6%) measures citing the *specific* document the expert named — a miss
is often a different valid document supporting the same finding. The fleet also scores the
`ID.RA-*` / `ID.AM-*` cluster consistently one level above the expert; we deliberately did not
tune that away, because with Tier agreement already at 6/6 it would mean overfitting to a
single practitioner's judgement.

---

## Repo map

| Path | What it is |
|---|---|
| `csf_gateway/` | FastAPI service — sessions, ingest, interview, runs, Model Armor, Agent Registry endpoint |
| `csf_coordinator/` | Orchestration steps and Pub/Sub client |
| `coordinator_engine/` | Agent Runtime entry point (the `root_agent` adapter) |
| `csf_specialists/` | The six scoring agents, rubrics, judge, narrative, exports, eval harness |
| `csf_ui/` | Streamlit application |
| `infra/` | Deploy, IAM, Agent Registry / Agent Gateway provisioning, verification |
| `docs/` | Architecture, evaluation results, golden set, sample report |

**Tech:** Google ADK · Vertex AI Agent Engine · Gemini 3.5/3.7 Flash · Cloud Run (services +
Jobs) · Pub/Sub · Firestore · Cloud Storage · Model Armor · Agent Registry · Agent Identity ·
Cloud Trace · Qdrant Cloud · FastAPI · Streamlit
