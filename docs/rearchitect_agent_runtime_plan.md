# Re-architecture Exploration Plan — Agent Runtime + Gateway + Identity

**Living doc. Update the Status Tracker (§8) every session. When in doubt, re-read §0 (the decision this is testing) and §6 (the guardrails) before doing anything.**

Created: 2026-08-25 (Tue) · Branch: `fork/rearchitect-explore` · Owner: Megha

---

## 0. What this is, in one paragraph

We have a **fully working** NIST CSF assessment fleet on the current stack (Pub/Sub dispatch + Cloud Run Jobs + hand-rolled Registry/Memory Bank/Gateway). The hackathon's *Fortified* track recommends 7 named Gemini Enterprise Agent Platform (GEAP) components. Three of them — **Agent Runtime, Agent Gateway, Agent Identity** — are confirmed (first-party docs, §2) to only work for agents **hosted on Agent Runtime**. This exploration tests one specific hypothesis: **can we host just the Coordinator on Agent Runtime, unlock the GEAP-native components around it, and leave the specialist/Pub/Sub layer untouched** — cheaply, reversibly, and in time. This is a *spike with hard go/no-go gates*, not a commitment to migrate. The working system on `feat/ingest-pipeline` is never touched.

**We migrate only if the gates in §4 pass. We abort the moment one fails. That discipline is the whole point of this doc.**

---

## 1. Stakes & clock (do not drift on these)

- **Hard deadline:** Mon 2026-08-31, 8:00 PM ET. Soft target: 12:00 PM ET same day.
- **Our own code freeze:** Sat 2026-08-29. Everything after is submission polish + demo recording only.
- **Today:** Tue 2026-08-25. That leaves **~4 working days to freeze.**
- **Judging weights:** Innovation & Operational Utility **40%** · Architectural Discipline & Tech Stack **30%** · Demo & Production Readiness **30%**.
- **Why this matters, honestly:** GEAP-native adoption can only lift the 30% Architecture bucket. It cannot fix the 40% Innovation bucket (that's gated on Sakina's golden set / interview questions, not our infra). So this exploration is a bet on the *Architecture* score and the *"reads as real platform adoption at a glance"* judge-perception risk — worth doing **only** if it stays cheap and doesn't cannibalize the working demo.

---

## 2. Confirmed facts — do NOT re-research these

All fetched from first-party docs on 2026-08-25. Settled. Don't spend time re-litigating.

| # | Fact | Source |
|---|------|--------|
| F1 | Agent Gateway supports **only** Agent Runtime (ingress + egress) and Gemini Enterprise (egress only). **No arbitrary Cloud Run path.** | Agent Gateway overview |
| F2 | Agent Identity supported services are **exactly** Agent Runtime + Gemini Enterprise. No Cloud Run, no documented workload-federation workaround. | Agent Identity overview |
| F3 | Agent Gateway supports **all HTTP-based traffic incl. MCP + A2A**; parses request data for MCP only. | Agent Gateway overview |
| F4 | Agent Registry: "Your agents, and any endpoints, servers, or tools you want to connect to, must all be registered." (No field-level detail in docs — empirical.) | Agent Gateway overview |
| F5 | **Rate limiting is NOT a documented Gateway capability.** We keep our hand-rolled limiter regardless of which option wins. | Agent Gateway overview |
| F6 | ADK agents deploy to Agent Runtime via `adk deploy agent_engine` (managed template path), *not* the custom-container runtime contract. | Agent Runtime docs |
| F7 | `adk deploy agent_engine` (v2.6.3, confirmed locally) supports: `--extra_packages` (multi-package projects), `--trigger_sources pubsub,eventarc` (event-driven `/trigger/*` endpoints), `--session_service_uri agentengine://` , `--memory_service_uri agentengine://` (**= the real Memory Bank product**), `--otel_to_cloud` (**= Agent Observability**). | `adk deploy agent_engine --help` |

**Implication of F1/F2:** there is no "surgical adoption without hosting." To get Gateway/Identity you MUST host at least one agent on Agent Runtime. The hypothesis is that hosting *one* (the Coordinator) is enough.

