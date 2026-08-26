"""
THROWAWAY probe agent for the Agent Runtime / Agent Engine re-architecture spike.
See docs/rearchitect_agent_runtime_plan.md (Steps 0-2 / Gates 1-2).

Gate 1 (PASSED): bare deploy + Gemini 3.x reachability.
Gate 2 (this version): the two architecture-deciding unknowns —
  U1  slow_task()    — does a long-running invocation survive to completion, or
                       does the runtime kill it at some request timeout? Our real
                       Coordinator runs for minutes; this is a proxy for that.
  U2  egress_check() — can the hosted agent make an authenticated outbound call
                       to the Cloud Run Admin API (exactly what DispatchStep does
                       via run_v2.JobsClient to trigger csf-worker), or is egress
                       blocked? Uses a raw authed REST call so the container needs
                       NO deps beyond google-adk + google-auth (both already
                       present) — avoids the "can I add deps" question entirely.
  whoami()           — reports the runtime's own service-account identity, so we
                       know exactly which SA to grant egress roles to if U2 hits
                       a 403 (IAM gap) rather than a hard block.

Deliberately STANDALONE — imports nothing from csf_*. Safe to delete post-spike.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from google.adk.agents import Agent

PROJECT = "csf-assessor-hackathon"
LOCATION = "us-central1"


def _runtime_sa() -> str:
    """The service-account email this container actually runs as, via the GCE
    metadata server (authoritative inside any GCP runtime)."""
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode().strip()
    except Exception as e:  # noqa: BLE001
        return f"<metadata lookup failed: {type(e).__name__}: {e}>"


def whoami() -> dict:
    """Report the runtime identity of this deployed agent. No args."""
    sa = _runtime_sa()
    out = {"runtime_service_account": sa}
    try:
        import google.auth

        creds, proj = google.auth.default()
        out["adc_project"] = proj
        out["adc_sa_email"] = getattr(creds, "service_account_email", "<n/a>")
    except Exception as e:  # noqa: BLE001
        out["adc_error"] = f"{type(e).__name__}: {e}"
    return out


def slow_task(seconds: int) -> dict:
    """Run a deliberately slow task to test whether a long-running invocation
    survives to completion inside Agent Runtime.

    Args:
        seconds: how long to run (capped at 180s for safety).
    """
    seconds = max(1, min(int(seconds), 180))
    start = time.time()
    # Busy-free wait in small increments so the runtime sees a genuinely
    # long-lived call, mirroring our Coordinator's minutes-long poll loop.
    remaining = seconds
    while remaining > 0:
        step = min(10, remaining)
        time.sleep(step)
        remaining -= step
    elapsed = round(time.time() - start, 1)
    return {"requested_seconds": seconds, "elapsed_seconds": elapsed, "status": "COMPLETED_TO_END"}


def egress_check() -> dict:
    """Attempt the same outbound call DispatchStep makes — reach the Cloud Run
    Admin API — using the runtime's own credentials via a raw authed REST GET.
    No args. Distinguishes: reachable+authorized (200), egress-ok-but-IAM-gap
    (403), or egress-blocked (connection error/timeout)."""
    result: dict = {"target": "run.googleapis.com jobs.list", "runtime_sa": _runtime_sa()}
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{LOCATION}/jobs"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = json.loads(r.read().decode() or "{}")
                jobs = [j.get("name", "?").split("/")[-1] for j in body.get("jobs", [])]
                result.update(http_status=r.status, verdict="EGRESS_OK_AUTHORIZED", jobs_seen=jobs)
        except urllib.error.HTTPError as he:
            # Got an HTTP response → egress works; status tells us the IAM story.
            verdict = "EGRESS_OK_IAM_GAP" if he.code in (401, 403) else f"EGRESS_OK_HTTP_{he.code}"
            result.update(http_status=he.code, verdict=verdict, detail=he.read().decode()[:300])
        except urllib.error.URLError as ue:
            result.update(http_status=None, verdict="EGRESS_BLOCKED", detail=f"{type(ue).__name__}: {ue.reason}")
    except Exception as e:  # noqa: BLE001
        result.update(verdict="PROBE_ERROR", detail=f"{type(e).__name__}: {e}")
    return result


root_agent = Agent(
    name="probe_agent",
    model="gemini-3.5-flash",
    description="Throwaway probe for the Agent Engine spike (Gates 1-2).",
    instruction=(
        "You are a deployment probe with three tools: whoami, slow_task, and "
        "egress_check. When the user asks you to run a specific check, call that "
        "tool with any arguments they give, then report the tool's raw returned "
        "dict back to the user verbatim as JSON. Do not summarize or omit fields. "
        "If asked to 'run all checks', call whoami, then egress_check, then "
        "slow_task with the given seconds, and report all three results."
    ),
    tools=[whoami, slow_task, egress_check],
)
