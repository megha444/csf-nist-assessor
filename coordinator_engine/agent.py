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
  2. parses `session=<sid>` and optional `functions=govern,identify` / `run=<rid>`,
  3. awaits the existing run_assessment() to completion (synchronous — Gate 2
     proved a hosted invocation holds well past a 2-Function run),
  4. yields a final event with the run_id and per-Function tier summary.

`run=<rid>` matters when the caller is the gateway rather than a human at the
playground: POST /sessions/{sid}/run returns a run_id to the UI *immediately*
and the UI then polls sessions/{sid}/runs/{rid}. If we minted our own run_id
here instead of honouring the caller's, that poll would target a document that
never gets written and the UI would sit on "pending" forever. Omitted (the
playground / spike case) → run_assessment generates one, as before.

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


def _trust_agent_gateway_ca() -> None:
    """Teach this container to trust the Agent Gateway's TLS inspection CA.

    Agent Gateway INSPECTS traffic, which means it terminates TLS and re-signs
    with its own "Agent Gateway TLS Inspection CA" — a deliberate MITM, and the
    only way Model Armor can read a request body. Clients that don't hold that CA
    fail every call with:

        SSLCertVerificationError: self-signed certificate in certificate chain

    Adding the CA to the OS store is NOT enough: aiohttp / requests / google-auth
    read the bundle shipped by the `certifi` package, and gRPC reads whatever
    GRPC_DEFAULT_SSL_ROOTS_FILE_PATH names. So we concatenate certifi's bundle
    with the gateway CA and point all three at the result.

    Gated on AGENT_GATEWAY_CA_BUNDLE=1, injected by
    infra/deploy_coordinator_engine.sh for NON-PRODUCTION engines only. Production
    does not route through the gateway, so it must not carry an extra trusted CA
    it has no use for — trusting a MITM CA you don't need is a real, if small,
    widening of the trust boundary, and this project's Agent Identity claims are
    the last place to be casual about that.

    Must run BEFORE any csf_* import constructs a client, same as the project-id
    fix above: SSL contexts are built once and cached.
    """
    if os.environ.get("AGENT_GATEWAY_CA_BUNDLE") != "1":
        return
    # Normal path: the deploy script baked the bundle into the image and pointed
    # the env vars at it, so it is already in force before this module is imported
    # — which is the only ordering that works for gRPC (see the deploy script).
    # Nothing to do; just confirm it so the log says which file is authoritative.
    preset = os.environ.get("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH")
    if preset and os.path.exists(preset):
        log.info("Agent Gateway CA already trusted via %s (baked into image)", preset)
        return
    # Fallback only. This fixes HTTP clients but is TOO LATE for gRPC, whose roots
    # are cached during container startup. Kept so a misconfigured deploy degrades
    # to "HTTP works, gRPC does not" rather than failing everything silently.
    log.warning("Agent Gateway CA bundle not baked in; falling back to a runtime "
                "bundle. HTTP will work, gRPC will still fail cert verification.")
    ca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_gateway_ca.pem")
    if not os.path.exists(ca):
        log.warning("AGENT_GATEWAY_CA_BUNDLE=1 but %s is missing — egress will fail", ca)
        return
    try:
        import certifi

        # Keep this path in sync with GRPC_DEFAULT_SSL_ROOTS_FILE_PATH in
        # infra/deploy_coordinator_engine.sh — gRPC reads that env var from the
        # container environment, so the two must name the same file.
        bundle = os.environ.get("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
                                "/tmp/ca-bundle-with-agent-gateway.pem")
        with open(bundle, "w") as out:
            for src in (certifi.where(), ca):
                with open(src) as f:
                    out.write(f.read().rstrip() + "\n")
        # requests/aiohttp/google-auth, the stdlib default, and gRPC respectively.
        os.environ["REQUESTS_CA_BUNDLE"] = bundle
        os.environ["SSL_CERT_FILE"] = bundle
        os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = bundle
        log.info("Agent Gateway CA trusted via %s", bundle)
    except Exception:
        log.exception("failed to build the Agent Gateway CA bundle")


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("csf-coordinator.entry")
_trust_agent_gateway_ca()

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

from csf_coordinator.coordinator import run_assessment

_SESSION_RE = re.compile(r"session\s*=\s*([A-Za-z0-9\-]+)")
# Stops at the next `key=` token instead of running to end-of-string. Without
# the lookahead, "functions=govern,identify run=<rid>" parses a function called
# "identify run" (the char class eats spaces and letters), which then fails
# run_assessment's unknown-function check. Still tolerates "govern, identify".
_FUNCTIONS_RE = re.compile(r"functions\s*=\s*([A-Za-z0-9_,\s]+?)(?=\s+[A-Za-z_]+\s*=|$)")
# `run=` must be matched before `session=`/`functions=` can swallow it: both are
# uuid-shaped, so the patterns are anchored on their own key names, not position.
_RUN_RE = re.compile(r"\brun\s*=\s*([A-Za-z0-9\-]+)")


def _text_event(author: str, invocation_id: str, text: str) -> Event:
    """Like csf_coordinator/steps.py::_text_event, but carries invocation_id.
    Agent Engine's MANAGED session service rejects events without it (400
    INVALID_ARGUMENT), unlike the lenient InMemorySessionService the steps use."""
    return Event(
        author=author,
        invocation_id=invocation_id,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


def _parse_request(text: str) -> tuple[str | None, list[str] | None, str | None]:
    """Pull session_id, optional function list, and optional run_id out of the
    invocation message. Expected form:
    'session=<sid> functions=govern,identify run=<rid>' — functions optional
    (→ every registered agent, resolved inside run_assessment) and run optional
    (→ run_assessment mints one). The gateway always sends run= so the run_id it
    already handed the UI is the one actually written to Firestore."""
    session_id = None
    functions = None
    run_id = None
    if (m := _SESSION_RE.search(text)):
        session_id = m.group(1)
    if (m := _FUNCTIONS_RE.search(text)):
        functions = [f.strip() for f in m.group(1).split(",") if f.strip()]
    if (m := _RUN_RE.search(text)):
        run_id = m.group(1)
    return session_id, functions, run_id


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

        session_id, functions, req_run_id = _parse_request(text)
        if not session_id:
            yield _text_event(
                self.name, ctx.invocation_id,
                "ERROR: no session id in message. Expected: 'session=<sid> functions=govern,identify run=<rid>'.",
            )
            return

        yield _text_event(
            self.name, ctx.invocation_id,
            f"starting assessment · session={session_id} · functions={functions or 'ALL registered'}"
            f" · run={req_run_id or 'auto'}",
        )
        log.info(
            "[entry] run_assessment session=%s functions=%s run_id=%s",
            session_id, functions, req_run_id,
        )

        _reset_stale_clients()  # rebind cached async clients to THIS invocation's loop
        run_id, tiers = await run_assessment(session_id, functions, req_run_id)

        bits = []
        for fn, tier in tiers.items():
            tval = getattr(tier, "tier", None)
            bits.append(f"{fn}=Tier{tval}" if tval is not None else fn)
        summary = ", ".join(bits) if bits else "no tiers persisted"
        yield _text_event(self.name, ctx.invocation_id, f"DONE · run_id={run_id} · {summary}")


root_agent = CoordinatorEntryAgent(name="csf_coordinator_entry")
