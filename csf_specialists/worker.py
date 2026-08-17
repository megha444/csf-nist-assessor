"""
One-shot specialist worker — pulls a single dispatch message from
csf-dispatch-{function}, scores every Category in it via that Function's
registered agent (csf_specialists.agents.AGENTS), publishes one completion
message to csf-results.

NOT a deployed/push-triggered service — that's explicitly Phase 3 (Aug 22)
per govern_build_tasks.md ("Deploy csf_specialists as its own Cloud Run
service", "Per-agent SA impersonation"). This is a locally-runnable stub
consumer — one process per Function you want to actually service; a real
multi-Function csf_coordinator.run_assessment() call needs one of these
running per Function passed to it.

Usage:
  poetry run python csf_specialists/worker.py --function govern
  poetry run python csf_specialists/worker.py --function identify --timeout 60
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
from csf_specialists.agents import AGENTS  # noqa: E402

# Firing every Category at once (e.g. 6 for Govern) hit Vertex AI's rate limit
# for this project/model — observed live (Aug 17): 2 of 6 concurrent calls
# failed with 429 RESOURCE_EXHAUSTED. This caps how many Categories are
# in flight at once; tune down if 429s still appear, up if quota allows more.
MAX_CONCURRENT_CATEGORIES = 3


async def _score_one(
    agent, function: str, cat: str, session_id: str, run_id: str, semaphore: asyncio.Semaphore,
) -> str | None:
    """Score one Category; print the result; return `cat` on failure, None on success.

    Returns a sentinel instead of raising so asyncio.gather over all Categories
    doesn't need return_exceptions=True — one Category failing doesn't cancel
    the others, matching the original sequential loop's error-isolation.
    """
    async with semaphore:
        try:
            r = await agent.score_category(cat, session_id, run_id=run_id)
            print(f"[worker/{function}]   {cat}: CMMI={r.cmmi_level} conf={r.confidence:.2f}")
            return None
        except Exception as e:
            print(f"[worker/{function}]   {cat}: FAILED — {type(e).__name__}: {e}", file=sys.stderr)
            return cat


async def process_one_dispatch(function: str, timeout: float) -> bool:
    """Pull one dispatch message for `function`; return False if none arrived within timeout."""
    if function not in AGENTS:
        raise ValueError(f"no registered agent for function={function!r} — see csf_specialists.agents.AGENTS")
    agent = AGENTS[function]

    messages = await pubsub_client.pull_dispatch(function, max_messages=1, timeout=timeout)
    if not messages:
        return False

    msg = messages[0]
    run_id = msg["run_id"]
    session_id = msg["session_id"]
    category_ids = msg["category_ids"]
    print(f"[worker/{function}] dispatch received: run_id={run_id} session={session_id} categories={category_ids}")

    start = time.monotonic()
    # Categories are independent Gemini calls (different retrieval, different
    # prompt) — score them concurrently instead of one at a time, bounded by
    # MAX_CONCURRENT_CATEGORIES so we don't exceed Vertex AI's rate limit.
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CATEGORIES)
    outcomes = await asyncio.gather(
        *(_score_one(agent, function, cat, session_id, run_id, semaphore) for cat in category_ids)
    )
    failed_ids = [cat for cat in outcomes if cat is not None]

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "complete" if not failed_ids else "partial"

    await pubsub_client.publish_result({
        "run_id": run_id,
        "function": function,
        "status": status,
        "category_count": len(category_ids),
        "failed_ids": failed_ids,
        "duration_ms": duration_ms,
    })
    print(f"[worker/{function}] published result: status={status} duration_ms={duration_ms} failed={failed_ids}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--function", required=True, choices=list(AGENTS.keys()), help="which Function to service")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for a dispatch message")
    args = parser.parse_args()

    got_one = asyncio.run(process_one_dispatch(args.function, args.timeout))
    if not got_one:
        print(f"[worker/{args.function}] no dispatch message within {args.timeout}s", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
