"""
Function-level aggregation — Category CMMI scores → Tier.

Implements `docs/lld.md §8.2` (`aggregate_function`) for real. Category-weighted:
each of a Function's Categories counts equally regardless of how many
Subcategories NIST split it into. This matches ADR-0002 (Category is the
scoring/reporting unit) and is what Judge + report consume downstream.

Deliberately NOT Subcategory-weighted (pooling every Subcategory score across
Categories) — that was an ad hoc calculation from Aug 15, never part of the
design, and disagrees with this algorithm by a full Tier on real data (Govern
on session 23a53272-...: 3.333→Tier 3 here vs. 2.613→Tier 2 pooled). See
docs/HANDOFF.md §8 and docs/govern_build_tasks.md's follow-ups for the history.
"""
from __future__ import annotations

import logging

from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import Function
from csf_gateway.app.schema import TierResult

log = logging.getLogger("csf-specialists.aggregate")

# Below this, a Category/Subcategory score counts as "insufficient evidence"
# rather than a scorable data point. Single source of truth — report/UI layers
# import this rather than re-hardcoding 0.6.
CONFIDENCE_THRESHOLD = 0.6

_firestore_client: AsyncClient | None = None
_firestore_loop = None  # event loop the cached client is bound to (loop-aware caching)


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


def cmmi_to_tier(avg: float) -> int:
    if avg < 2.0:
        return 1
    if avg < 3.0:
        return 2
    if avg < 4.0:
        return 3
    return 4


async def aggregate_function(session_id: str, run_id: str, function: Function) -> TierResult:
    """
    Roll up one Function's persisted Category scores into a Tier.

    Reads `sessions/{sid}/runs/{rid}/scores`, filters to this Function, and
    computes avg_cmmi as the mean of `cmmi_level` across Categories with
    confidence >= 0.6 ("scorable"). Categories below that threshold count
    toward `insufficient_evidence_count` but not the average. If 2+ Categories
    are insufficient, the resulting Tier is knocked down by one (floor Tier 1)
    — a whole Function shouldn't read as mature when a third or more of its
    Categories couldn't be scored with confidence.
    """
    client = _get_firestore_client()
    coll = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("scores")
    )
    query = coll.where(filter=FieldFilter("function", "==", function))
    scores = [snap.to_dict() async for snap in query.stream()]

    if not scores:
        raise ValueError(
            f"no scores found at sessions/{session_id}/runs/{run_id}/scores for function={function!r}"
        )

    scorable = [s for s in scores if s["confidence"] >= CONFIDENCE_THRESHOLD]
    insufficient = len(scores) - len(scorable)
    avg_cmmi = (sum(s["cmmi_level"] for s in scorable) / len(scorable)) if scorable else 1.0

    tier = cmmi_to_tier(avg_cmmi)
    if insufficient >= 2:
        tier = max(1, tier - 1)

    result = TierResult(
        function=function,
        tier=tier,
        avg_cmmi=avg_cmmi,
        category_count=len(scores),
        insufficient_evidence_count=insufficient,
    )
    log.info(
        "[%s] aggregated %d Categories (scorable=%d, insufficient=%d) -> avg_cmmi=%.3f Tier=%d",
        function, len(scores), len(scorable), insufficient, avg_cmmi, tier,
    )
    return result


async def persist_tier(session_id: str, run_id: str, result: TierResult) -> None:
    """Write to sessions/{sid}/runs/{rid}/tiers/{function}."""
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("tiers").document(result.function)
    )
    await ref.set(result.model_dump())
    log.info(
        "[%s] persisted -> sessions/%s/runs/%s/tiers/%s",
        result.function, session_id, run_id, result.function,
    )
