"""
Base class for CSF Function specialist agents.

One instance per Function. Owns the rubric (Sakina-authored) and NIST
implementation examples (extracted from CSF 2.0-Implementation_Examples.xlsx).

Public API:
    async score_category(category_code, session_id, run_id=None) -> ScoreOutput

    - Retrieves top-5 evidence chunks from Qdrant (session-scoped)
    - Fetches interview answers from Firestore filtered to this Function
    - Assembles the scoring prompt (rubric + examples + evidence + Q&A)
    - Calls Gemini 3.5 Flash via a Google ADK LlmAgent, output_schema=ScoreOutput
    - Optionally persists to Firestore at sessions/{sid}/runs/{rid}/scores/{cat_id}
"""
from __future__ import annotations

import logging
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.genai import types

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import CATEGORIES
from csf_gateway.app.ingest.embedder import embed_query
from csf_gateway.app.ingest.vector_store import search_session
from csf_gateway.app.llm import gemini_model
from csf_gateway.app.schema import EvidenceCitation, ScoreOutput
from csf_gateway.app.tracing import get_tracer

_tracer = get_tracer("csf-specialists")
from csf_specialists.loaders import (
    Category,
    FunctionRubric,
    SubcategoryExamples,
    examples_for_category,
    load_rubric,
)

log = logging.getLogger("csf-specialists")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "score.txt"

# ADK Runner bookkeeping — one session per score_category call (stateless,
# single-shot structured generation; no cross-call conversation needed).
ADK_APP_NAME = "csf-specialists"
ADK_USER_ID = "csf-assessor"
ADK_OUTPUT_KEY = "score_result"

# Module-level Firestore client — reused across score_category calls.
_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(
            project=s.google_cloud_project,
            database=s.firestore_database,
        )
    return _firestore_client