**Bonus upside (F7):** if the Coordinator lands on Agent Runtime, `--memory_service_uri agentengine://` and `--otel_to_cloud` give us the *named* Memory Bank + Observability products almost for free — turning "hand-rolled equivalents" into "literal GEAP components" for 4 of the 7, not just the 3 we came for.

---

## 3. Current environment snapshot (verified 2026-08-25)

- **ADK:** `adk, version 2.6.3` (local, via poetry).
- **gcloud:** project `csf-assessor-hackathon`, account `meghaappdev@gmail.com`, region `us-central1`.
- **Enabled APIs (relevant):** `aiplatform.googleapis.com`, `run.googleapis.com`. **Not yet confirmed enabled:** whatever Agent Engine / reasoningEngines requires — smoke test will surface this.
- **Region tension to watch:** `.env` sets `GOOGLE_CLOUD_LOCATION=global` because **Gemini 3.x isn't served regionally on this project** (documented gotcha in HANDOFF.md §6). Agent Engine deploys to a real region (`us-central1`). **Open question G1:** can an Agent-Engine-hosted agent in `us-central1` still call Gemini 3.x via `global`? Must verify — this could force a model-region rethink.
- **Coordinator shape:** `csf_coordinator/coordinator.py::run_assessment(session_id, functions=None, run_id=None)` is an **async factory** — it builds a new `SequentialAgent` per call from runtime params. There is **no static `root_agent`** today. Agent Engine needs one. → adaptation work in Step 3.

---

## 4. The gated plan (each gate is a real stop point)

> **Rule:** you may not proceed past a gate until its exit criterion is met with *real verification* (an actual call/response, a persisted Firestore doc — not "no exception"). If a gate fails, go to §7 (Abort).

### Step 0 — Prep (15 min) · Gate 0
- [ ] Confirm branch is `fork/rearchitect-explore`, tree clean.
- [ ] Create a throwaway probe dir `spike/probe_agent/` with a trivial `root_agent` (a bare `LlmAgent` with one dummy tool, or an echo). **No real project code.**
- [ ] Decide the deploy target region (default `us-central1`) and write it here: `______`.
- **Exit Gate 0:** probe agent imports & runs locally via `adk run spike/probe_agent`.

### Step 1 — Trivial deploy smoke test (30–45 min) · Gate 1 ⭐ HARD GATE
Isolates "does the tooling + project + quota even work" from "does our architecture fit."
- [ ] `adk deploy agent_engine --project=csf-assessor-hackathon --region=<region> --display_name=probe spike/probe_agent`
- [ ] Whatever API it demands be enabled → enable it, note it in §8.
- [ ] Call the deployed probe once (via the returned resource / SDK), confirm a real response.
- [ ] Resolve **G1** (region/global model reachability): make the probe's agent actually invoke `gemini-3.5-flash` once and confirm it returns.
- **Exit Gate 1:** probe deployed + returned a real response + a Gemini 3.x call succeeded from inside it.
- **FAIL Gate 1** (permissions / quota / API allowlist / region-model conflict unresolvable) → **STOP. Revert to Option A.** Cost so far: <1 hr. This is a totally acceptable outcome.

