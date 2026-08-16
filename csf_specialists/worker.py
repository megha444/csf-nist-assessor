"""
One-shot Govern specialist worker — pulls a single dispatch message from
csf-dispatch-govern, scores every Category in it, publishes one completion
message to csf-results.

NOT a deployed/push-triggered service — that's explicitly Phase 3 (Aug 22)
per govern_build_tasks.md ("Deploy csf_specialists as its own Cloud Run
service", "Per-agent SA impersonation"). This is a locally-runnable stub
consumer, matching the coordinator's own "stub" scope for Sun Aug 16.

Usage:
  poetry run python csf_specialists/worker.py
  poetry run python csf_specialists/worker.py --timeout 60
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from csf_coordinator import pubsub_client  # noqa: E402
from csf_specialists.agents.govern import govern_agent  # noqa: E402


async def process_one_dispatch(timeout: float) -> bool:
    """Pull one dispatch message; return False if none arrived within timeout."""
    messages = await pubsub_client.pull_dispatch("govern", max_messages=1, timeout=timeout)
    if not messages:
        return False

    msg = messages[0]
    run_id = msg["run_id"]
    session_id = msg["session_id"]
    category_ids = msg["category_ids"]
    print(f"[worker] dispatch received: run_id={run_id} session={session_id} categories={category_ids}")

    start = time.monotonic()
    failed_ids: list[str] = []
    for cat in category_ids:
        try:
            r = await govern_agent.score_category(cat, session_id, run_id=run_id)
            print(f"[worker]   {cat}: CMMI={r.cmmi_level} conf={r.confidence:.2f}")
        except Exception as e:
            print(f"[worker]   {cat}: FAILED — {type(e).__name__}: {e}", file=sys.stderr)
            failed_ids.append(cat)

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "complete" if not failed_ids else "partial"

    await pubsub_client.publish_result({
        "run_id": run_id,
        "function": "govern",
        "status": status,
        "category_count": len(category_ids),
        "failed_ids": failed_ids,
        "duration_ms": duration_ms,
    })
    print(f"[worker] published result: status={status} duration_ms={duration_ms} failed={failed_ids}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for a dispatch message")
    args = parser.parse_args()

    got_one = asyncio.run(process_one_dispatch(args.timeout))
    if not got_one:
        print(f"[worker] no dispatch message on csf-dispatch-govern within {args.timeout}s", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
