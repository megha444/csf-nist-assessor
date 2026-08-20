"""
Interview Director — decides the next interview question per turn via a single
ADK LlmAgent structured-output call, mixing unused seed questions with NIST-grounded
generated ones. Lives in csf_coordinator per docs/architecture.md's placement, even
though there's no separate deployed coordinator service yet (same simplification
already used by csf_coordinator/coordinator.py).

This is what Provenance.live_chat_generated (csf_gateway/app/schema.py) is for: an
answer whose QUESTION was itself generated live, not drawn from any pre-written bank.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.genai import types
from pydantic import BaseModel, Field

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import Function
from csf_gateway.app.llm import gemini_model
from csf_gateway.app.schema import Provenance
from csf_specialists.loaders import examples_for_category, load_rubric

log = logging.getLogger("csf-coordinator.interview")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "next_question.txt"
SAMPLE_DATA_DIR = Path(__file__).resolve(
).parents[1] / "csf_specialists" / "sample_data"

MAX_QUESTIONS = 35
ADK_APP_NAME = "csf-coordinator-interview"
ADK_USER_ID = "csf-assessor"

_SOURCE_TO_PROVENANCE = {
    "seed": Provenance.live_chat,
    "generated": Provenance.live_chat_generated,
}

_firestore_client: AsyncClient | None = None
_llm_agent: LlmAgent | None = None
_session_service: InMemorySessionService | None = None
_runner: Runner | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(
            project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


class NextQuestionDecision(BaseModel):
    """Internal — the Interview Director's per-turn structured decision."""
    done: bool
    question_id: str | None = None
    question: str | None = None
    category_hint: str | None = Field(
        None, description="Subcategory id, e.g. 'GV.SC-07'")
    source: Literal["seed", "generated"] | None = None
    reasoning: str


def _get_runner() -> Runner:
    global _llm_agent, _session_service, _runner
    if _runner is None:
        s = get_settings()
        _llm_agent = LlmAgent(
            name="interview_director",
            model=gemini_model(s.gemini_flash_model),
            output_schema=NextQuestionDecision,
            output_key="decision",
            generate_content_config=types.GenerateContentConfig(
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_budget=4000),
                max_output_tokens=4000,
            ),
        )
        _session_service = InMemorySessionService()
        _runner = Runner(agent=_llm_agent, app_name=ADK_APP_NAME,
                         session_service=_session_service)
    return _runner


async def _fetch_answers(session_id: str, function: Function) -> list[dict]:
    client = _get_firestore_client()
    coll = client.collection("sessions").document(
        session_id).collection("answers")
    query = coll.where(filter=FieldFilter("function", "==", function))
    return [snap.to_dict() async for snap in query.stream()]


async def _fetch_chunk_category_counts(session_id: str, function: Function) -> dict[str, int]:
    """Category-level doc-chunk coverage — chunks are only Category-tagged today
    (tagger.py), not Subcategory-tagged (blocked on Sakina's still-pending evidence
    taxonomy). Applied as a shared baseline to every Subcategory under a Category."""
    client = _get_firestore_client()
    counts: dict[str, int] = {}
    function_categories = set(load_rubric(function).categories.keys())
    session_ref = client.collection("sessions").document(session_id)
    async for doc_snap in session_ref.collection("documents").stream():
        async for chunk_snap in doc_snap.reference.collection("chunks").stream():
            for cat in chunk_snap.to_dict().get("candidate_categories", []):
                if cat in function_categories:
                    counts[cat] = counts.get(cat, 0) + 1
    return counts


async def _compute_coverage(session_id: str, function: Function) -> dict[str, int]:
    """Subcategory-granularity coverage. Generalizes lld.md §8.1's compute_coverage()
    from Category to Subcategory granularity, matching ADR-0007's Subcategory focus
    everywhere else in the system."""
    rubric = load_rubric(function)
    coverage: dict[str, int] = {}

    chunk_counts = await _fetch_chunk_category_counts(session_id, function)
    for cat_code in rubric.categories:
        baseline = chunk_counts.get(cat_code, 0)
        for sub in examples_for_category(function, cat_code):
            coverage[sub.subcategory_id] = baseline

    for answer in await _fetch_answers(session_id, function):
        sub_id = answer.get("category_hint", "")
        if sub_id:
            coverage[sub_id] = coverage.get(sub_id, 0) + 2

    return coverage


