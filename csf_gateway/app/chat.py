"""
Interview chat endpoints — conversational question/answer loop backed by
csf_coordinator.interview (the Interview Director, ADK-based).

`function` on /next is optional. Pass ?function=identify to force a specific
Function (used by tests, test_commands.md). Omit it — the normal UI path — and
the server picks the neediest Function itself via decide_next_question_auto,
so callers never have to know which Function a question is about.

Contract (docs/lld.md §4, +function, +history):
  POST /sessions/{sid}/chat/next[?function=govern]  -> {question_id, question, category_hint} | {done: true}
  POST /sessions/{sid}/chat/answer  body: {question_id, answer} -> {stored: true, next_available: bool}
  POST /sessions/{sid}/chat/finish  -> {done: true}
  GET  /sessions/{sid}/chat/history -> full past Q&A, oldest first
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from csf_coordinator import interview
from csf_coordinator.interview import MAX_QUESTIONS
from csf_specialists.agents import AGENTS

from .csf_catalog import Function
from .schema import ChatAnswerInput, ChatNextResponse, ChatQuestion, PendingQuestion
from .sessions import SESSIONS_COLLECTION, _client_get, get_session

log = logging.getLogger("csf-gateway.chat")

router = APIRouter(prefix="/sessions/{session_id}/chat", tags=["chat"])


async def _save_session(session) -> None:
    doc_ref = _client_get().collection(SESSIONS_COLLECTION).document(session.session_id)
    await doc_ref.set(session.model_dump())


@router.post("/next", response_model=ChatNextResponse)
async def chat_next(session_id: str, function: Function | None = None) -> ChatNextResponse:
    """
    Ask the Interview Director for the next question (or done).

    `function` omitted (the normal path): the server decides which Function
    needs a question most via decide_next_question_auto. Pass it explicitly to
    force a specific Function instead (tests, test_commands.md).

    Persists the pending question (and whichever Function it turned out to be
    about) on the session so /chat/answer can record it correctly without the
    caller needing to pass function again.
    """
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    # A question is already pending (unanswered) — return it as-is rather than
    # recomputing. Without this, a duplicate /next call (e.g. a client retry
    # or a double rerun) would re-run decide_next_question_auto against
    # unchanged coverage and, if the LLM's decision isn't perfectly
    # deterministic, could silently swap out an unanswered pending question.
    pending = session.chat_state.pending
    if pending is not None:
        return ChatNextResponse(
            done=False,
            question=ChatQuestion(
                question_id=pending.question_id,
                question=pending.question,
                category_hint=pending.category_hint,
            ),
        )

    if function is not None:
        if function not in AGENTS:
            raise HTTPException(status_code=400, detail=f"no specialist agent registered for function={function!r}")
        decision = await interview.decide_next_question(session_id, function)
    else:
        function, decision = await interview.decide_next_question_auto(session_id)

    if function is None or decision.done or decision.question is None:
        session.chat_state.done = True
        session.chat_state.pending = None
        await _save_session(session)
        return ChatNextResponse(done=True)

    session.chat_state.pending = PendingQuestion(
        question_id=decision.question_id,
        question=decision.question,
        category_hint=decision.category_hint or "",
        function=function,
        source=decision.source or "generated",
    )
    await _save_session(session)

    return ChatNextResponse(
        done=False,
        question=ChatQuestion(
            question_id=decision.question_id,
            question=decision.question,
            category_hint=decision.category_hint or "",
        ),
    )


@router.post("/answer")
async def chat_answer(session_id: str, payload: ChatAnswerInput) -> dict:
    """Record the answer to whatever question is currently pending."""
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    pending = session.chat_state.pending
    if pending is None or pending.question_id != payload.question_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"no pending question with id {payload.question_id!r} — "
                f"call POST /chat/next first"
            ),
        )

    await interview.record_answer(
        session_id=session_id,
        question_id=pending.question_id,
        question=pending.question,
        answer=payload.answer,
        function=pending.function,
        category_hint=pending.category_hint,
        source=pending.source,
        importance=pending.importance,
    )

    session.chat_state.questions_asked += 1
    session.chat_state.pending = None
    await _save_session(session)

    return {"stored": True, "next_available": session.chat_state.questions_asked < MAX_QUESTIONS}


@router.post("/finish")
async def chat_finish(session_id: str) -> dict:
    """Early opt-out — mark the interview done regardless of coverage."""
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    session.chat_state.done = True
    session.chat_state.pending = None
    await _save_session(session)
    return {"done": True}


@router.get("/history")
async def chat_history(session_id: str) -> list[dict]:
    """Full past Q&A for this session, oldest first, across every Function —
    lets the UI rebuild the chat transcript when a session is reopened."""
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return await interview.list_all_answers(session_id)
