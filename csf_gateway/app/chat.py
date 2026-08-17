"""
Interview chat endpoints — conversational question/answer loop backed by
csf_coordinator.interview (the Interview Director, ADK-based).

`function` is an optional query param on /next (defaults to "govern" for
backward compat with existing sessions/tests) — pass ?function=identify to
interview about a different Function. interview.py's logic was already
Function-generic; this just stops chat.py from hardcoding "govern" on the call.

Contract (docs/lld.md §4, +function):
  POST /sessions/{sid}/chat/next?function=govern  -> {question_id, question, category_hint} | {done: true}
  POST /sessions/{sid}/chat/answer  body: {question_id, answer} -> {stored: true, next_available: bool}
  POST /sessions/{sid}/chat/finish  -> {done: true}
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
async def chat_next(session_id: str, function: Function = "govern") -> ChatNextResponse:
    """
    Ask the Interview Director for the next question (or done) for `function`.
    Persists the pending question on the session so /chat/answer can record it
    correctly without the caller needing to pass function again.
    """
    if function not in AGENTS:
        raise HTTPException(status_code=400, detail=f"no specialist agent registered for function={function!r}")

    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    decision = await interview.decide_next_question(session_id, function)

    if decision.done or decision.question is None:
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