def _load_seed_questions(function: Function) -> list[dict]:
    path = SAMPLE_DATA_DIR / f"{function}_questions.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _build_prompt(
    function: Function,
    coverage: dict[str, int],
    seed_questions: list[dict],
    asked_seed_ids: set[str],
    prior_qa: list[dict],
    questions_asked: int,
) -> str:
    rubric = load_rubric(function)

    # need_score = category_importance / (1 + coverage), descending — see lld.md §8.1,
    # generalized to Subcategory. No per-Subcategory importance weight exists yet
    # (that's Sakina's still-pending deliverable, same gap as the roadmap-ranking code);
    # the parent Category's importance is used as a proxy, default 2.
    needs: list[tuple[str, float, int, int]] = []
    for cat_code, cat in rubric.categories.items():
        for sub in examples_for_category(function, cat_code):
            cov = coverage.get(sub.subcategory_id, 0)
            need_score = cat.importance / (1 + cov)
            needs.append((sub.subcategory_id, need_score, cat.importance, cov))
    needs.sort(key=lambda t: t[1], reverse=True)

    coverage_block = "\n".join(
        f"{sub_id}: coverage={cov}, category_importance={imp}"
        for sub_id, _, imp, cov in needs
    )

    unused_seed = [q for q in seed_questions if q["id"] not in asked_seed_ids]
    if unused_seed:
        seed_questions_block = "\n".join(
            f'{q["id"]} (targets {q["category_hint"]}): {q["question"]}' for q in unused_seed
        )
    else:
        seed_questions_block = "(no unused seed questions remain)"

    top_needs = {sub_id for sub_id, *_ in needs[:5]}
    examples_lines: list[str] = []
    for cat_code in rubric.categories:
        for sub in examples_for_category(function, cat_code):
            if sub.subcategory_id in top_needs:
                examples_lines.append(f"\n{sub.subcategory_id}: {sub.name}")
                for ex in sub.examples:
                    examples_lines.append(f"  - {ex}")
    examples_block = "\n".join(examples_lines).strip() or "(none)"

    if prior_qa:
        prior_qa_block = "\n\n".join(
            f'Q: {a.get("question", "")}\n  A: {a.get("answer", "")}' for a in prior_qa
        )
    else:
        prior_qa_block = "(no answers recorded yet this session)"

    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        function=function,
        questions_asked=questions_asked,
        max_questions=MAX_QUESTIONS,
        coverage_block=coverage_block,
        seed_questions_block=seed_questions_block,
        examples_block=examples_block,
        prior_qa_block=prior_qa_block,
    )


async def decide_next_question(session_id: str, function: Function) -> NextQuestionDecision:
    """Public entry point — one LLM decision per turn: seed question, generated
    question, or done."""
    prior_qa = await _fetch_answers(session_id, function)
    questions_asked = len(prior_qa)

    if questions_asked >= MAX_QUESTIONS:
        return NextQuestionDecision(done=True, reasoning=f"hit the {MAX_QUESTIONS}-turn safety cap")

    coverage = await _compute_coverage(session_id, function)
    seed_questions = _load_seed_questions(function)
    print(
        f"[interview/{function}] coverage={coverage}, prior_qa={prior_qa}, seed_questions={seed_questions}")
    seed_ids = {q["id"] for q in seed_questions}
    asked_seed_ids = {a["id"] for a in prior_qa if a.get("id") in seed_ids}

    prompt = _build_prompt(function, coverage, seed_questions,
                           asked_seed_ids, prior_qa, questions_asked)

    runner = _get_runner()
    adk_session_id = str(uuid.uuid4())
    await _session_service.create_session(app_name=ADK_APP_NAME, user_id=ADK_USER_ID, session_id=adk_session_id)

    final_event = None
    async for event in runner.run_async(
        user_id=ADK_USER_ID,
        session_id=adk_session_id,
        new_message=types.Content(
            role="user", parts=[types.Part(text=prompt)]),
    ):
        if event.is_final_response():
            final_event = event

    if final_event is None:
        raise RuntimeError(
            f"[interview/{function}] ADK runner produced no final response event.")

    actions = getattr(final_event, "actions", None)
    state_delta = (getattr(actions, "state_delta", None)
                   or {}) if actions else {}
    state_dict = state_delta.get("decision")
    if state_dict is None:
        raw = "".join(
            p.text for p in (final_event.content.parts if final_event.content else []) if p.text and not p.thought
        )
        raise RuntimeError(
            f"[interview/{function}] no 'decision' in state_delta — no parseable NextQuestionDecision.\n"
            f"    raw text: {raw!r}"
        )

    decision = NextQuestionDecision.model_validate(state_dict)

    if decision.source == "generated" and not decision.question_id:
        decision = decision.model_copy(
            update={"question_id": f"gen-{uuid.uuid4().hex[:8]}"})

    log.info(
        "[interview/%s] turn %d: done=%s source=%s question_id=%s",
        function, questions_asked, decision.done, decision.source, decision.question_id,
    )
    return decision