### Step 2 — Test the two real unknowns (1–2 hrs) · Gate 2 ⭐ THE DECISION POINT
These are the things no amount of doc-reading can answer. Use **throwaway** topics/resources, never the real `csf-dispatch-*` topics.
- [ ] **U1 — async / background survival.** Redeploy probe with `--trigger_sources=pubsub` on a *test* topic. Fire an event that kicks off a deliberately slow (~60–120s) task. Confirm it **completes** (writes a marker to Firestore/GCS at the end), i.e. the runtime didn't kill background work after the initial response. This is the pattern our real run-and-poll depends on.
- [ ] **U2 — egress freedom.** Give the probe's tool one real outbound call using the **same client libs `DispatchStep` uses** — e.g. publish to a test Pub/Sub topic OR trigger the actual `csf-worker` Cloud Run Job. Observe: does it succeed, or is it blocked pending Agent Registry registration?
  - If blocked → register that one destination in Agent Registry, retry. Note effort. (Extra config = fine. Fundamentally-can't = fail.)
- **Exit Gate 2:** U1 completes a background task past the response AND U2 makes a real outbound call (directly or after simple registration).
- **FAIL Gate 2** (background work killed, OR egress fundamentally unworkable) → **STOP. Revert to Option A.** Cost: ~half a day. Document *why* in §8 — that failure reason is itself a strong judge-Q&A answer ("we tested it empirically and here's the hard constraint").

### Step 3 — Deploy the real Coordinator (½ day) · Gate 3
Only if Gate 2 passed.
- [ ] Write the **root-agent adapter**: a static `root_agent` wrapper that receives `session_id`/`functions` from the incoming message (or trigger payload) and invokes the existing `run_assessment` factory. (This is the §3 adaptation — the one non-trivial code change.)
- [ ] Deploy: `adk deploy agent_engine ... --extra_packages csf_specialists --extra_packages csf_gateway ... --otel_to_cloud` to a **NEW** Agent Engine resource. Watch for import/dependency-staging failures (`--extra_packages` name-shadowing caveat).
- [ ] Run ONE real end-to-end assessment through the hosted Coordinator against a known multi-Function test session (**`f56a9039-...`**, Govern+Identify) — specialists still consume via existing Pub/Sub / Cloud Run Jobs, untouched.
- **Exit Gate 3:** real persisted Firestore output (scores + tiers + judge verdicts) from a run driven by the Agent-Engine-hosted Coordinator. Same verification bar we always hold.
- **FAIL Gate 3** → assess: is it a small fix or a rabbit hole? Time-box the fix to **half a day max**. If not closed by then → **STOP. Revert to Option A.**

### Step 4 — Layer the GEAP components (½–1 day) · Gate 4
Only if Gate 3 passed. Each sub-item is independently valuable — bank them as they land.
- [ ] **Agent Identity** — confirm the hosted Coordinator has its auto-assigned SPIFFE identity; use it for at least one downstream auth instead of the shared SA.
- [ ] **Agent Gateway (ingress)** — front the Coordinator so client→agent traffic is Gateway-mediated. (Keep our rate limiter — F5.)
- [ ] **Memory Bank (real)** — repoint via `--memory_service_uri agentengine://` if it cleanly replaces the hand-rolled `orgs/{org}/memory/{fn}`. If not clean, keep hand-rolled; don't force it.
- [ ] **Observability (real)** — `--otel_to_cloud` on; confirm spans land.
- **Exit Gate 4:** each adopted component demonstrably works in a real run. Update the Fortified-components table in HANDOFF.md §7.9.

### Step 5 — Freeze decision (Sat 2026-08-29) · Gate 5 ⭐ MANDATORY STOP
- [ ] Whatever state we're in on Sat, **decide**: ship the migrated stack OR ship Option A. Both are demo-ready by construction (Option A never broke; migrated only ships if its gates passed).
- [ ] No new migration work after this date. Only demo polish.

---

## 5. Definition of "success" for this exploration

Not "we migrated." Success is **reaching a confident decision cheaply**:
- **Best case:** Gates 1–4 pass → we ship a stack using Agent Runtime + Gateway + Identity (+ maybe real Memory Bank + Observability), a genuinely stronger Architecture-score story.
- **Equally valid case:** a gate fails → we ship Option A, and we have a *docs-cited, empirically-tested* answer for why the GEAP-native path doesn't fit our deployment model. That is itself a 30%-Architecture-bucket asset (informed choice > cargo-culting names).
- **Only real failure mode:** letting sunk cost drag us past a failed gate, or letting this touch/break the working demo. §6 exists to prevent exactly that.

---

## 6. Guardrails (read before every work session)

1. **Never touch the working system.** `feat/ingest-pipeline` and the deployed `csf-gateway` service stay live and demo-able the entire time. All spike work is on `fork/rearchitect-explore`, all deploy targets are **new** resources.
2. **Gates are real.** No proceeding on a failed/unmet gate. No "we're close, one more hour" past a stop point without writing down *why* in §8 first.
3. **Time-box every gate.** Written estimates in §4 are ceilings, not targets. Blow the ceiling → abort that step.
4. **Throwaway resources for Steps 1–2.** Never point the probe at real `csf-dispatch-*` topics or the real gateway.
5. **Verify for real.** A persisted Firestore doc / an actual response — never "the command exited 0."
6. **Sat 2026-08-29 is a hard stop** for migration work regardless of progress.
7. **The 40% Innovation bucket is not helped by any of this.** If Sakina's golden set / interview questions land, *that* work outranks this. This exploration yields to it.

---

## 7. Abort procedure (cheap by design)

If any gate fails or the freeze hits mid-migration:
1. Stop migration work. Write the failure reason + evidence in §8 (it's demo/Q&A ammo).
2. `git checkout feat/ingest-pipeline` — the working system is exactly as it was.
3. Delete any throwaway Agent Engine resources to avoid idle cost.
4. Fold the empirical finding into `docs/presentation_pointers.md` as the "we tested GEAP-native adoption and here's what we learned" narrative.
5. Resume the Option-A remaining work: Agent Identity (per-fn SA), Model Armor spike, report/exec-summary polish, README + diagram, repro pass, backup demo recording.

**Aborting is not failure. Aborting late is.**

---

## 8. Status tracker — UPDATE EVERY SESSION

| Date | Gate | Status | Evidence / notes / decision |
|------|------|--------|------------------------------|
| 2026-08-25 | Plan | ✅ written | This doc created on `fork/rearchitect-explore`. Env verified: ADK 2.6.3, project `csf-assessor-hackathon`, region `us-central1`, `aiplatform`+`run` APIs on. Coordinator confirmed to be a factory fn (no static root_agent) → adapter needed in Step 3. |
| 2026-08-25 | Gate 0 | ✅ PASS | Built throwaway `spike/probe_agent/` (standalone, no csf_* imports) + `spike/run_probe_local.py`. Ran locally through real ADK Runner: model called the tool, echoed `marker=gate0-live`, reached `gemini-3.5-flash` via Vertex with `GOOGLE_CLOUD_LOCATION=global`. Tool-calling + Gemini 3.x both work locally. |
| 2026-08-25 | Gate 1 | ✅ PASS | Deployed via `adk deploy agent_engine --project=csf-assessor-hackathon --region=us-central1 spike/probe_agent` (exit 0, ~5 min build). **Reasoning engine:** `projects/220244569524/locations/us-central1/reasoningEngines/634309907331416064` (delete on abort — §7). Called it via `spike/call_probe_remote.py`: deployed agent responded, made a real tool call, and **`gemini-3.5-flash` returned normally**. No quota/allowlist friction on this project. **G1 RESOLVED FAVORABLY:** the deploy-log "ignoring GOOGLE_CLOUD_LOCATION" only governs *where the engine resource lives* (us-central1); the container runtime DID get `GOOGLE_CLOUD_LOCATION=global` from `.env` (confirmed — the probe's tool read it back as `global` from inside the deployed container) and Gemini 3.x was reachable. **Deploy-region and model-call-location are independent** — no model-region rethink needed. |
| 2026-08-25 | Gate 2 | ✅ PASS (core) | Redeployed probe in place with 3 dependency-free tools; driver `spike/call_probe_gate2.py`. **U1 (long invocation): PASS** — a 90s `slow_task` ran fully to `COMPLETED_TO_END` (~100s wall-clock), sync `stream_query` connection held the whole time. Implication: a single synchronous Agent Engine invocation runs long → **the fire-and-forget pattern may be unnecessary** (it was only a Cloud Run CPU-throttling workaround). **U2 (egress): NOT blocked — plain IAM gap.** Hosted agent REACHED `run.googleapis.com` and got HTTP **403** (`run.jobs.list denied`), not a connection error → **no egress lockdown to Agent-Registry-registered destinations; egress is open like any GCP compute.** **Runtime SA = `service-220244569524@gcp-sa-aiplatform-re.iam.gserviceaccount.com`** (Google-managed RE service agent), initially had only `roles/aiplatform.reasoningEngineServiceAgent`. Granted it `roles/run.developer` (exactly what `DispatchStep.run_job` needs). ⚠️ **Step-3 IAM note:** this SA also needs `roles/pubsub.publisher`, `roles/pubsub.subscriber`, `roles/datastore.user` for the real Coordinator — those are bound to OTHER SAs today, not this one. **CONFIRMED post-grant:** egress_check returned **HTTP 200 / EGRESS_OK_AUTHORIZED** and listed the real Job (`jobs_seen: ["csf-worker"]`) — the hosted agent can now reach the exact resource `DispatchStep` triggers. U1 re-run at **180s held to COMPLETED_TO_END** (187s wall-clock). **Residual open item (minor):** real runs can hit ~4 min; sync stream proven to 180s, not yet 240–300s — Step 3's real run will exercise true duration, and `--trigger_sources`/background-poll is the documented fallback if a sync ceiling appears. **Verdict: the "Coordinator on Agent Runtime, specialists+Pub/Sub untouched" architecture is empirically viable.** |
| 2026-08-25 | Gate 3 | 🟡 in progress | Built adapter `coordinator_engine/` (agent.py = `CoordinatorEntryAgent(BaseAgent)` parsing `session=…/functions=…` from `ctx.user_content` → awaits existing `run_assessment`; +`.env`, `requirements.txt`). Granted runtime SA the 3 remaining roles (pubsub.publisher/subscriber, datastore.user) — now has all 5. **G2 RESOLVED:** multi-package deploy (`--extra_packages csf_coordinator csf_specialists csf_gateway` + full requirements) built clean (exit 0) → new resource `…/reasoningEngines/4356534999353131008`. **First invoke FAILED — real lesson:** container crashed at import (`create_session` → FAILED_PRECONDITION / Internal Server Error; Cloud Logging showed `importlib.import_module` failing). Root cause: `from csf_specialists.agents import AGENTS` pulls `agent_base` → `csf_gateway.app.ingest.vector_store` → `qdrant_client`, which I'd omitted from requirements (local test passed only because laptop has it). Fix: added `qdrant-client==1.16.2` + `python-dotenv==1.2.2`; redeploying in place. **Lesson: a local import test can't catch a missing container dep — the deployed container has only what requirements.txt lists.** Two more container-only bugs found on the next invoke (both fixed in `coordinator_engine/agent.py`): (A) events yielded into Agent Engine's MANAGED session service need `invocation_id=ctx.invocation_id` (the steps' own InMemory service is lenient; managed 400s without it); (B) Agent Runtime forces `GOOGLE_CLOUD_PROJECT` to the project NUMBER → Firestore 404s ("database (default) does not exist for project 220244569524") → force the canonical project ID in the adapter before any csf_* import. **✅ GATE 3 PASS (run `82f8a7ab-…`, session `f56a9039-…`, govern+identify):** hosted Coordinator wrote Firestore, published Pub/Sub, triggered `csf-worker` Jobs, collected, aggregated, judged — **verified in Firestore: status=ready_for_report, 2/2 agents, 9 scores, 2 tiers, 9 judge verdicts.** **Sync invocation held 321s (5m21s) → resolves the Gate-2 residual: no fire-and-forget/trigger_sources needed.** Two reasoning engines now exist: real `csf-coordinator` (`4356534999353131008`) + throwaway probe (`634309907331416064`, safe to delete). |
| 2026-08-25 | **PAUSE** | ⏸️ decided | After Gate 3 PASS, Megha chose to **pause & assess** rather than proceed to Gate 4 — viability is proven and documented; decision on whether to finish Gate 4 vs. redirect remaining days to the 40% Innovation bucket / demo polish is deferred. Throwaway probe engine `634309907331416064` **deleted**. Kept: real `csf-coordinator` engine `4356534999353131008`, the runtime SA's 5 IAM roles, `coordinator_engine/` code (uncommitted, on `fork/rearchitect-explore`). Working system on `feat/ingest-pipeline` untouched throughout. |
| 2026-08-26 | Gate 3 robustness | ✅ FIXED | Megha's own re-run exposed that Gate 3's earlier PASS was **cold-start only**: the container stays warm and each invocation gets a FRESH event loop, but 4 modules (`steps`, `aggregate`, `memory_bank`, `judge`) cache a Firestore `AsyncClient` (+ judge an ADK Runner) in a module global bound to the first loop → 2nd invocation died at 0.8s with `RuntimeError: Event loop is closed`. Fix (isolated to `coordinator_engine/agent.py::_reset_stale_clients`, touches no shared code): null those cached globals at the start of each invocation so they rebind to the current loop. **Confirmed with TWO consecutive runs on the warm container:** run1 `ea0ec8a0` (275s) + run2 `fc0afd37` (302s), each 9 scores / 2 tiers / 9 judge, both PASS. Lesson added: always exercise a warm-container repeat invocation, not just a single cold run. |
| 2026-08-26 | Gate 4 | ✅ CLOSED (3 native + 1 deferred) | **Observability — native, VERIFIED 2026-08-26:** deployed with `--otel_to_cloud`; granted the RE SA `roles/cloudtrace.agent` (it was missing, same silent-export gap as the gateway SA per HANDOFF §9). **Confirmed working:** a post-grant run (`efe65fe2`) produced 9 traces with our custom spans (`csf.coordinator.{create_run,dispatch,collect_results,aggregate,memory_bank_write,judge}` + `csf.specialist.{score_category,judge_category}`) AND ADK's native OTLP spans (`invocation`/`invoke_agent`/`call_llm`/`generate_content`) all landing — verified via the Trace v1 API, not just the console. Also added coordinator plumbing spans this day (`steps.py`) so orchestration is traced end-to-end, not just LLM ops. **Agent Identity — native:** the hosted Coordinator runs under its own Agent-Runtime-assigned managed identity (`service-220244569524@gcp-sa-aiplatform-re.iam`), scoped to least-privilege IAM (6 roles), instead of the shared `csf-gateway` SA — that IS the Agent Identity story (auto-assigned per-agent identity + our scoping). **Memory Bank (native) — evaluated & DECLINED (G3 resolved):** `--memory_service_uri agentengine://` is ADK *session/conversational* memory, a different data model than our report-visible cross-run Tier/gap tracking (confirmed against Google's own Memory Bank definition, task_list Aug 24); it wouldn't replace our feature and the pipeline doesn't use ADK's memory API → keep hand-rolled. **Agent Gateway ingress — DEFERRED:** the one heavy item (VPC + Gateway resource + IAP + destination registration, 2–4+ hrs, least demo-visible); scoped out under timeline, documented as an informed call. **Net: the migration now delivers Agent Runtime + Agent Identity + native Observability as literally-native GEAP components, plus a documented, docs-cited decision on Gateway-ingress and native Memory Bank.** |
| | Gate 5 | ⬜ not started | |

### Open questions to resolve empirically (not by more reading)
- **G1** — Can an Agent-Engine agent in `us-central1` reach Gemini 3.x via `GOOGLE_CLOUD_LOCATION=global`? (Step 1)
- **U1** — Does Agent Runtime allow background/async work to complete past the initial response? (Step 2)
- **U2** — Is the hosted agent's egress free, or locked to Agent-Registry-registered destinations? (Step 2)
- **G2** — ✅ RESOLVED: `--extra_packages csf_coordinator csf_specialists csf_gateway` stages cleanly, no name-shadowing. Caveat: the agent's *runtime* deps must all be in the agent-dir `requirements.txt` (a missing one — qdrant-client — crashed container import; not caught by local test).
- **G3** — ✅ RESOLVED: `agentengine://` memory is ADK session/conversational memory — a different data model than our report-visible cross-run Tier/gap tracking. Doesn't replace ours; pipeline doesn't use ADK's memory API. Keep hand-rolled.

---

## 9. Reference — key paths & commands

- Working system branch: `feat/ingest-pipeline` · deployed service: `csf-gateway` (Cloud Run, `us`).
- Coordinator entry: `csf_coordinator/coordinator.py::run_assessment(session_id, functions=None, run_id=None)`.
- Dispatch mechanism (leave untouched): `csf_coordinator/steps.py::DispatchStep` → `csf-worker` Cloud Run Job.
- Probe smoke deploy (Step 1):
  ```
  poetry run adk deploy agent_engine \
    --project=csf-assessor-hackathon --region=us-central1 \
    --display_name=probe spike/probe_agent
  ```
- Real Coordinator deploy sketch (Step 3, adapt once adapter exists):
  ```
  poetry run adk deploy agent_engine \
    --project=csf-assessor-hackathon --region=us-central1 \
    --display_name=csf-coordinator \
    --extra_packages csf_specialists --extra_packages csf_gateway \
    --trigger_sources pubsub --otel_to_cloud \
    <coordinator_root_agent_dir>
  ```
- Related docs: `docs/HANDOFF.md` (§6 deploy, §7.9 Fortified table), `docs/decisions.md` (ADR-0004 Agent Identity), `docs/presentation_pointers.md` (judge narrative).
