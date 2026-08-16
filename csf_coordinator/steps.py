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
from datetime import datetime, timezone

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.cloud.firestore import AsyncClient
from google.genai import types

from csf_coordinator import pubsub_client
from csf_coordinator.config import get_settings
from csf_gateway.app.schema import RunStatus
from csf_specialists.aggregate import aggregate_function, persist_tier

log = logging.getLogger("csf-coordinator.steps")

_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


def _text_event(author: str, text: str) -> Event:
    return Event(author=author, content=types.Content(role="model", parts=[types.Part(text=text)]))


class DispatchStep(BaseAgent):
    """Creates the runs/{run_id} parent doc, then publishes one dispatch message."""

    run_id: str
    session_id: str
    function: str
    category_ids: list[str]

    async def _run_async_impl(self, ctx: InvocationContext):
        client = _get_firestore_client()
        session_ref = client.collection("sessions").document(self.session_id)

        doc_ids = [d.id async for d in session_ref.collection("documents").stream()]
        answer_ids = [a.id async for a in session_ref.collection("answers").stream()]

        run_ref = session_ref.collection("runs").document(self.run_id)
        await run_ref.set({
            "run_id": self.run_id,
            "session_id": self.session_id,
            "dispatched_at": datetime.now(timezone.utc),
            "status": RunStatus.dispatched.value,
            "expected_agents": 1,  # Govern-only stub; becomes 6 in the full fleet (Phase 3)
            "completed_agents": 0,
            "snapshot": {
                "doc_ids": doc_ids,
                "answer_ids": answer_ids,
                "rubric_version": "v1",
            },
        })
        log.info("[%s] created runs/%s (doc_ids=%d, answer_ids=%d)", self.function, self.run_id, len(doc_ids), len(answer_ids))

        await pubsub_client.publish_dispatch(self.function, {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "function": self.function,
            "category_ids": self.category_ids,
            "rubric_version": "v1",
            "snapshot_ref": f"runs/{self.run_id}",
        })
        yield _text_event(self.name, f"dispatched {self.function} (run_id={self.run_id}, {len(self.category_ids)} Categories)")


class CollectResultsStep(BaseAgent):
    """Pulls csf-results until `expected_count` completions for this run_id arrive, or timeout."""

    session_id: str
    run_id: str
    expected_count: int = 1
    poll_timeout_s: float = 30.0
    max_wait_s: float = 300.0

    async def _run_async_impl(self, ctx: InvocationContext):
        import asyncio
        import time

        received: list[dict] = []
        deadline = time.monotonic() + self.max_wait_s
        while len(received) < self.expected_count and time.monotonic() < deadline:
            messages = await pubsub_client.pull_results(max_messages=10, timeout=self.poll_timeout_s)
            for msg in messages:
                if msg.get("run_id") == self.run_id:
                    received.append(msg)
                else:
                    log.info("ignoring result for a different run_id=%s", msg.get("run_id"))
            if len(received) < self.expected_count:
                await asyncio.sleep(2)

        if len(received) < self.expected_count:
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
        result = await aggregate_function(self.session_id, self.run_id, self.function)
        await persist_tier(self.session_id, self.run_id, result)

        client = _get_firestore_client()
        run_ref = (
            client.collection("sessions").document(self.session_id)
            .collection("runs").document(self.run_id)
        )
        await run_ref.update({"status": RunStatus.ready_for_report.value})

        log.info("[%s] run_id=%s aggregated -> Tier %d (avg_cmmi=%.3f)", self.function, self.run_id, result.tier, result.avg_cmmi)
        yield _text_event(self.name, f"Tier {result.tier} (avg_cmmi={result.avg_cmmi:.3f}) for {self.function}, run_id={self.run_id}")
