"""
Report generator v1 — JSON output for one run: every scored Category (CMMI level,
evidence citations, reasoning, per-Subcategory findings) plus the aggregated Tier,
grouped per Function — a run can now cover more than one Function
(csf_coordinator.coordinator.run_assessment), so the top level is keyed by
Function, not a single flat function/tier pair. Foundation for v2 (HTML+Plotly)
and v3 (exec summary+roadmap) — those consume this same structure rather than
re-querying Firestore from scratch.

Usage:
  poetry run python csf_specialists/scripts/export_json.py --session <sid> --run <rid>
  poetry run python csf_specialists/scripts/export_json.py --session <sid> --run <rid> --out report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.cloud.firestore import AsyncClient

from csf_gateway.app.config import get_settings
from csf_specialists.firestore_util import aclose_firestore
from csf_specialists.memory_bank import get_prior_assessment


async def build_report(session_id: str, run_id: str) -> dict:
    s = get_settings()
    client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    try:
        session_snap = await client.collection("sessions").document(session_id).get()
        org_id = (session_snap.to_dict() or {}).get("org_id", "") if session_snap.exists else ""

        run_ref = (
            client.collection("sessions").document(session_id)
            .collection("runs").document(run_id)
        )

        scores = [snap.to_dict() async for snap in run_ref.collection("scores").stream()]
        if not scores:
            raise ValueError(f"no scores at sessions/{session_id}/runs/{run_id}/scores")

        scores.sort(key=lambda s: s["category_id"])
        functions = sorted({s["function"] for s in scores})

        # LLM-as-Judge defensibility verdicts, one doc per Category (may be absent
        # for a Category whose judge hasn't run/failed — surfaced as-available).
        # Doc id == category_id; shape {defensibility: high|medium|low, judge_notes}.
        judge_docs = {snap.id: (snap.to_dict() or {}) async for snap in run_ref.collection("judge").stream()}

        result: dict = {"session_id": session_id, "run_id": run_id, "functions": {}}
        for function in functions:
            function_scores = [s for s in scores if s["function"] == function]
            tier_snap = await run_ref.collection("tiers").document(function).get()
            # Memory Bank: the most recent PRIOR assessment of this same org for
            # this Function (excluding this run, which may already be recorded
            # by the time a report reads it back) — None if this is the first
            # assessment of this org, or Memory Bank predates it. Pass our own
            # client so no separate (unclosed) Memory Bank client is opened.
            prior = await get_prior_assessment(org_id, function, exclude_run_id=run_id, client=client)

            categories = [
                {
                    "category_id": s["category_id"],
                    "cmmi_level": s["cmmi_level"],
                    "confidence": s["confidence"],
                    "reasoning": s["reasoning"],
                    "no_doc_evidence": s["no_doc_evidence"],
                    "evidence_citations": s.get("evidence_citations", []),
                    "interview_evidence": s.get("interview_evidence", []),
                    "subcategory_scores": s.get("subcategory_scores", []),
                    # Judge's independent defensibility verdict (None if not yet judged).
                    "defensibility": judge_docs.get(s["category_id"], {}).get("defensibility"),
                    "judge_notes": judge_docs.get(s["category_id"], {}).get("judge_notes"),
                }
                for s in function_scores
            ]

            result["functions"][function] = {
                "tier": tier_snap.to_dict() if tier_snap.exists else None,
                "category_count": len(categories),
                "categories": categories,
                "prior_assessment": prior,
            }

        return result
    finally:
        # Close the grpc.aio channel so a Streamlit rerun / CLI script loop
        # teardown doesn't leave a poller raising "Event loop is closed".
        await aclose_firestore(client)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="session_id")
    parser.add_argument("--run", required=True, dest="run_id", help="run_id (must have persisted scores)")
    parser.add_argument("--out", type=Path, default=None, help="write to file instead of stdout")
    args = parser.parse_args()

    try:
        report = asyncio.run(build_report(args.session, args.run_id))
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    text = json.dumps(report, indent=2, default=str)
    total_categories = sum(f["category_count"] for f in report["functions"].values())
    summary = ", ".join(f"{fn}={f['category_count']}" for fn, f in report["functions"].items())
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {total_categories} Categories across {len(report['functions'])} Function(s) ({summary}) -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
