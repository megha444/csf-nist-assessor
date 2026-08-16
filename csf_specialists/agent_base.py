"""
Base class for CSF Function specialist agents.

One instance per Function. Owns the rubric (Sakina-authored) and NIST
implementation examples (extracted from CSF 2.0-Implementation_Examples.xlsx).

Public API:
    async score_category(category_code, session_id, run_id=None) -> ScoreOutput

    - Retrieves top-5 evidence chunks from Qdrant (session-scoped)
    - Fetches interview answers from Firestore filtered to this Function
    - Assembles the scoring prompt (rubric + examples + evidence + Q&A)
    - Calls Gemini 3.5 Flash with strict response_schema=ScoreOutput
    - Optionally persists to Firestore at sessions/{sid}/runs/{rid}/scores/{cat_id}
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai
from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.genai import types

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import CATEGORIES
from csf_gateway.app.ingest.embedder import embed_query
from csf_gateway.app.ingest.vector_store import search_session
from csf_gateway.app.schema import EvidenceCitation, ScoreOutput
from csf_specialists.loaders import (
    Category,
    FunctionRubric,
    SubcategoryExamples,
    examples_for_category,
    load_rubric,
)

log = logging.getLogger("csf-specialists")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "score.txt"

# Module-level Gemini + Firestore clients — reused across score_category calls.
_genai_client: genai.Client | None = None
_firestore_client: AsyncClient | None = None


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        s = get_settings()
        _genai_client = genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,
        )
    return _genai_client


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

    def __post_init__(self) -> None:
        self.rubric = load_rubric(self.function)
        self.examples_by_category = {
            code: examples_for_category(self.function, code)
            for code in self.rubric.categories
        }
        self.prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
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
        """
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

        # 4. Gemini structured-output call
        s = get_settings()
        client = _get_genai_client()
        response = await client.aio.models.generate_content(
            model=s.gemini_flash_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=ScoreOutput,
                # Gemini 3.x is a thinking model. Left uncapped, `thoughts_token_count`
                # can hit 20k+ on the same prompt and truncate the JSON output mid-object
                # → response.parsed=None. Cap thinking to a fixed budget and give the
                # structured output generous headroom so it always fits.
                thinking_config=types.ThinkingConfig(thinking_budget=8000),
                max_output_tokens=24000,
            ),
        )

        result: ScoreOutput | None = response.parsed
        if result is None:
            usage = response.usage_metadata
            raw = response.text or ""
            # Try a manual parse to surface WHICH field the schema rejected.
            manual_err = ""
            try:
                ScoreOutput.model_validate_json(raw)
            except Exception as ve:
                manual_err = f"\n    manual validate: {type(ve).__name__}: {str(ve)[:400]}"
            raise RuntimeError(
                f"[{self.function}/{category_code}] Gemini returned no parseable ScoreOutput.\n"
                f"    usage: prompt={getattr(usage, 'prompt_token_count', '?')} "
                f"thoughts={getattr(usage, 'thoughts_token_count', '?')} "
                f"candidates={getattr(usage, 'candidates_token_count', '?')}\n"
                f"    raw len: {len(raw)} chars\n"
                f"    raw text: {raw!r}"
                f"{manual_err}"
            )

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

        usage = response.usage_metadata
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
