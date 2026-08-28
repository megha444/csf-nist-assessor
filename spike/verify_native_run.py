"""
Verify the Agent Runtime cut-over: does a CALLER-SUPPLIED run_id survive the
round trip to the hosted Coordinator and land on the Firestore doc the UI polls?

This is the one thing that silently breaks the native path. The gateway mints
run_id, returns it to the UI immediately, and the UI polls
sessions/{sid}/runs/{rid}. If the engine mints its own run_id instead of
honouring `run=`, every field still looks healthy server-side while the UI sits
on "pending" forever. spike/call_coordinator.py can't catch that — it reads
whichever run_id the engine reports back, so it passes either way.

Deliberately mirrors csf_gateway/app/runs.py::_run_via_agent_runtime rather than
call_coordinator.py: same async_create_session / async_stream_query surface the
gateway uses, so this exercises the real code path and not a sync lookalike.

Usage:
    poetry run python -m spike.verify_native_run [session_id] [functions]
Defaults: session f56a9039-... (Gate 3's session), functions govern,identify
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid

import vertexai
from vertexai import agent_engines
from google.cloud.firestore import Client

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"
import os
ENGINE = os.environ.get(
    "REASONING_ENGINE_RESOURCE",
    f"projects/220244569524/locations/{LOCATION}/reasoningEngines/4356534999353131008",
)
DEFAULT_SESSION = "f56a9039-877e-4a24-adc6-efafa22d104b"
DEFAULT_FUNCTIONS = "govern,identify"
USER = "csf-gateway"  # same engine user_id the gateway uses


async def main() -> int:
    session_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION
    functions = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_FUNCTIONS

    # The gateway generates this BEFORE invoking and hands it straight to the UI.
    run_id = str(uuid.uuid4())
    print(f"caller-generated run_id : {run_id}")
    print(f"session                 : {session_id}")
    print(f"functions               : {functions}\n")

    vertexai.init(project=PROJECT, location=LOCATION)
    app = agent_engines.get(ENGINE)

    remote = await app.async_create_session(user_id=USER)
    remote_id = remote["id"] if isinstance(remote, dict) else getattr(remote, "id", remote)

    message = f"session={session_id} functions={functions} run={run_id}"
    print(f"invoking: {message}\n--- streaming ---")

    t0 = time.time()
    try:
        async for event in app.async_stream_query(
            user_id=USER, session_id=remote_id, message=message
        ):
            for part in (event.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    print(f"[{round(time.time() - t0, 1)}s] {part['text']}")
    except Exception as e:
        print(f"\nSTREAM RAISED after {round(time.time() - t0, 1)}s: {type(e).__name__}: {e}")
        print("(the engine may still be running server-side — checking Firestore anyway)")

    elapsed = round(time.time() - t0, 1)
    print(f"\n--- invocation returned after {elapsed}s ---\n")

    # ---- The actual assertion: OUR run_id, not whatever the engine chose ----
    db = Client(project=PROJECT)
    run_ref = (
        db.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
    )
    snap = run_ref.get()

    print("===== VERIFICATION =====")
    if not snap.exists:
        print(f"FAIL — sessions/{session_id}/runs/{run_id} does not exist.")
        # Two very different causes produce this, so don't guess. A real run
        # takes minutes; a crash returns in seconds. Distinguishing them saved
        # a wrong diagnosis on 2026-08-27, when an AGENT_IDENTITY engine died in
        # 1.3s on a 401 and this message wrongly blamed run_id parsing.
        if elapsed < 30:
            print(f"       Returned in {elapsed}s — far too fast for a real run, so the")
            print("       agent almost certainly CRASHED rather than ignoring `run=`.")
            print("       Check the engine's own logs for the real error:")
            print("         gcloud logging read 'resource.type=\"aiplatform.googleapis.com/ReasoningEngine\"")
            print(f"           AND resource.labels.reasoning_engine_id=\"{ENGINE.split('/')[-1]}\"")
            print("           AND severity>=ERROR' --limit 20 --freshness=15m")
        else:
            print("       The engine ran but did not honour `run=` — it minted its own")
            print("       run_id, so the UI would poll this id forever and see nothing.")
        return 1

    doc = snap.to_dict() or {}
    scores = len(list(run_ref.collection("scores").stream()))
    tiers = list(run_ref.collection("tiers").stream())
    judges = len(list(run_ref.collection("judge").stream()))

    print(f"run doc exists  : YES  <- caller's run_id was honoured")
    print(f"status          : {doc.get('status')}")
    print(f"agents          : {doc.get('completed_agents')}/{doc.get('expected_agents')}")
    print(f"Category scores : {scores}")
    print(f"Tiers           : {len(tiers)} -> {[t.id + '=' + str((t.to_dict() or {}).get('tier')) for t in tiers]}")
    print(f"Judge verdicts  : {judges}")

    n_fn = len([f for f in functions.split(",") if f.strip()])
    ok = doc.get("status") == "ready_for_report" and len(tiers) == n_fn and scores > 0
    print(f"\nRESULT: {'PASS — native Agent Runtime wrote the run the UI polls' if ok else 'INCOMPLETE — see counts above'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
