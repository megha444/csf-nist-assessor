"""
Register the CSF fleet in Google's native Agent Registry (GEAP).

    poetry run python infra/register_agent_registry.py           # create/update
    poetry run python infra/register_agent_registry.py --dry-run # print, change nothing
    poetry run python infra/register_agent_registry.py --list    # show what's registered

WHY A SCRIPT AND NOT SELF-REGISTRATION
--------------------------------------
csf_specialists/agent_base.py::_register writes each agent into *Firestore* at
import time, which is fine because it is one cheap local write. Doing the same
against the Agent Registry API would fire 6 HTTPS calls on every container start
in three services (gateway, worker, UI) — slow, rate-limit-prone, and on the
import hot path. Registration is a deploy-time concern, so it lives here.

WHAT GETS REGISTERED (and what deliberately does NOT)
-----------------------------------------------------
The Coordinator is NOT registered here. Agent Runtime **auto-registers** agents
it hosts: `csf-coordinator` has been in the registry since 2026-08-25 with the
native URN

    urn:agent:projects-220244569524:...:aiplatform:reasoningEngines:4356534999353131008

carrying platform-supplied attributes we could never set by hand — RuntimeIdentity
(the Agent-Runtime service agent), Framework=google-adk, and a RuntimeReference to
the live engine. Registering it manually would create a WEAKER duplicate under an
`agentregistry:` URN that does not self-identify as an Agent Runtime agent. So we
leave it alone; `--list` shows it alongside ours.

That leaves 7 manual entries: the 6 specialists, and the gateway.

RESOURCE MODEL (why we POST `services` but read `agents`)
----------------------------------------------------------
You do not create Agents. You create a **Service**, and the registry projects it
into the read-only `agents` / `endpoints` / `mcpServers` catalogues. Hence
services.create/patch/delete vs agents.list/get/search.

  - 6 specialists -> agentSpec   (they are autonomous scoring agents)
  - gateway       -> endpointSpec (it is an API front door, not an agent)

`type: NO_SPEC` is the documented category for "standard REST agents that don't
implement the A2A specification" — literally what we are. We do NOT claim
A2A_AGENT_CARD: that asserts the agent serves an Agent Card over the A2A
protocol, which ours do not, and the registry would index skills we don't expose.

THE INTERFACE URL — read this before describing it to anyone
-------------------------------------------------------------
`Interface.url` is required, but the 6 specialists are Cloud Run *Jobs* consuming
Pub/Sub: no URL, no port, no ingress. Each is therefore registered against
`{gateway}/agents/{function}` — a real, reachable endpoint that returns that
agent's metadata. It is a DESCRIPTOR endpoint, not an invocation endpoint. You
cannot POST to it to run a scoring job. Do not imply otherwise.

Region: us-central1. Manual registration is NOT supported in the `us`/`eu`
multi-regions, so this deliberately does not sit where the Model Armor template
lives (`us`).

EGRESS DESTINATIONS LIVE ELSEWHERE — infra/setup_agent_gateway.py
------------------------------------------------------------------
Agent Gateway turns the registry into a default-deny egress ALLOWLIST: every
hostname the Coordinator dials must be a registered Service or the call is
refused. Those ~28 entries are deliberately NOT here. This file is the fleet
CATALOGUE — 7 entries, each individually argued, meant to be read by a human;
folding an allowlist into it would triple `--list` and blur that. They also fail
differently: a thin description here is cosmetic, a missing hostname there is a
silent egress outage. They are namespaced `egress-*` so the two never collide.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.auth.transport.requests import AuthorizedSession  # noqa: E402
import google.auth  # noqa: E402

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"          # regional: manual registration is barred in `us`/`eu`
BASE = f"https://agentregistry.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}"
GATEWAY_URL = "https://csf-gateway-jdogd2dq2q-uc.a.run.app"

FUNCTION_TITLES = {
    "govern": "Govern", "identify": "Identify", "protect": "Protect",
    "detect": "Detect", "respond": "Respond", "recover": "Recover",
}


# ----------------------------------------------------------------- helpers
def _session() -> AuthorizedSession:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return AuthorizedSession(creds)


def _wait(sess: AuthorizedSession, op: dict, timeout: float = 120.0) -> dict:
    """services.create/patch return a long-running Operation. Poll it, because
    'HTTP 200 with an operation name' is not the same as 'the resource exists' —
    and the very next thing we do is read the catalogue back."""
    name = op.get("name", "")
    if not name.startswith("operations/") and "/operations/" not in name:
        return op  # already a resource, nothing to wait on
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = sess.get(f"https://agentregistry.googleapis.com/v1/{name}", timeout=30)
        d = r.json()
        if d.get("done"):
            if "error" in d:
                raise RuntimeError(f"operation failed: {d['error']}")
            return d.get("response", d)
        time.sleep(2)
    raise TimeoutError(f"operation {name} did not complete in {timeout}s")


def _load_specialist_metadata() -> dict[str, dict]:
    """Reuse what agent_base.py::_register already wrote to Firestore rather than
    re-deriving capabilities here — one source of truth for what each agent covers."""
    from google.cloud.firestore import Client

    db = Client(project=PROJECT)
    return {d.id: (d.to_dict() or {}) for d in db.collection("agents").stream()}


# ----------------------------------------------------------------- payloads
def _build_entries(meta: dict[str, dict]) -> list[tuple[str, dict]]:
    entries: list[tuple[str, dict]] = []

    for fn, title in FUNCTION_TITLES.items():
        m = meta.get(fn) or {}
        caps = m.get("capabilities") or []
        rubric = m.get("rubric_version", "unknown")
        # Capabilities go in the description because NO_SPEC has no structured
        # skills field — this is what makes agents.search able to find them.
        desc = (
            f"NIST CSF 2.0 {title} specialist. Scores the {title} function's "
            f"{len(caps)} categories ({', '.join(caps)}) against a CMMI 1-5 rubric "
            f"using retrieved evidence and interview answers. Rubric version {rubric}. "
            f"Runs as a Cloud Run Job dispatched over Pub/Sub; the registered URL is a "
            f"metadata descriptor endpoint, not an invocation endpoint."
        )
        entries.append((
            f"csf-specialist-{fn}",
            {
                "displayName": f"CSF {title} Specialist",
                "description": desc,
                "agentSpec": {"type": "NO_SPEC"},
                "interfaces": [
                    {"url": f"{GATEWAY_URL}/agents/{fn}", "protocolBinding": "HTTP_JSON"}
                ],
            },
        ))

    entries.append((
        "csf-gateway-api",
        {
            "displayName": "CSF Assessor Gateway API",
            "description": (
                "Front-door REST API for the CSF Assessor fleet: session management, "
                "evidence ingest, interview Q&A, assessment runs, and reports. Enforces "
                "API-key auth and per-caller rate limiting, and screens untrusted input "
                "through Model Armor. Registered as an endpoint, not an agent."
            ),
            "endpointSpec": {"type": "NO_SPEC"},
            "interfaces": [{"url": GATEWAY_URL, "protocolBinding": "HTTP_JSON"}],
        },
    ))
    return entries


# ----------------------------------------------------------------- actions
def register(sess: AuthorizedSession, dry_run: bool) -> int:
    meta = _load_specialist_metadata()
    missing = [f for f in FUNCTION_TITLES if f not in meta]
    if missing:
        print(f"WARNING: no Firestore metadata for {missing} — descriptions will be thin.")

    failures = 0
    for service_id, body in _build_entries(meta):
        url = f"{BASE}/services/{service_id}"
        existing = sess.get(url, timeout=30)

        if dry_run:
            verb = "PATCH" if existing.status_code == 200 else "CREATE"
            print(f"[dry-run] {verb} {service_id}")
            print(json.dumps(body, indent=2))
            continue

        try:
            if existing.status_code == 200:
                mask = ",".join(body.keys())
                r = sess.patch(f"{url}?updateMask={mask}", json=body, timeout=60)
                action = "updated"
            else:
                r = sess.post(f"{BASE}/services?serviceId={service_id}", json=body, timeout=60)
                action = "created"
            if r.status_code >= 400:
                print(f"  FAIL {service_id}: HTTP {r.status_code} {r.text[:300]}")
                failures += 1
                continue
            _wait(sess, r.json())
            print(f"  {action}: {service_id}")
        except Exception as e:  # keep going: one bad entry must not abort the rest
            print(f"  FAIL {service_id}: {type(e).__name__}: {e}")
            failures += 1
    return failures


def list_registry(sess: AuthorizedSession) -> None:
    r = sess.get(f"{BASE}/agents?pageSize=100", timeout=30)
    agents = r.json().get("agents", [])
    print(f"\n=== agents ({len(agents)}) ===")
    for a in agents:
        attrs = a.get("attributes") or {}
        uri = str((attrs.get("agentregistry.googleapis.com/system/RuntimeReference") or {}).get("uri") or "")
        # Every entry has a RuntimeReference — a manual one points back at its own
        # registry Service, a platform-hosted one points at the real runtime. Only
        # the latter is genuinely auto-registered.
        if uri.startswith("//aiplatform.googleapis.com/"):
            tag = " [AUTO-REGISTERED by Agent Runtime]"
        elif str(a.get("agentId", "")).startswith("urn:agent:googleapis.com:"):
            tag = " [Google built-in]"   # not ours; ships with the registry
        else:
            tag = " [manual]"
        print(f"  {a.get('displayName','?'):32s} loc={a.get('location','?')}{tag}")
        print(f"      {a.get('agentId','?')}")

    for kind in ("endpoints", "services"):
        r = sess.get(f"{BASE}/{kind}?pageSize=100", timeout=30)
        items = r.json().get(kind, [])
        print(f"\n=== {kind} ({len(items)}) ===")
        for i in items:
            print(f"  {i.get('displayName', i.get('name','?').split('/')[-1])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print payloads, change nothing")
    ap.add_argument("--list", action="store_true", help="list what is registered and exit")
    args = ap.parse_args()

    sess = _session()
    if args.list:
        list_registry(sess)
        return 0

    print(f"Registering CSF fleet in Agent Registry ({PROJECT}/{LOCATION})")
    print("Coordinator is skipped — Agent Runtime auto-registers it natively.\n")
    failures = register(sess, args.dry_run)
    if not args.dry_run:
        list_registry(sess)
    if failures:
        print(f"\n{failures} entr(ies) failed — the Firestore registry is unaffected.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
