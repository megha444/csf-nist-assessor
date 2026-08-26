"""
Gate 3 test: invoke the DEPLOYED Coordinator on Agent Runtime against a real
session, then verify real persisted Firestore output (scores + tiers + judge).
Specialists still run as csf-worker Cloud Run Jobs, dispatched via Pub/Sub —
this only moves the orchestrator's hosting.

Usage:
    poetry run python -m spike.call_coordinator <reasoningEngine_resource> [session_id] [functions]
Defaults: session f56a9039-... , functions govern,identify
"""
from __future__ import annotations

import re
import sys
import time

import vertexai
from vertexai import agent_engines
from google.cloud.firestore import Client

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"
DEFAULT_SESSION = "f56a9039-877e-4a24-adc6-efafa22d104b"
DEFAULT_FUNCTIONS = "govern,identify"
USER = "gate3"


def main() -> None:
    if len(sys.argv) < 2:
        print("need the reasoningEngine resource name as arg 1")
        sys.exit(1)
    resource = sys.argv[1]
    session_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SESSION
    functions = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_FUNCTIONS

    vertexai.init(project=PROJECT, location=LOCATION)
    app = agent_engines.get(resource)
    remote = app.create_session(user_id=USER)
    remote_id = remote["id"] if isinstance(remote, dict) else getattr(remote, "id", remote)

    msg = f"session={session_id} functions={functions}"
    print(f"invoking coordinator: {msg}\n--- streaming (a real run takes ~2 min) ---")
    t0 = time.time()
    run_id = None
    try:
        for event in app.stream_query(user_id=USER, session_id=remote_id, message=msg):
            parts = (event.get("content") or {}).get("parts") or []
            for p in parts:
                if p.get("text"):
                    txt = p["text"]
                    print(f"[{round(time.time()-t0,1)}s] {txt}")
                    if (m := re.search(r"run_id=([A-Za-z0-9\-]+)", txt)):
                        run_id = m.group(1)
    except Exception as e:
        print(f"\nSTREAM RAISED after {round(time.time()-t0,1)}s: {type(e).__name__}: {e}")

    print(f"\n--- invocation returned after {round(time.time()-t0,1)}s · run_id={run_id} ---")
    if not run_id:
        print("GATE 3: FAIL — no run_id returned from the hosted coordinator")
        return

    # ---- Verify real persisted Firestore output (the actual exit criterion) ----
    db = Client(project=PROJECT)
    run_ref = db.collection("sessions").document(session_id).collection("runs").document(run_id)
    snap = run_ref.get()
    if not snap.exists:
        print(f"GATE 3: FAIL — runs/{run_id} not found in Firestore")
        return
    run_doc = snap.to_dict()
    scores = list(run_ref.collection("scores").stream())
    tiers = list(run_ref.collection("tiers").stream())
    judges = list(run_ref.collection("judge").stream())

    print("\n===== GATE 3 VERIFICATION (Firestore) =====")
    print(f"run status      : {run_doc.get('status')}")
    print(f"expected agents : {run_doc.get('expected_agents')}   completed: {run_doc.get('completed_agents')}")
    print(f"Category scores : {len(scores)}")
    print(f"Tiers persisted : {len(tiers)}  -> {[t.id + '=' + str((t.to_dict() or {}).get('tier')) for t in tiers]}")
    print(f"Judge verdicts  : {len(judges)}")
    ok = len(scores) >= 9 and len(tiers) >= 2 and len(judges) >= 9
    print(f"\nGATE 3 RESULT: {'PASS — real persisted output from hosted coordinator' if ok else 'INCOMPLETE — see counts above'}")


if __name__ == "__main__":
    main()
