"""
Gate 1 remote-call test: invoke the DEPLOYED probe on Agent Engine and see if it
(a) responds at all and (b) can actually reach Gemini 3.x from us-central1 —
the empirical answer to open question G1 (region/model reachability).

Usage:
    poetry run python -m spike.call_probe_remote <reasoningEngine_resource_name>

If no arg is given, uses the RESOURCE constant below (update after deploy).
"""
from __future__ import annotations

import sys

import vertexai
from vertexai import agent_engines

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"
# Filled in from the Gate 1 deploy log:
RESOURCE = "projects/220244569524/locations/us-central1/reasoningEngines/634309907331416064"

USER = "gate1"
MESSAGE = "Run a check with marker 'gate1-deployed'."


def main() -> None:
    resource = sys.argv[1] if len(sys.argv) > 1 else RESOURCE
    vertexai.init(project=PROJECT, location=LOCATION)

    print(f"Fetching deployed agent: {resource}")
    app = agent_engines.get(resource)

    # Surface what query API this deployment actually exposes (ADK apps vary by
    # SDK version) rather than assuming.
    ops = [m for m in dir(app) if not m.startswith("_") and callable(getattr(app, m, None))]
    print("Available operations:", [o for o in ops if any(k in o for k in ("query", "session", "stream"))])

    # ADK-on-Agent-Engine pattern: create a session, then stream_query.
    session = app.create_session(user_id=USER)
    session_id = session["id"] if isinstance(session, dict) else getattr(session, "id", session)
    print(f"Created remote session: {session_id}")

    print("\n--- streaming response ---")
    got_output = False
    try:
        for event in app.stream_query(user_id=USER, session_id=session_id, message=MESSAGE):
            got_output = True
            print(event)
    except Exception as e:
        print(f"\nstream_query RAISED: {type(e).__name__}: {e}")
        print("\nGATE 1 REMOTE RESULT: FAIL — deployed agent errored (likely the G1 model-region issue)")
        return

    verdict = "PASS — deployed agent responded" if got_output else "FAIL — no output from deployed agent"
    print(f"\nGATE 1 REMOTE RESULT: {verdict}")


if __name__ == "__main__":
    main()
