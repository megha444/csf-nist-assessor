"""
Memory Bank — persistent cross-session context (Fortified component).

Genuinely different from `runs/{run_id}.snapshot` (a same-run audit record of
what evidence existed when one specific run was dispatched, per
csf_coordinator/steps.py::CreateRunStep) — that never gets read back by
anything. This is real cross-session memory: after a Function is aggregated,
records a compact summary keyed by org_id, so a LATER, separate assessment of
the SAME organization can see what a PRIOR assessment found. Matches Google's
own Memory Bank definition (retrieve -> generate -> insert): a report build
retrieves this history, generates the current run's own summary, and inserts
both so a reader sees "Tier 2 -> Tier 3 since last time" instead of every
assessment reading as a stranger.

Firestore layout: orgs/{org_id}/memory/{function}
  {
    function: "govern",
    history: [
      {run_id, session_id, completed_at, tier, avg_cmmi,
       categories: {category_id: {cmmi_level, top_gap}}},
      ...
    ],
  }

History is append-only, capped at MAX_HISTORY entries (oldest dropped) so it
can't grow unbounded across a long testing/demo session — proportionate for
a hackathon, not meant to be a real production retention policy.

Deliberately NOT wired into the interview director's own prompt yet (making
it actively probe "has this gap been fixed?") — that's real additional scope
weighed against report-visible tracking; see task_list.md's Aug 24 entry for
why report-visible tracking shipped first.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from csf_gateway.app.config import get_settings
from csf_gateway.app.schema import TierResult

log = logging.getLogger("csf-specialists.memory_bank")

MAX_HISTORY = 20

_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


def _worst_subcategory_gap(category_score: dict) -> str:
    """The gap text from whichever Subcategory scored lowest — "here's the
    single most significant weakness in this Category" is a more useful
    one-line memory than the Category's own summary reasoning, which tends
    to restate what's already good alongside what isn't."""
    subs = category_score.get("subcategory_scores") or []
    if not subs:
        return category_score.get("reasoning", "")[:200]
    worst = min(subs, key=lambda s: s["cmmi_level"])
    return f"{worst['subcategory_id']}: {worst.get('gap', '')}"[:200]


async def record_assessment(
    org_id: str,
    function: str,
    session_id: str,
    run_id: str,
    tier_result: TierResult,
) -> None:
    """Append one entry to this org+Function's memory history. Called from
    AggregateStep right after a Tier is computed — reads that Function's own
    just-persisted Category scores directly (a small extra query, kept
    separate from aggregate.py's own read so aggregate_function's existing,
    already-verified return type doesn't need to change for this)."""
    if not org_id:
        log.info("[%s/%s] no org_id on session %s — skipping Memory Bank write", function, run_id, session_id)
        return

    client = _get_firestore_client()
    scores_coll = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id).collection("scores")
    )
    query = scores_coll.where(filter=FieldFilter("function", "==", function))
    category_scores = [snap.to_dict() async for snap in query.stream()]

    entry = {
        "run_id": run_id,
        "session_id": session_id,
        "completed_at": datetime.now(timezone.utc),
        "tier": tier_result.tier,
        "avg_cmmi": tier_result.avg_cmmi,
        "categories": {
            c["category_id"]: {"cmmi_level": c["cmmi_level"], "top_gap": _worst_subcategory_gap(c)}
            for c in category_scores
        },
    }

    mem_ref = client.collection("orgs").document(org_id).collection("memory").document(function)
    snap = await mem_ref.get()
    history = (snap.to_dict() or {}).get("history", []) if snap.exists else []
    history.append(entry)
    history = history[-MAX_HISTORY:]

    await mem_ref.set({"function": function, "history": history})
    log.info(
        "[%s] recorded assessment for org=%s (history now %d entries)",
        function, org_id, len(history),
    )


async def get_prior_assessment(org_id: str, function: str, exclude_run_id: str) -> dict | None:
    """The most recent history entry for this org+Function that ISN'T
    `exclude_run_id` — used by the report layer, which typically runs after
    AggregateStep has already recorded the current run, so the current run's
    own entry is usually already in history by the time a report reads it
    back. None if there's no prior entry (first-ever assessment of this org,
    or this org predates Memory Bank)."""
    history = await get_history(org_id, function)
    prior_entries = [h for h in history if h["run_id"] != exclude_run_id]
    return prior_entries[-1] if prior_entries else None


async def get_history(org_id: str, function: str) -> list[dict]:
    """Full history for one org+Function, oldest first. Empty list if no
    prior memory exists (a brand-new org, or Memory Bank predates this org's
    earliest run) — callers should treat that as "no prior context available",
    not an error."""
    if not org_id:
        return []
    client = _get_firestore_client()
    mem_ref = client.collection("orgs").document(org_id).collection("memory").document(function)
    snap = await mem_ref.get()
    if not snap.exists:
        return []
    return snap.to_dict().get("history", [])
