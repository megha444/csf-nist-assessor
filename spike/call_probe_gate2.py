"""
Gate 2 call test: run U1 (long-invocation survival) + U2 (egress) against the
deployed probe. See docs/rearchitect_agent_runtime_plan.md.

Usage:
    poetry run python -m spike.call_probe_gate2 [slow_seconds]
"""
from __future__ import annotations

import json
import sys
import time

import vertexai
from vertexai import agent_engines

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"
RESOURCE = "projects/220244569524/locations/us-central1/reasoningEngines/634309907331416064"
USER = "gate2"


def main() -> None:
    slow_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    vertexai.init(project=PROJECT, location=LOCATION)
    app = agent_engines.get(RESOURCE)
    session = app.create_session(user_id=USER)
    session_id = session["id"] if isinstance(session, dict) else getattr(session, "id", session)
    print(f"remote session: {session_id}")

    msg = (
        f"Run all checks with slow_task seconds={slow_seconds}. "
        "Call whoami, then egress_check, then slow_task, and report each tool's "
        "raw returned dict verbatim as JSON."
    )
    print(f"sending: {msg}\n--- streaming (watch wall-clock for U1) ---")
    t0 = time.time()
    tool_results: list = []
    last_text = ""
    try:
        for event in app.stream_query(user_id=USER, session_id=session_id, message=msg):
            parts = (event.get("content") or {}).get("parts") or []
            for p in parts:
                if "function_response" in p:
                    fr = p["function_response"]
                    tool_results.append((fr.get("name"), fr.get("response")))
                    print(f"[{round(time.time()-t0,1)}s] TOOL {fr.get('name')} -> {json.dumps(fr.get('response'))}")
                elif "function_call" in p:
                    print(f"[{round(time.time()-t0,1)}s] call {p['function_call'].get('name')}({json.dumps(p['function_call'].get('args'))})")
                elif p.get("text"):
                    last_text = p["text"]
    except Exception as e:
        print(f"\nSTREAM RAISED after {round(time.time()-t0,1)}s: {type(e).__name__}: {e}")

    elapsed = round(time.time() - t0, 1)
    print(f"\n--- done, total wall-clock {elapsed}s ---")
    if last_text:
        print("final model text:", last_text)

    # Verdicts
    names = {n for n, _ in tool_results}
    slow = next((r for n, r in tool_results if n == "slow_task"), None)
    egr = next((r for n, r in tool_results if n == "egress_check"), None)
    who = next((r for n, r in tool_results if n == "whoami"), None)

    print("\n===== GATE 2 VERDICTS =====")
    if who:
        print("runtime SA:", who.get("runtime_service_account"))
    if slow and slow.get("status") == "COMPLETED_TO_END":
        print(f"U1 (long invocation): PASS — slow_task ran {slow.get('elapsed_seconds')}s to completion, stream held")
    else:
        print(f"U1 (long invocation): INCONCLUSIVE/FAIL — slow_task result: {slow}")
    if egr:
        print(f"U2 (egress): {egr.get('verdict')} — http_status={egr.get('http_status')}")
    else:
        print("U2 (egress): NO RESULT — egress_check did not return")


if __name__ == "__main__":
    main()
