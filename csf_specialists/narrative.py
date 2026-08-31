"""
Report narrative — the prose half of the PDF report.

One Gemini call per run turns the aggregated scores into the language the
Executive Summary and Areas of Improvement pages need: an opening paragraph, one
finding per Function, and 4-6 cross-cutting improvement themes. Every *number* in
the PDF still comes from the persisted scores; this module only produces the words
wrapped around them, and the prompt is grounded in the real Category scores and the
weakest Subcategories so it cannot invent a finding.

Persisted at sessions/{sid}/runs/{rid}/report/narrative, so re-rendering the PDF
(a Streamlit rerun, a second download) never re-bills a Gemini call.

Deliberately importable from csf_coordinator.steps: LLM + Firestore + Pydantic
only, all of which coordinator_engine/requirements.txt already carries. The
reportlab rendering lives in csf_specialists/scripts/export_pdf.py and must stay
out of this import chain — see that module's docstring.

Same structure as csf_specialists/judge.py (cached LlmAgent + Runner, loop-aware
Firestore client, Model Armor + PII scrub before the call).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud.firestore import AsyncClient
from google.genai import types

from csf_gateway.app import model_armor, pii_scrubber
from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import FUNCTION_NAMES, categories_for_function
from csf_gateway.app.llm import gemini_model
from csf_gateway.app.schema import ReportNarrative
from csf_gateway.app.tracing import get_tracer
from csf_specialists.aggregate import CONFIDENCE_THRESHOLD, overall_maturity
from csf_specialists.loaders import load_implementation_examples

log = logging.getLogger("csf-specialists.narrative")
_tracer = get_tracer("csf-specialists")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "narrative.txt"

ADK_APP_NAME = "csf-specialists-narrative"
ADK_USER_ID = "csf-assessor"
ADK_OUTPUT_KEY = "report_narrative"

# How many of the lowest-scoring Subcategories to hand the model as evidence for
# the improvement themes. 15 is roughly the bottom seventh of the 106 CSF 2.0
# Subcategories — enough for 4-6 real themes to emerge, few enough that the model
# groups them instead of transcribing the list.
WEAKEST_SUBCATEGORY_COUNT = 15

# The six CSF 2.0 Function definitions, in the plain-English register the report
# uses. Static, NOT LLM-generated — these are stable framework definitions and a
# model paraphrasing them each run would be six chances to drift for no gain.
# Taken verbatim from the approved Executive Summary template.
FUNCTION_DEFINITIONS: dict[str, str] = {
    "govern":   "Sets the strategy, policy, and accountability for how the organisation manages cyber risk.",
    "identify": "Understanding what needs protecting — the organisation's systems, data, and the risks to them.",
    "protect":  "The safeguards — access control, encryption, training — that limit or contain a cyber incident.",
    "detect":   "The organisation's ability to notice that a cybersecurity incident is happening.",
    "respond":  "The actions taken to contain and manage a cybersecurity incident once confirmed.",
    "recover":  "Restoring normal business operations and services after a cybersecurity incident.",
}

_firestore_client: AsyncClient | None = None
_firestore_loop = None  # event loop the cached client is bound to (loop-aware caching)
_llm_agent: LlmAgent | None = None
_session_service: InMemorySessionService | None = None
_runner: Runner | None = None


def _get_firestore_client() -> AsyncClient:
    # Loop-aware: rebind the AsyncClient when the running event loop changes
    # (Streamlit reruns / fresh asyncio.run) so a cached client from a closed
    # loop never raises "Event loop is closed". See memory_bank.py.
    import asyncio
    global _firestore_client, _firestore_loop
    loop = asyncio.get_running_loop()
    if _firestore_client is None or _firestore_loop is not loop:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
        _firestore_loop = loop
    return _firestore_client


def _get_runner() -> Runner:
    global _llm_agent, _session_service, _runner
    if _runner is None:
        s = get_settings()
        _llm_agent = LlmAgent(
            name="narrative",
            model=gemini_model(s.gemini_pro_model, s.gemini_pro_fallback_model),
            output_schema=ReportNarrative,
            output_key=ADK_OUTPUT_KEY,
            generate_content_config=types.GenerateContentConfig(
                # Slightly above the 0.1 scoring/judge use — this is the one place
                # in the system producing prose a human reads for tone, and 0.1
                # makes six Function summaries that all open the same way.
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_budget=8000),
                max_output_tokens=8000,
            ),
        )
        _session_service = InMemorySessionService()
        _runner = Runner(agent=_llm_agent, app_name=ADK_APP_NAME, session_service=_session_service)
    return _runner


# ---------------------------------------------------------------------------
# Documents provided for a run — shared with the PDF appendix
# ---------------------------------------------------------------------------


async def session_target_org(session_id: str) -> str:
    """The session's display name for the org under assessment.

    Reads the session document directly rather than going through
    csf_gateway.app.sessions.get_session — that module imports FastAPI to declare
    its router, and this one is in the coordinator's import chain, which the Agent
    Engine deployment satisfies from coordinator_engine/requirements.txt where
    fastapi is deliberately absent. One field is not worth dragging a web
    framework into a deployment that has no HTTP surface.
    """
    client = _get_firestore_client()
    snap = await client.collection("sessions").document(session_id).get()
    return ((snap.to_dict() or {}).get("target_org") or session_id) if snap.exists else session_id


async def run_document_names(session_id: str, run_id: str) -> list[str]:
    """Filenames of every document this run actually saw, plus any questionnaires
    uploaded to the session.

    Driven by the run's own `snapshot.doc_ids` (written by CreateRunStep) rather
    than the live documents collection, so a document uploaded *after* dispatch —
    which no specialist agent could have read — is correctly left out of the
    report's appendix. Falls back to the live collection for older runs whose
    snapshot predates the field.
    """
    client = _get_firestore_client()
    session_ref = client.collection("sessions").document(session_id)
    run_snap = await session_ref.collection("runs").document(run_id).get()
    doc_ids = ((run_snap.to_dict() or {}).get("snapshot") or {}).get("doc_ids") or []

    names: list[str] = []
    if doc_ids:
        for doc_id in doc_ids:
            snap = await session_ref.collection("documents").document(doc_id).get()
            if snap.exists:
                names.append((snap.to_dict() or {}).get("filename", doc_id))
    else:
        async for snap in session_ref.collection("documents").stream():
            names.append((snap.to_dict() or {}).get("filename", snap.id))

    # Questionnaires go through POST /sessions/{sid}/qna, a separate path that
    # never touches the documents collection — appended so the appendix reflects
    # everything the client actually handed over, not just the evidence corpus.
    async for snap in session_ref.collection("questionnaires").stream():
        filename = (snap.to_dict() or {}).get("filename")
        if filename:
            names.append(filename)

    return sorted(names)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _weakest_subcategories(report: dict) -> list[dict]:
    """Every Subcategory across the run, worst first. Sorted by CMMI then by
    confidence, so a confidently-evidenced Level 1 outranks a barely-evidenced
    one — the model should theme what we actually know is weak ahead of what we
    merely failed to evidence."""
    flat: list[dict] = []
    for function, data in report["functions"].items():
        examples = load_implementation_examples(function)
        for cat in data["categories"]:
            for s in cat.get("subcategory_scores", []):
                meta = examples.get(s["subcategory_id"])
                flat.append({
                    "function": function,
                    "category_id": cat["category_id"],
                    "subcategory_id": s["subcategory_id"],
                    "name": meta.name if meta else "",
                    "cmmi_level": s["cmmi_level"],
                    "confidence": s["confidence"],
                    "evidence_status": s["evidence_status"],
                    "gap": s["gap"],
                })
    flat.sort(key=lambda s: (s["cmmi_level"], -s["confidence"]))
    return flat[:WEAKEST_SUBCATEGORY_COUNT]


def _functions_block(report: dict) -> str:
    lines: list[str] = []
    for function in FUNCTION_NAMES:  # canonical Govern->Recover order
        data = report["functions"].get(function)
        if not data:
            continue
        tier_data = data.get("tier") or {}
        cat_names = {c.code: c.name for c in categories_for_function(function)}
        lines.append(
            f"\n{FUNCTION_NAMES[function]} ({function}) — Tier {tier_data.get('tier', '?')}, "
            f"average CMMI {tier_data.get('avg_cmmi', 0):.2f} across {len(data['categories'])} Categories"
        )
        insufficient = tier_data.get("insufficient_evidence_count") or 0
        if insufficient:
            lines.append(
                f"  {insufficient} Categor{'y' if insufficient == 1 else 'ies'} scored below the confidence "
                f"threshold — the evidence provided was too thin to score them reliably."
            )
        for c in sorted(data["categories"], key=lambda c: c["category_id"]):
            flags = []
            if c["confidence"] < CONFIDENCE_THRESHOLD:
                flags.append("low confidence")
            if c["no_doc_evidence"]:
                flags.append("no document evidence")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  {c['category_id']} {cat_names.get(c['category_id'], '')}: CMMI {c['cmmi_level']}{flag_text}"
            )
            lines.append(f"    {c['reasoning']}")
    return "\n".join(lines).strip() or "(no Functions scored)"


def _weakest_block(report: dict) -> str:
    weakest = _weakest_subcategories(report)
    if not weakest:
        return "(no Subcategory scores recorded)"
    return "\n".join(
        f"\n{s['subcategory_id']} ({FUNCTION_NAMES.get(s['function'], s['function'])} / {s['category_id']})"
        f" — CMMI {s['cmmi_level']}, confidence {s['confidence'] * 100:.0f}%, evidence {s['evidence_status']}"
        f"\n  {s['name']}"
        f"\n  gap: {s['gap']}"
        for s in weakest
    ).strip()


def build_prompt(report: dict, target_org: str, document_count: int) -> str:
    overall = overall_maturity(report)
    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        target_org=target_org,
        assessment_date=datetime.now(timezone.utc).strftime("%B %Y"),
        document_count=document_count,
        overall_cmmi=f"{overall[0]:.2f}" if overall else "not yet aggregated",
        overall_tier=overall[1] if overall else "?",
        confidence_threshold_pct=round(CONFIDENCE_THRESHOLD * 100),
        functions_block=_functions_block(report),
        weakest_block=_weakest_block(report),
    )


# ---------------------------------------------------------------------------
# Generate / persist / load
# ---------------------------------------------------------------------------


async def generate_narrative(session_id: str, run_id: str) -> ReportNarrative:
    """Synthesise (and persist) the report narrative for one completed run.

    Reads the same aggregated structure the report renderers use, so there is no
    second Firestore query path to keep in sync.
    """
    with _tracer.start_as_current_span("csf.specialist.generate_narrative") as span:
        span.set_attribute("csf.session_id", session_id)
        span.set_attribute("csf.run_id", run_id)

        # Imported here, not at module scope: export_json lives under scripts/ and
        # importing it eagerly would drag the scripts package into every consumer
        # of this module (including the coordinator's own import chain).
        from csf_specialists.scripts.export_json import build_report

        report = await build_report(session_id, run_id)
        target_org = await session_target_org(session_id)
        document_names = await run_document_names(session_id, run_id)

        prompt = build_prompt(report, target_org, len(document_names))
        await model_armor.screen_prompt(prompt, context=f"narrative/{run_id}")
        prompt = pii_scrubber.scrub_for_llm(prompt, context=f"narrative/{run_id}")

        runner = _get_runner()
        adk_session_id = str(uuid.uuid4())
        await _session_service.create_session(app_name=ADK_APP_NAME, user_id=ADK_USER_ID, session_id=adk_session_id)

        final_event = None
        async for event in runner.run_async(
            user_id=ADK_USER_ID,
            session_id=adk_session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            if event.is_final_response():
                final_event = event

        if final_event is None:
            raise RuntimeError(f"[narrative/{run_id}] ADK runner produced no final response event.")

        actions = getattr(final_event, "actions", None)
        state_delta = (getattr(actions, "state_delta", None) or {}) if actions else {}
        state_dict = state_delta.get(ADK_OUTPUT_KEY)
        if state_dict is None:
            raise RuntimeError(f"[narrative/{run_id}] no {ADK_OUTPUT_KEY!r} in state_delta — no parseable ReportNarrative.")

        narrative = ReportNarrative.model_validate(state_dict)
        span.set_attribute("csf.improvement_themes", len(narrative.improvement_themes))
        span.set_attribute("csf.function_summaries", len(narrative.function_summaries))
        log.info(
            "[narrative/%s] %d Function summaries, %d improvement themes",
            run_id, len(narrative.function_summaries), len(narrative.improvement_themes),
        )

        await persist_narrative(session_id, run_id, narrative)
        return narrative


async def persist_narrative(session_id: str, run_id: str, narrative: ReportNarrative) -> None:
    """Write to sessions/{sid}/runs/{rid}/report/narrative."""
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("report").document("narrative")
    )
    payload = narrative.model_dump()
    payload["generated_at"] = datetime.now(timezone.utc)
    await ref.set(payload)
    log.info("[narrative/%s] persisted -> sessions/%s/runs/%s/report/narrative", run_id, session_id, run_id)


async def load_narrative(session_id: str, run_id: str) -> ReportNarrative | None:
    """Read back a persisted narrative, or None if this run has never had one
    generated. None is the expected case for any run that completed before this
    feature shipped — callers fall back to generating one on demand."""
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("report").document("narrative")
    )
    snap = await ref.get()
    if not snap.exists:
        return None
    return ReportNarrative.model_validate(snap.to_dict())