async def record_answer(
    session_id: str,
    question_id: str,
    question: str,
    answer: str,
    function: Function,
    category_hint: str,
    source: Literal["seed", "generated"],
    importance: int = 2,
) -> None:
    """Writes to sessions/{sid}/answers/{question_id} — same collection/shape
    agent_base._fetch_answers already reads, so live-chat answers feed scoring
    identically to preseed, no changes needed there."""
    client = _get_firestore_client()
    ref = client.collection("sessions").document(
        session_id).collection("answers").document(question_id)
    provenance = _SOURCE_TO_PROVENANCE[source]
    await ref.set({
        "id": question_id,
        "question": question,
        "answer": answer,
        "function": function,
        "category_hint": category_hint,
        "provenance": provenance.value,
        "importance": importance,
        "answered_at": datetime.now(timezone.utc),
    })
    log.info("[interview/%s] recorded answer %s (provenance=%s)",
             function, question_id, provenance.value)


async def list_all_answers(session_id: str) -> list[dict]:
    """Every answer across every Function, oldest first — reconstructs a session's
    full chat history (the UI's Chat view uses this to rebuild the transcript when
    a session is reopened, since nothing about it lives only in Streamlit state).
    Records written before answered_at existed sort first (missing key ~ None)."""
    client = _get_firestore_client()
    coll = client.collection("sessions").document(
        session_id).collection("answers")
    answers = [snap.to_dict() async for snap in coll.stream()]
    answers.sort(key=lambda a: a.get("answered_at")
                 or datetime.min.replace(tzinfo=timezone.utc))
    return answers


async def decide_next_question_auto(session_id: str) -> tuple[Function | None, NextQuestionDecision]:
    """Cross-Function meta-decision — the UI never picks a Function itself. For
    every Function with a live agent, compute its top per-Subcategory need_score
    (same formula _build_prompt already uses internally: category_importance /
    (1 + coverage)), skip any Function already at MAX_QUESTIONS, and delegate to
    the existing decide_next_question() for whichever Function is neediest.
    decide_next_question() itself is untouched — this only decides which Function
    to call it for, so anything calling it directly with an explicit Function
    (tests, test_commands.md) keeps working unchanged."""
    from csf_specialists.agents import AGENTS  # local import — csf_coordinator.coordinator does the same

    best_function: Function | None = None
    best_score = -1.0
    for function in AGENTS:
        prior_qa = await _fetch_answers(session_id, function)
        if len(prior_qa) >= MAX_QUESTIONS:
            continue
        coverage = await _compute_coverage(session_id, function)
        rubric = load_rubric(function)
        top_need = max(
            (
                cat.importance / (1 + coverage.get(sub.subcategory_id, 0))
                for cat_code, cat in rubric.categories.items()
                for sub in examples_for_category(function, cat_code)
            ),
            default=0.0,
        )
        if top_need > best_score:
            best_score = top_need
            best_function = function

    if best_function is None:
        return None, NextQuestionDecision(done=True, reasoning="every Function has hit its question cap")

    decision = await decide_next_question(session_id, best_function)
    return best_function, decision