@dataclass
class SpecialistAgent:
    """
    One specialist per CSF Function. Reads rubric + implementation examples
    at construction time (fail-fast if either is missing).
    """
    function: str  # "govern", "identify", "protect", "detect", "respond", "recover"

    # Populated in __post_init__
    rubric: FunctionRubric = field(init=False)
    examples_by_category: dict[str, list[SubcategoryExamples]] = field(init=False)
    prompt_template: str = field(init=False)
    _llm_agent: LlmAgent = field(init=False, repr=False)
    _session_service: InMemorySessionService = field(init=False, repr=False)
    _runner: Runner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.rubric = load_rubric(self.function)
        self.examples_by_category = {
            code: examples_for_category(self.function, code)
            for code in self.rubric.categories
        }
        self.prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

        s = get_settings()
        self._llm_agent = LlmAgent(
            name=f"{self.function}_specialist",
            model=gemini_model(s.gemini_flash_model),
            output_schema=ScoreOutput,
            output_key=ADK_OUTPUT_KEY,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.1,
                # Gemini 3.x is a thinking model. Left uncapped, `thoughts_token_count`
                # can hit 20k+ on the same prompt and truncate the JSON output mid-object.
                # Cap thinking to a fixed budget and give the structured output generous
                # headroom so it always fits. (response_mime_type/response_schema are NOT
                # set here — ADK's LlmAgent forbids that placement; output_schema= above
                # is the ADK-native equivalent.)
                thinking_config=types.ThinkingConfig(thinking_budget=8000),
                max_output_tokens=24000,
            ),
        )
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=self._llm_agent,
            app_name=ADK_APP_NAME,
            session_service=self._session_service,
        )
        log.info(
            "SpecialistAgent(%s) ready: %d Categories, %d Subcategories total",
            self.function,
            len(self.rubric.categories),
            sum(len(v) for v in self.examples_by_category.values()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def score_category(
        self,
        category_code: str,
        session_id: str,
        run_id: str | None = None,
    ) -> ScoreOutput:
        """
        Score one Category for one session.

        If `run_id` is provided, the returned ScoreOutput is also persisted to
        `sessions/{sid}/runs/{rid}/scores/{cat}`. If None, no Firestore write —
        useful for adhoc testing (Phase F).

        Thin span-wrapping shim around _score_category_impl (Agent Observability
        v1) — kept separate so the actual scoring logic below never had to be
        reindented under a `with` block.
        """
        with _tracer.start_as_current_span("csf.specialist.score_category") as span:
            span.set_attribute("csf.function", self.function)
            span.set_attribute("csf.category_id", category_code)
            span.set_attribute("csf.session_id", session_id)
            if run_id:
                span.set_attribute("csf.run_id", run_id)
            result = await self._score_category_impl(category_code, session_id, run_id)
            span.set_attribute("csf.cmmi_level", result.cmmi_level)
            span.set_attribute("csf.confidence", result.confidence)
            span.set_attribute("csf.no_doc_evidence", result.no_doc_evidence)
            return result

    async def _score_category_impl(
        self,
        category_code: str,
        session_id: str,
        run_id: str | None = None,
    ) -> ScoreOutput:
        self._assert_owns(category_code)
        cat = self.rubric.categories[category_code]

        # 1. Retrieval — build query, embed, search Qdrant (session-scoped).
        # Adaptive top_k: max(10, 2 × subcategory count). Reasoning: CSF scoring
        # is multi-hop (need multiple evidence pieces per Subcategory), and Categories
        # with 7-10 Subcategories need proportionally more evidence than 2-3 Sub ones.
        # See ADR-0008 / govern_build_tasks.md.
        query_text = self._build_query(category_code)
        n_subs = len(self.examples_by_category.get(category_code, []))
        top_k = max(10, 2 * n_subs)
        log.info(
            "[%s/%s] retrieval query: %r (n_subs=%d → top_k=%d)",
            self.function, category_code, query_text[:120], n_subs, top_k,
        )
        query_vec = await embed_query(query_text)
        chunks = search_session(session_id, query_vec, top_k=top_k)
        log.info("[%s/%s] retrieved %d chunks", self.function, category_code, len(chunks))

        # 2. Interview answers for this Function
        answers = await self._fetch_answers(session_id)
        log.info("[%s/%s] fetched %d interview answers", self.function, category_code, len(answers))

        # 3. Prompt assembly
        prompt = self._build_prompt(category_code, chunks, answers)

        # 4. ADK structured-output call. One fresh session per call — this is a
        # stateless, single-shot structured generation, not a multi-turn conversation.
        adk_session_id = str(uuid.uuid4())
        await self._session_service.create_session(
            app_name=ADK_APP_NAME, user_id=ADK_USER_ID, session_id=adk_session_id,
        )

        final_event = None
        last_text_seen = ""
        try:
            async for event in self._runner.run_async(
                user_id=ADK_USER_ID,
                session_id=adk_session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                if event.content and event.content.parts:
                    text = "".join(
                        p.text for p in event.content.parts if p.text and not p.thought
                    )
                    if text:
                        last_text_seen = text
                if event.is_final_response():
                    final_event = event
        except Exception as e:
            raise RuntimeError(
                f"[{self.function}/{category_code}] ADK runner raised during structured-output "
                f"generation: {type(e).__name__}: {str(e)[:400]}\n"
                f"    last raw text seen ({len(last_text_seen)} chars): {last_text_seen!r}"
            ) from e

        if final_event is None:
            raise RuntimeError(
                f"[{self.function}/{category_code}] ADK runner produced no final response event."
            )

        usage = final_event.usage_metadata
        actions = getattr(final_event, "actions", None)
        state_delta = (getattr(actions, "state_delta", None) or {}) if actions else {}
        state_dict = state_delta.get(ADK_OUTPUT_KEY)

        if state_dict is None:
            raise RuntimeError(
                f"[{self.function}/{category_code}] ADK agent returned a final event but no "
                f"{ADK_OUTPUT_KEY!r} in state_delta — no parseable ScoreOutput.\n"
                f"    usage: prompt={getattr(usage, 'prompt_token_count', '?')} "
                f"thoughts={getattr(usage, 'thoughts_token_count', '?')} "
                f"candidates={getattr(usage, 'candidates_token_count', '?')}\n"
                f"    raw len: {len(last_text_seen)} chars\n"
                f"    raw text: {last_text_seen!r}"
            )

        result = ScoreOutput.model_validate(state_dict)

        # 5. Deterministic Category CMMI = round(mean(subcategory scores)). See ADR-0007.
        #    LLM's own top-level cmmi_level is treated as a hint; the mean is authoritative
        #    so the aggregation math is transparent + auditable.
        if result.subcategory_scores:
            computed = round(statistics.mean(s.cmmi_level for s in result.subcategory_scores))
            if computed != result.cmmi_level:
                log.info(
                    "[%s/%s] LLM Category cmmi=%d, computed mean=%d — using mean",
                    self.function, category_code, result.cmmi_level, computed,
                )
                result = result.model_copy(update={"cmmi_level": computed})

        log.info(
            "[%s/%s] scored CMMI=%d conf=%.2f subs=%d tokens in=%s out=%s",
            self.function, category_code,
            result.cmmi_level, result.confidence, len(result.subcategory_scores),
            getattr(usage, "prompt_token_count", "?"),
            getattr(usage, "candidates_token_count", "?"),
        )

        # 6. Optional persistence
        if run_id is not None:
            await self._persist_score(session_id, run_id, result)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_owns(self, category_code: str) -> None:
        if category_code not in self.rubric.categories:
            owned = ", ".join(self.rubric.categories)
            raise ValueError(
                f"SpecialistAgent({self.function!r}) does not own Category {category_code!r}. "
                f"Owned Categories: {owned}"
            )

    def _build_query(self, category_code: str) -> str:
        """
        Compose a retrieval query from Category name + Subcategory names + a
        few catalog keywords. Bias toward the semantic terms most likely to
        appear in policy language.
        """
        cat = self.rubric.categories[category_code]
        parts: list[str] = [cat.name]

        # Include Subcategory names (they carry the specific practice language)
        for sub in self.examples_by_category.get(category_code, [])[:6]:
            parts.append(sub.name)

        # Plus a handful of curated keywords from csf_catalog (Category-level tags)
        catalog_entry = CATEGORIES.get(category_code)
        if catalog_entry:
            parts.extend(list(catalog_entry.keywords[:8]))

        return " ".join(parts)

    async def _fetch_answers(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch interview answers for this Function from Firestore."""
        client = _get_firestore_client()
        coll = (
            client.collection("sessions").document(session_id).collection("answers")
        )
        query = coll.where(filter=FieldFilter("function", "==", self.function))
        return [snap.to_dict() async for snap in query.stream()]

    def _build_prompt(
        self,
        category_code: str,
        chunks: list[dict[str, Any]],
        answers: list[dict[str, Any]],
    ) -> str:
        cat = self.rubric.categories[category_code]
        subs = self.examples_by_category.get(category_code, [])

        rubric_block = "\n\n".join(
            f"Level {lvl}: {text}" for lvl, text in sorted(cat.levels.items())
        )

        if subs:
            sub_lines: list[str] = []
            for s in subs:
                sub_lines.append(f"\n{s.subcategory_id}: {s.name}")
                for ex in s.examples:
                    sub_lines.append(f"  - {ex}")
            subs_block = "\n".join(sub_lines).strip()
        else:
            subs_block = "(no NIST examples available for this Category)"

        if chunks:
            chunk_lines: list[str] = []
            for i, h in enumerate(chunks, 1):
                p = h.get("payload", {}) or {}
                snippet = str(p.get("text", "") or "")[:600].replace("\n", " ").strip()
                chunk_lines.append(
                    f'[{i}] doc_type={p.get("doc_type", "?")!r}  '
                    f'section={p.get("section_title", "") or "?"!r}  '
                    f'pages={p.get("page_start")}-{p.get("page_end")}  '
                    f'chunk_id={p.get("chunk_id", h.get("id"))}\n'
                    f'    {snippet}'
                )
            chunks_block = "\n\n".join(chunk_lines)
        else:
            chunks_block = "(no relevant document evidence retrieved for this Category)"

        if answers:
            ans_lines: list[str] = []
            for a in answers:
                qid = a.get("id", "?")
                ans_lines.append(
                    f"Q ({qid}): {a.get('question', '')}\n"
                    f"  A: {a.get('answer', '')}"
                )
            answers_block = "\n\n".join(ans_lines)
        else:
            answers_block = "(no interview answers recorded for this Function yet)"

        return self.prompt_template.format(
            function=self.function,
            category_id=cat.code,
            category_name=cat.name,
            rubric_block=rubric_block,
            subs_block=subs_block,
            chunks_block=chunks_block,
            answers_block=answers_block,
        )

    async def _persist_score(
        self,
        session_id: str,
        run_id: str,
        score: ScoreOutput,
    ) -> None:
        """Write to sessions/{sid}/runs/{rid}/scores/{cat_id}."""
        client = _get_firestore_client()
        ref = (
            client.collection("sessions").document(session_id)
            .collection("runs").document(run_id)
            .collection("scores").document(score.category_id)
        )
        payload = score.model_dump()
        payload["scored_by_agent"] = f"{self.function}_specialist"
        payload["scored_at"] = datetime.now(timezone.utc)
        await ref.set(payload)
        log.info(
            "[%s/%s] persisted → sessions/%s/runs/%s/scores/%s",
            self.function, score.category_id, session_id, run_id, score.category_id,
        )
