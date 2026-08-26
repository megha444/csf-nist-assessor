"""
Agent Runtime entry point for the CSF Coordinator.

`adk deploy agent_engine` needs a static module-level `root_agent`. Our real
orchestrator, csf_coordinator.coordinator.run_assessment(), is a *factory*: it
builds a fresh SequentialAgent per assessment (parameterized by session_id /
functions / run_id) and runs it via its own Runner. This adapter is the thin
bridge between the two — it does NOT re-implement any orchestration logic.

CoordinatorEntryAgent is a plain BaseAgent (same style as the steps in
csf_coordinator/steps.py). On invocation it:
  1. reads the incoming message text (ctx.user_content),
  2. parses `session=<sid>` and optional `functions=govern,identify`,
  3. awaits the existing run_assessment() to completion (synchronous — Gate 2
     proved a hosted invocation holds well past a 2-Function run),
  4. yields a final event with the run_id and per-Function tier summary.

Firestore remains the source of truth; the event text is a convenience. The
run's real output is verified by reading sessions/{sid}/runs/{run_id} back.
"""
from __future__ import annotations

import logging
import os
import re

# Agent Runtime injects GOOGLE_CLOUD_PROJECT as the project NUMBER into the
# container, and Firestore then 404s ("database (default) does not exist for
# project <number>"). Force the canonical project ID *before* any csf_* import
# constructs a Firestore client or caches get_settings().
os.environ["GOOGLE_CLOUD_PROJECT"] = "csf-assessor-hackathon"

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

from csf_coordinator.coordinator import run_assessment

log = logging.getLogger("csf-coordinator.entry")

_SESSION_RE = re.compile(r"session\s*=\s*([A-Za-z0-9\-]+)")
_FUNCTIONS_RE = re.compile(r"functions\s*=\s*([A-Za-z0-9_,\s]+)")


def _text_event(author: str, invocation_id: str, text: str) -> Event:
    """Like csf_coordinator/steps.py::_text_event, but carries invocation_id.
    Agent Engine's MANAGED session service rejects events without it (400
    INVALID_ARGUMENT), unlike the lenient InMemorySessionService the steps use."""
    return Event(
        author=author,
        invocation_id=invocation_id,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


def _parse_request(text: str) -> tuple[str | None, list[str] | None]:
    """Pull session_id and optional function list out of the invocation message.
    Expected form: 'session=<sid> functions=govern,identify' (functions optional
    → defaults to every registered agent inside run_assessment)."""
    session_id = None
    functions = None
    if (m := _SESSION_RE.search(text)):
        session_id = m.group(1)
    if (m := _FUNCTIONS_RE.search(text)):
        functions = [f.strip() for f in m.group(1).split(",") if f.strip()]
    return session_id, functions


def _reset_stale_clients() -> None:
    """Agent Runtime keeps the container warm but hands each invocation a FRESH
    asyncio event loop. Several modules cache a Firestore AsyncClient — and Judge
    caches an ADK Runner — in a module-level global bound to whichever loop first
    created it. That's fine in the long-lived gateway process (one loop for the
    process's life), but here the 2nd invocation reuses a client bound to the
    1st (now-closed) loop → 'RuntimeError: Event loop is closed'. Null them so
    each run rebinds to the current loop. Isolated to this adapter; touches no
    shared logic (the originals just get lazily recreated, as on a cold start)."""
    import csf_coordinator.steps as _steps
    import csf_specialists.aggregate as _agg
    import csf_specialists.judge as _judge
    import csf_specialists.memory_bank as _mem

    _steps._firestore_client = None
    _agg._firestore_client = None
    _mem._firestore_client = None
    _judge._firestore_client = None
    _judge._runner = None
    _judge._llm_agent = None
    _judge._session_service = None


class CoordinatorEntryAgent(BaseAgent):
    """Static root agent that drives the existing run_assessment() factory."""

    async def _run_async_impl(self, ctx: InvocationContext):
        text = ""
        if ctx.user_content and ctx.user_content.parts:
            text = "".join(p.text for p in ctx.user_content.parts if p.text)

        session_id, functions = _parse_request(text)
        if not session_id:
            yield _text_event(
                self.name, ctx.invocation_id,
                "ERROR: no session id in message. Expected: 'session=<sid> functions=govern,identify'.",
            )
            return

        yield _text_event(
            self.name, ctx.invocation_id,
            f"starting assessment · session={session_id} · functions={functions or 'ALL registered'}",
        )
        log.info("[entry] run_assessment session=%s functions=%s", session_id, functions)

        _reset_stale_clients()  # rebind cached async clients to THIS invocation's loop
        run_id, tiers = await run_assessment(session_id, functions)

        bits = []
        for fn, tier in tiers.items():
            tval = getattr(tier, "tier", None)
            bits.append(f"{fn}=Tier{tval}" if tval is not None else fn)
        summary = ", ".join(bits) if bits else "no tiers persisted"
        yield _text_event(self.name, ctx.invocation_id, f"DONE · run_id={run_id} · {summary}")


root_agent = CoordinatorEntryAgent(name="csf_coordinator_entry")
