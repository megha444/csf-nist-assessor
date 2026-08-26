"""
Coordinator workflow steps — plain-Python BaseAgent subclasses composed by
SequentialAgent in coordinator.py. ADK's workflow agents don't require every
sub-agent to be LLM-backed; dispatch/wait/aggregate is deterministic plumbing,
which is exactly what a custom BaseAgent step is for.

Each step gets everything it needs via constructor fields (not via ADK session
state) — run_id is generated once by the caller before the steps are built, so
there's no inter-step data-passing to reason about; each step is self-contained.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.cloud import run_v2
from google.cloud.firestore import AsyncClient
from google.genai import types

from csf_coordinator import pubsub_client
from csf_coordinator.config import get_settings
from csf_gateway.app.config import get_settings as get_gateway_settings
from csf_gateway.app.schema import RunStatus
from csf_gateway.app.tracing import get_tracer
from csf_specialists.aggregate import aggregate_function, persist_tier
from csf_specialists.judge import judge_run
from csf_specialists.loaders import rubric_version_hash
from csf_specialists.memory_bank import record_assessment

log = logging.getLogger("csf-coordinator.steps")
# Observability: the coordinator's orchestration plumbing (create/dispatch/
# collect/aggregate/judge) is now traced alongside the already-instrumented LLM
# operations (score/judge/interview), so a full assessment shows end-to-end in
# one Cloud Trace timeline — including the Collect wait, where "looks like a
# hang" incidents actually live. Non-fatal by design (tracing.py wraps export).
_tracer = get_tracer("csf-coordinator")

_firestore_client: AsyncClient | None = None
_firestore_loop = None  # event loop the cached client is bound to (loop-aware caching)

# csf-worker Cloud Run Job — one Job, `--function` overridden per execution.
# See task_list.md's Sun Aug 23 entry for why (shared image with the gateway,
# fire-and-forget since CollectResultsStep's own Pub/Sub polling is what
# actually waits for completion).
_CLOUD_RUN_REGION = "us-central1"
_CLOUD_RUN_WORKER_JOB = "csf-worker"


def _trigger_worker_job(function: str) -> None:
    settings = get_gateway_settings()
    client = run_v2.JobsClient()
    job_name = (
        f"projects/{settings.google_cloud_project}/locations/{_CLOUD_RUN_REGION}"
        f"/jobs/{_CLOUD_RUN_WORKER_JOB}"
    )
    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    args=["csf_specialists/worker.py", "--function", function, "--timeout", "60"],
                ),
            ],
        ),
    )
    client.run_job(request=request)


def _get_firestore_client() -> AsyncClient:
    # Loop-aware: rebind the AsyncClient when the running event loop changes, so
    # a cached client from a prior/closed loop never raises "Event loop is
    # closed" (Streamlit reruns, migration adapter, etc.). See memory_bank.py.
    import asyncio
    global _firestore_client, _firestore_loop
    loop = asyncio.get_running_loop()
    if _firestore_client is None or _firestore_loop is not loop:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
        _firestore_loop = loop
    return _firestore_client


def _text_event(author: str, text: str) -> Event:
    return Event(author=author, content=types.Content(role="model", parts=[types.Part(text=text)]))


class CreateRunStep(BaseAgent):
    """Creates the runs/{run_id} parent doc once per assessment, before any
    per-Function DispatchStep publishes. Split out from DispatchStep so an
    assessment covering N Functions creates exactly one run doc, not N."""

    run_id: str
    session_id: str
    expected_agents: int
    functions: list[str]

    async def _run_async_impl(self, ctx: InvocationContext):
        with _tracer.start_as_current_span("csf.coordinator.create_run") as span:
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("expected_agents", self.expected_agents)
            client = _get_firestore_client()
            session_ref = client.collection("sessions").document(self.session_id)

            doc_ids = [d.id async for d in session_ref.collection("documents").stream()]
            answer_ids = [a.id async for a in session_ref.collection("answers").stream()]
            span.set_attribute("doc_count", len(doc_ids))
            span.set_attribute("answer_count", len(answer_ids))

            run_ref = session_ref.collection("runs").document(self.run_id)
            await run_ref.set({
                "run_id": self.run_id,
                "session_id": self.session_id,
                "dispatched_at": datetime.now(timezone.utc),
                "status": RunStatus.dispatched.value,
                "expected_agents": self.expected_agents,
                "completed_agents": 0,
                "snapshot": {
                    "doc_ids": doc_ids,
                    "answer_ids": answer_ids,
                    # One hash per Function, not one flat string — a run can span
                    # 6 Functions with 6 different rubric files. Real content
                    # hashes, replacing the old always-"v1" placeholder.
                    "rubric_versions": {fn: rubric_version_hash(fn) for fn in self.functions},
                },
            })
            log.info(
                "created runs/%s (expected_agents=%d, doc_ids=%d, answer_ids=%d)",
                self.run_id, self.expected_agents, len(doc_ids), len(answer_ids),
            )
            yield _text_event(self.name, f"created run {self.run_id} (expecting {self.expected_agents} Function(s))")


class DispatchStep(BaseAgent):
    """Publishes one dispatch message for one Function and triggers the
    csf-worker Cloud Run Job execution that will consume it. Assumes
    CreateRunStep already created the runs/{run_id} parent doc.

    Job-triggering lives here (not in each caller) so both csf_ui/app.py and
    the Agent Runtime HTTP endpoint (csf_gateway/app/runs.py) get it for free
    just by calling run_assessment() — one place, not two copies to keep in
    sync."""

    run_id: str
    session_id: str
    function: str
    category_ids: list[str]

    async def _run_async_impl(self, ctx: InvocationContext):
        with _tracer.start_as_current_span("csf.coordinator.dispatch") as span:
            span.set_attribute("function", self.function)
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("category_count", len(self.category_ids))
            await pubsub_client.publish_dispatch(self.function, {
                "run_id": self.run_id,
                "session_id": self.session_id,
                "function": self.function,
                "category_ids": self.category_ids,
                "rubric_version": rubric_version_hash(self.function),
                "snapshot_ref": f"runs/{self.run_id}",
            })
            _trigger_worker_job(self.function)
            yield _text_event(self.name, f"dispatched {self.function} (run_id={self.run_id}, {len(self.category_ids)} Categories)")


class CollectResultsStep(BaseAgent):
    """Pulls csf-results until `expected_count` completions for this run_id arrive, or timeout."""

    session_id: str
    run_id: str
    expected_count: int = 1
    poll_timeout_s: float = 30.0
    # 300s was too tight — observed live (Aug 17): a 6-Category Govern run alone
    # regularly takes 4-6 min (GV.SC's 10 Subcategories are always the slowest),
    # and a real run got cancelled mid-GV.SC when this cap fired at 5 min while
    # Identify (3 Categories) had already finished. 900s gives real headroom for
    # the largest Function without masking a genuinely hung worker forever.
    max_wait_s: float = 900.0

    async def _run_async_impl(self, ctx: InvocationContext):
        import asyncio
        import time

        with _tracer.start_as_current_span("csf.coordinator.collect_results") as span:
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("expected_count", self.expected_count)
            span.set_attribute("max_wait_s", self.max_wait_s)
            start = time.monotonic()

            received: list[dict] = []
            deadline = start + self.max_wait_s
            while len(received) < self.expected_count and time.monotonic() < deadline:
                messages = await pubsub_client.pull_results(max_messages=10, timeout=self.poll_timeout_s)
                for msg in messages:
                    if msg.get("run_id") == self.run_id:
                        received.append(msg)
                    else:
                        log.info("ignoring result for a different run_id=%s", msg.get("run_id"))
                if len(received) < self.expected_count:
                    await asyncio.sleep(2)

            span.set_attribute("received_count", len(received))
            span.set_attribute("waited_s", round(time.monotonic() - start, 1))

            if len(received) < self.expected_count:
                span.set_attribute("timed_out", True)
                raise TimeoutError(
                    f"run_id={self.run_id}: expected {self.expected_count} completion(s), "
                    f"got {len(received)} within {self.max_wait_s}s"
                )

            client = _get_firestore_client()
            run_ref = (
                client.collection("sessions").document(self.session_id)
                .collection("runs").document(self.run_id)
            )
            await run_ref.update({
                "status": RunStatus.partial.value,
                "completed_agents": len(received),
            })

            log.info("run_id=%s: collected %d/%d completion(s)", self.run_id, len(received), self.expected_count)
            yield _text_event(self.name, f"collected {len(received)}/{self.expected_count} completions for run_id={self.run_id}")


class AggregateStep(BaseAgent):
    """Aggregates the persisted Category scores into a Tier and persists it."""

    session_id: str
    run_id: str
    function: str

    async def _run_async_impl(self, ctx: InvocationContext):
        with _tracer.start_as_current_span("csf.coordinator.aggregate") as span:
            span.set_attribute("function", self.function)
            span.set_attribute("run_id", self.run_id)
            result = await aggregate_function(self.session_id, self.run_id, self.function)
            await persist_tier(self.session_id, self.run_id, result)
            span.set_attribute("tier", result.tier)
            span.set_attribute("avg_cmmi", result.avg_cmmi)

            client = _get_firestore_client()
            session_ref = client.collection("sessions").document(self.session_id)
            run_ref = session_ref.collection("runs").document(self.run_id)

            # Aggregation no longer flips the terminal status — JudgeStep does,
            # so the report waits for Judge verdicts too (`ready_for_report` now
            # means scores + tiers + judge are ALL done, not just tiers). Status
            # stays `partial` through aggregation. Tier progress is recorded as a
            # span attribute for observability only.
            tier_count = len([t async for t in run_ref.collection("tiers").stream()])
            span.set_attribute("tiers_persisted", tier_count)

            # Memory Bank (Fortified component) — record this Function's result
            # against the org so a LATER, separate assessment of the same org can
            # see what this one found. Best-effort: a memory-write failure must
            # never break the actual scoring pipeline it's observing.
            with _tracer.start_as_current_span("csf.coordinator.memory_bank_write") as mem_span:
                mem_span.set_attribute("function", self.function)
                try:
                    session_snap = await session_ref.get()
                    org_id = (session_snap.to_dict() or {}).get("org_id", "") if session_snap.exists else ""
                    mem_span.set_attribute("org_id", org_id or "<none>")
                    await record_assessment(org_id, self.function, self.session_id, self.run_id, result)
                except Exception:
                    log.exception("[%s] Memory Bank write failed — continuing anyway", self.function)

            # SessionState.run_id exists precisely so a caller can GET /sessions/{sid}
            # and know which run to report on, without tracking run_id separately.
            # Not touching session-level `status` here — that field's ready_for_report
            # semantics imply all dispatched Functions are in, which isn't meaningful
            # yet for a Govern-only stub; revisit once the full fan-out exists.
            await session_ref.update({"run_id": self.run_id})

            log.info("[%s] run_id=%s aggregated -> Tier %d (avg_cmmi=%.3f)", self.function, self.run_id, result.tier, result.avg_cmmi)
            yield _text_event(self.name, f"Tier {result.tier} (avg_cmmi={result.avg_cmmi:.3f}) for {self.function}, run_id={self.run_id}")


class JudgeStep(BaseAgent):
    """Runs the LLM-as-Judge (csf_specialists.judge) over every Category
    already scored for one Function in this run, persisting a defensibility
    verdict per Category. Reads the same persisted scores AggregateStep does —
    no real dependency between the two, ordered after it here purely so the
    log narrative reads score -> aggregate -> judge, matching how a report
    would present Tier alongside its defensibility review."""

    session_id: str
    run_id: str
    function: str

    async def _run_async_impl(self, ctx: InvocationContext):
        with _tracer.start_as_current_span("csf.coordinator.judge") as span:
            span.set_attribute("function", self.function)
            span.set_attribute("run_id", self.run_id)
            results = await judge_run(self.session_id, self.run_id, self.function)
            counts = Counter(r.defensibility for r in results)
            summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            span.set_attribute("categories_judged", len(results))

            # Terminal completion signal (moved here from AggregateStep): flip the
            # run to ready_for_report only once EVERY Function has been judged, so
            # the report renders with defensibility verdicts present, not mid-Judge.
            # Counted per-Function (not per-Category doc) → hang-proof: a Category
            # whose judge failed still lets its Function advance the count.
            # JudgeSteps run sequentially, so read-increment-write needs no txn.
            client = _get_firestore_client()
            run_ref = (
                client.collection("sessions").document(self.session_id)
                .collection("runs").document(self.run_id)
            )
            run_doc = (await run_ref.get()).to_dict() or {}
            judged = run_doc.get("judged_functions", 0) + 1
            expected = run_doc.get("expected_agents", 1)
            update = {"judged_functions": judged}
            if judged >= expected:
                update["status"] = RunStatus.ready_for_report.value
            await run_ref.update(update)
            span.set_attribute("judged_functions", judged)

            log.info("[%s] run_id=%s judged %d Categories (%s)", self.function, self.run_id, len(results), summary)
            yield _text_event(self.name, f"judged {len(results)} Categories for {self.function}: {summary}")
