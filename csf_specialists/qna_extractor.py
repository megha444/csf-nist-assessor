"""
QnA document extractor — turns an arbitrary already-completed questionnaire
document (Word/PDF/Excel, already parsed to markdown by the ingest parsers)
into PreseedRecord-shaped Q&A pairs via one ADK structured-output call,
classified against the full CSF catalog (all 6 Functions, not just
csf_specialists.agents.AGENTS — a Function without a live agent yet just has
its extracted answers sit ready for when that agent exists).

One call per document, no chunking — proportionate for a typical few-page
completed questionnaire. A very large source document may need the caller to
split it first; not built here.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import FUNCTION_NAMES, Function
from csf_gateway.app.llm import gemini_model
from csf_gateway.app.schema import PreseedRecord, Provenance
from csf_specialists.loaders import load_implementation_examples

log = logging.getLogger("csf-specialists.qna_extractor")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "qna_extract.txt"

ADK_APP_NAME = "csf-specialists-qna-extractor"
ADK_USER_ID = "csf-assessor"
ADK_OUTPUT_KEY = "extraction_result"


class ExtractedQA(BaseModel):
    question: str
    answer: str
    function: Function
    category_hint: str = Field(..., description="Subcategory id this pair most directly answers, e.g. 'GV.SC-04'")
    importance: int = Field(2, ge=1, le=3)


class QnAExtractionResult(BaseModel):
    records: list[ExtractedQA]


def _build_catalog_block() -> str:
    lines: list[str] = []
    for fn, name in FUNCTION_NAMES.items():
        lines.append(f"\n## {name} ({fn})")
        for sub_id, meta in sorted(load_implementation_examples(fn).items()):
            lines.append(f"  {sub_id}: {meta.name}")
    return "\n".join(lines)


_llm_agent: LlmAgent | None = None
_session_service: InMemorySessionService | None = None
_runner: Runner | None = None


def _get_runner() -> Runner:
    global _llm_agent, _session_service, _runner
    if _runner is None:
        s = get_settings()
        _llm_agent = LlmAgent(
            name="qna_extractor",
            model=gemini_model(s.gemini_flash_model),
            output_schema=QnAExtractionResult,
            output_key=ADK_OUTPUT_KEY,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=8000),
                max_output_tokens=24000,
            ),
        )
        _session_service = InMemorySessionService()
        _runner = Runner(agent=_llm_agent, app_name=ADK_APP_NAME, session_service=_session_service)
    return _runner


async def extract_qna(document_text: str) -> list[PreseedRecord]:
    """One structured-output call over the whole document. Returns ready-to-
    preseed PreseedRecords — stable ids are generated here, never by the LLM."""
    prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8").format(
        catalog_block=_build_catalog_block(),
        document_text=document_text,
    )

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
        raise RuntimeError("[qna_extractor] ADK runner produced no final response event.")

    actions = getattr(final_event, "actions", None)
    state_delta = (getattr(actions, "state_delta", None) or {}) if actions else {}
    state_dict = state_delta.get(ADK_OUTPUT_KEY)
    if state_dict is None:
        raise RuntimeError("[qna_extractor] no extraction_result in state_delta — no parseable output.")

    result = QnAExtractionResult.model_validate(state_dict)
    log.info("[qna_extractor] extracted %d Q&A pairs", len(result.records))

    return [
        PreseedRecord(
            id=f"qna-{uuid.uuid4().hex[:8]}",
            question=r.question,
            answer=r.answer,
            function=r.function,
            category_hint=r.category_hint,
            provenance=Provenance.pre_seeded,
            importance=r.importance,
        )
        for r in result.records
    ]
