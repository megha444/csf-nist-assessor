"""
LLM-as-Judge — independent defensibility review of an already-scored Category.

Reads a persisted ScoreOutput and the Category's own CMMI rubric, and asks a
second model (the "Pro slot," gemini-3.7-flash per ADR-0005 — no Gemini 3.x Pro
tier exists yet, the newest Flash plays reviewer) whether the score would hold up
to a skeptical human auditor: does the cited evidence actually support the claimed
level, are citations specific, is confidence calibrated. Deliberately does NOT
re-run retrieval or re-score anything — critiques what the specialist already
produced, same as a human QA reviewer would work from the written assessment, not
redo the research from scratch.

Design per docs/lld.md §10 sequence diagram: judge runs per Category, in parallel
with aggregation, once all of a run's scores exist. Firestore layout also per
lld.md: sessions/{sid}/runs/{rid}/judge/{category_id}.
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
from google.cloud.firestore_v1.base_query import FieldFilter
from google.genai import types

from csf_gateway.app import model_armor, pii_scrubber
from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import Function
from csf_gateway.app.llm import gemini_model
from csf_gateway.app.schema import JudgeResult, ScoreOutput
from csf_gateway.app.tracing import get_tracer
from csf_specialists.loaders import load_rubric

log = logging.getLogger("csf-specialists.judge")
_tracer = get_tracer("csf-specialists")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "judge.txt"

ADK_APP_NAME = "csf-specialists-judge"
ADK_USER_ID = "csf-assessor"
ADK_OUTPUT_KEY = "judge_result"

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
            name="judge",
            model=gemini_model(s.gemini_pro_model, s.gemini_pro_fallback_model),
            output_schema=JudgeResult,
            output_key=ADK_OUTPUT_KEY,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=8000),
                max_output_tokens=8000,
            ),
        )
        _session_service = InMemorySessionService()
        _runner = Runner(agent=_llm_agent, app_name=ADK_APP_NAME, session_service=_session_service)
    return _runner


async def _fetch_score(session_id: str, run_id: str, category_id: str) -> ScoreOutput:
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("scores").document(category_id)
    )
    snap = await ref.get()
    if not snap.exists:
        raise ValueError(
            f"no score found at sessions/{session_id}/runs/{run_id}/scores/{category_id} — "
            f"score it first via SpecialistAgent.score_category(run_id=...)"
        )
    return ScoreOutput.model_validate(snap.to_dict())


def _build_prompt(score: ScoreOutput) -> str:
    rubric = load_rubric(score.function)
    cat = rubric.categories[score.category_id]
    rubric_block = "\n\n".join(f"Level {lvl}: {text}" for lvl, text in sorted(cat.levels.items()))

    if score.evidence_citations:
        citations_block = "\n".join(
            f'- doc_type/section={c.doc_title!r}/{c.section!r} pages={c.page_start}-{c.page_end}: {c.snippet[:300]}'
            for c in score.evidence_citations
        )
    else:
        citations_block = "(none cited)"

    interview_evidence_block = ", ".join(score.interview_evidence) if score.interview_evidence else "(none)"

    sub_lines: list[str] = []
    for s in score.subcategory_scores:
        sub_lines.append(
            f"\n{s.subcategory_id}: cmmi={s.cmmi_level} confidence={s.confidence:.2f} "
            f"evidence_status={s.evidence_status}\n"
            f"  expected_practice: {s.expected_practice}\n"
            f"  observations: {s.observations}\n"
            f"  gap: {s.gap}\n"
            f"  recommendation: {s.recommendation}"
        )
    subcategory_scores_block = "\n".join(sub_lines).strip() or "(none)"

    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        category_id=score.category_id,
        category_name=cat.name,
        function=score.function,
        rubric_block=rubric_block,
        category_cmmi=score.cmmi_level,
        category_confidence=f"{score.confidence:.2f}",
        no_doc_evidence=score.no_doc_evidence,
        category_reasoning=score.reasoning,
        n_citations=len(score.evidence_citations),
        citations_block=citations_block,
        interview_evidence_block=interview_evidence_block,
        subcategory_scores_block=subcategory_scores_block,
    )


async def judge_category(session_id: str, run_id: str, category_id: str) -> JudgeResult:
    """Review one already-scored Category's defensibility. Always persists —
    unlike score_category's optional run_id, a Judge result with nowhere to
    write to isn't a meaningful adhoc case (there's nothing to review without
    a persisted score to begin with).

    Thin span-wrapping shim around _judge_category_impl (closes the Agent
    Observability gap found Aug 21 — Judge had zero Cloud Trace instrumentation,
    which is why real Judge activity looked like a stall during a live 6-Function
    run). Same pattern as agent_base.py::score_category."""
    with _tracer.start_as_current_span("csf.specialist.judge_category") as span:
        span.set_attribute("csf.category_id", category_id)
        span.set_attribute("csf.session_id", session_id)
        span.set_attribute("csf.run_id", run_id)
        result = await _judge_category_impl(session_id, run_id, category_id)
        span.set_attribute("csf.defensibility", result.defensibility)
        return result


async def _judge_category_impl(session_id: str, run_id: str, category_id: str) -> JudgeResult:
    score = await _fetch_score(session_id, run_id, category_id)
    prompt = _build_prompt(score)
    await model_armor.screen_prompt(prompt, context=f"judge/{category_id}")
    prompt = pii_scrubber.scrub_for_llm(prompt, context=f"judge/{category_id}")

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
        raise RuntimeError(f"[judge/{category_id}] ADK runner produced no final response event.")

    actions = getattr(final_event, "actions", None)
    state_delta = (getattr(actions, "state_delta", None) or {}) if actions else {}
    state_dict = state_delta.get(ADK_OUTPUT_KEY)
    if state_dict is None:
        raise RuntimeError(f"[judge/{category_id}] no {ADK_OUTPUT_KEY!r} in state_delta — no parseable JudgeResult.")

    result = JudgeResult.model_validate(state_dict)
    log.info("[judge/%s] defensibility=%s", category_id, result.defensibility)

    await _persist_judge_result(session_id, run_id, result)
    return result


async def _persist_judge_result(session_id: str, run_id: str, result: JudgeResult) -> None:
    """Write to sessions/{sid}/runs/{rid}/judge/{category_id}, per docs/lld.md §10."""
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("judge").document(result.category_id)
    )
    payload = result.model_dump()
    payload["judged_at"] = datetime.now(timezone.utc)
    await ref.set(payload)
    log.info("[judge/%s] persisted -> sessions/%s/runs/%s/judge/%s", result.category_id, session_id, run_id, result.category_id)


async def judge_run(session_id: str, run_id: str, function: Function) -> list[JudgeResult]:
    """Judge every Category already scored for one Function in one run."""
    client = _get_firestore_client()
    coll = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("scores")
    )
    query = coll.where(filter=FieldFilter("function", "==", function))
    category_ids = [snap.id async for snap in query.stream()]
    if not category_ids:
        raise ValueError(f"no scores found for function={function!r} at sessions/{session_id}/runs/{run_id}/scores")

    return [await judge_category(session_id, run_id, cat_id) for cat_id in category_ids]
