"""
Pydantic DTOs used across the FastAPI routes and internal pipelines.

Mirrors LLD §5. Fields that specialists / coordinator will read (e.g.
`ScoreOutput`, `PreseedRecord`) are included even though this phase doesn't
write them yet — keeps future services import-compatible from day one.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .csf_catalog import Function  # Literal alias
from .doctype_taxonomy import DocType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_org(name: str) -> str:
    """
    Convert a free-form org name to a stable, filesystem-safe slug.
    'Northwind Financial' → 'northwind-financial'
    'AT&T Inc.'           → 'at-t-inc'
    """
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "unknown-org"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IngestStatus(str, Enum):
    pending = "pending"
    parsing = "parsing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class SessionStatus(str, Enum):
    collecting_inputs = "collecting_inputs"
    running = "running"
    ready_for_report = "ready_for_report"
    complete = "complete"


class RunStatus(str, Enum):
    dispatched = "dispatched"
    partial = "partial"
    ready_for_report = "ready_for_report"
    complete = "complete"
    failed = "failed"


class Provenance(str, Enum):
    pre_seeded = "pre_seeded"
    live_chat = "live_chat"
    live_chat_generated = "live_chat_generated"


class Defensibility(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class PendingQuestion(BaseModel):
    """The question a session is currently awaiting an answer for. Persisted on
    SessionState.chat_state so /chat/answer can record it correctly (question text,
    provenance source, importance, which Function it belongs to) without the
    client needing to echo it back."""
    question_id: str
    question: str
    category_hint: str
    function: Function
    source: Literal["seed", "generated"]
    importance: int = 2


class ChatState(BaseModel):
    questions_asked: int = 0
    done: bool = False
    pending: PendingQuestion | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    session_id: str
    # demo default; overridable via CreateSessionRequest
    target_org: str = "Northwind Financial"
    # stable slug of target_org; empty on legacy rows
    org_id: str = ""
    status: SessionStatus = SessionStatus.collecting_inputs
    created_at: datetime
    doc_ids: list[str] = Field(default_factory=list)
    preseed_loaded: bool = False
    chat_state: ChatState = Field(default_factory=ChatState)
    run_id: str | None = None


class CreateSessionRequest(BaseModel):
    """Optional body for POST /sessions. Omit to use the demo default."""
    target_org: str = Field(
        default="Northwind Financial",
        description="Name of the organization being assessed.",
        min_length=1,
        max_length=200,
    )
    org_id: str | None = Field(
        default=None,
        description=(
            "Optional stable identifier for the organization. If omitted, derived "
            "from target_org via slugification (e.g. 'Acme Corp' → 'acme-corp'). "
            "Pass this explicitly when consistency across sessions matters "
            "(e.g. tying multiple assessments to the same underlying tenant)."
        ),
        max_length=100,
    )

    @field_validator("org_id")
    @classmethod
    def _validate_org_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Enforce slug-safe: lowercase, alphanumeric + dash
        if not re.fullmatch(r"[a-z0-9-]+", v):
            raise ValueError(
                "org_id must be lowercase alphanumeric with dashes only")
        return v


# ---------------------------------------------------------------------------
# Documents + chunks
# ---------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    doc_id: str
    filename: str
    doc_type: DocType = DocType.other
    org_id: str = ""                      # inherited from session on write
    page_count: int = 0
    chunk_count: int = 0
    uploaded_at: datetime
    ingest_status: IngestStatus = IngestStatus.pending
    failure_reason: str | None = None
    gcs_uri: str
    content_hash: str


class ChunkRecord(BaseModel):
    chunk_id: str
    text: str
    section_title: str = ""
    page_start: int = 1
    page_end: int = 1
    chunk_index: int
    token_count: int
    vector_datapoint_id: str
    candidate_categories: list[str] = Field(default_factory=list)


class UploadedFile(BaseModel):
    filename: str
    doc_id: str
    was_duplicate: bool = False


class DocumentUploadResponse(BaseModel):
    files: list[UploadedFile]
    status: Literal["processing", "complete"] = "processing"


class DocumentStatusResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    doc_id: str
    ingest_status: IngestStatus
    progress_pct: int = Field(0, ge=0, le=100)
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Answers (pre-seed + live chat) — Stage 2/3
# ---------------------------------------------------------------------------


class PreseedRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    question: str
    answer: str
    function: Function
    category_hint: str
    provenance: Provenance = Provenance.pre_seeded
    importance: int = Field(2, ge=1, le=3)


class ChatQuestion(BaseModel):
    question_id: str
    question: str
    category_hint: str
    is_followup: bool = False
    parent_question_id: str | None = None


class ChatAnswerInput(BaseModel):
    question_id: str
    answer: str


class ChatNextResponse(BaseModel):
    """POST /sessions/{sid}/chat/next response — {question_id, question, category_hint}
    | {done: true} per docs/lld.md §4, collapsed into one typed model."""
    done: bool = False
    question: ChatQuestion | None = None


# ---------------------------------------------------------------------------
# Agent I/O — Stage 5/6 (specialists + judge)
# ---------------------------------------------------------------------------


class EvidenceCitation(BaseModel):
    doc_id: str
    chunk_id: str
    doc_title: str
    section: str = ""
    page_start: int = 1
    page_end: int = 1
    snippet: str  # UI truncates at render — no Pydantic-side length cap (LLM
    # occasionally emits 400-600 chars and cosmetic rejection breaks
    # the whole ScoreOutput parse for a stochastic reason)


class SubcategoryScore(BaseModel):
    """
    Per-Subcategory scoring output from the specialist agent. Populated for EVERY
    Subcategory under the Category (not just gaps). Category CMMI is derived as
    the deterministic round(mean) of these. Templates are keyed by
    (subcategory_id, current→next_level).  See ADR-0007.
    """
    subcategory_id: str = Field(..., description="e.g. 'PR.AA-05'")
    cmmi_level: int = Field(..., ge=1, le=5,
                            description="1=Initial through 5=Optimising, applied at Subcategory granularity using the Category rubric text as a maturity scale")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_status: Literal["absent", "partial", "present"]
    expected_practice: str = Field(
        ..., description="One representative NIST Implementation Example text describing what a mature org would do"
    )
    observations: str = Field(
        ..., description="1-2 sentences, factual: what the evidence shows this org actually does today for this Subcategory"
    )
    gap: str = Field(
        ..., description="1-2 sentences: specifically what is missing relative to the next maturity level — not the generic NIST example, the delta for THIS org's evidence"
    )
    recommendation: str = Field(
        ..., description="1-2 sentences: concrete incremental action(s) to move from the current cmmi_level to the next 1-2 levels only (never 'reach Level 5'), grounded in the rubric level text and NIST examples above"
    )


class ScoreOutput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category_id: str
    function: Function
    cmmi_level: int = Field(..., ge=1, le=5, description="Category-level CMMI. Deterministically overridden by the agent to round(mean(subcategory_scores.cmmi_level)) when subcategory_scores is non-empty (see ADR-0007).")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)
    interview_evidence: list[str] = Field(default_factory=list)  # answer_ids
    reasoning: str
    no_doc_evidence: bool = False
    subcategory_scores: list[SubcategoryScore] = Field(  # ADR-0007 (revised)
        default_factory=list,
        description="One score per Subcategory under this Category. Category cmmi_level is round(mean(...)) of these.",
    )


class TierResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    function: Function
    tier: int = Field(..., ge=1, le=4)
    avg_cmmi: float
    category_count: int
    insufficient_evidence_count: int = 0


class JudgeResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category_id: str
    defensibility: Defensibility
    judge_notes: str


# ---------------------------------------------------------------------------
# Report narrative — Stage 7 (PDF report)
# ---------------------------------------------------------------------------


class FunctionSummary(BaseModel):
    """One Function's finding, in the business register the exec summary uses."""
    model_config = ConfigDict(use_enum_values=True)

    function: Function
    summary: str = Field(
        ..., description="1-2 sentences a non-technical Board member would understand: what this Function's practice actually looks like at this org today"
    )


class ImprovementTheme(BaseModel):
    """One cross-cutting improvement area, grounded in real Subcategory gaps."""

    title: str = Field(..., description="Short noun phrase, e.g. 'Privileged access on legacy infrastructure'")
    body: str = Field(..., description="2-3 sentences: what the gap is and why it matters commercially. No jargon.")
    refs: list[str] = Field(
        default_factory=list, description="Subcategory ids this theme is grounded in, e.g. ['PR.AA-05']"
    )


class ReportNarrative(BaseModel):
    """LLM-synthesised prose for the PDF report's Executive Summary and Areas of
    Improvement pages. Deliberately narrow: every number in the report still comes
    from the persisted scores, and this model carries only the language wrapped
    around them. Persisted at sessions/{sid}/runs/{rid}/report/narrative so a
    re-render never re-bills a Gemini call.

    Lists rather than dicts throughout — Gemini's structured-output schema has no
    clean representation for an open-ended mapping, so `function_summaries` is a
    list keyed by its own `function` field instead of a dict[Function, str]."""

    intro: str = Field(
        ..., description="One paragraph (4-6 sentences) opening the executive summary: who the org is, how it manages cyber risk, and where its strongest practice and best opportunities lie."
    )
    function_summaries: list[FunctionSummary] = Field(
        default_factory=list, description="One entry per assessed Function, in Govern->Recover order"
    )
    improvement_themes: list[ImprovementTheme] = Field(
        default_factory=list, description="4-6 themes, most material first"
    )
