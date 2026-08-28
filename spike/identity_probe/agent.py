"""
Agent Identity transport probe — which client transports can actually use a
certificate-bound token?

THE QUESTION
------------
With Agent Identity's default Context-Aware Access policy ON, tokens are bound to
the agent's X.509 certificate (mTLS + DPoP). Our real Coordinator gets
401 UNAUTHENTICATED on every call and dies in ~1.3s. We SUSPECT the cause is that
our Firestore clients are async gRPC (`firestore.AsyncClient`) and that transport
cannot perform the bound-token handshake — but we have never proven it, because
the run dies on the very first Firestore call and never reaches anything else.

This probe deliberately runs each transport INDEPENDENTLY and catches every
failure, so one invocation reports all four results instead of stopping at the
first one.

  1. Firestore SYNC  gRPC   -- if this works, the fix is a targeted transport
                               change in 5 engine-side modules, no opt-out needed
  2. Firestore ASYNC gRPC   -- what our real code uses today
  3. Pub/Sub  SYNC   gRPC   -- a different service, same transport family
  4. Firestore REST (raw)   -- plain HTTPS + bearer token, no gRPC at all

INTERPRETING THE RESULT
-----------------------
  * sync OK + async FAIL  -> transport-specific. Convert engine-side Firestore to
                             sync (wrapped in asyncio.to_thread) and we can turn
                             token binding back ON. Best outcome.
  * REST OK + all gRPC FAIL -> the token itself is fine; gRPC is the problem.
  * everything FAILS      -> the bound-token flow does not work from this runtime
                             with these libraries at all, and the documented
                             opt-out is the only path. Also a real answer.

IMPORTANT: this agent's .env deliberately does NOT set
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES, so token binding stays
ON. That is the entire point -- do not "fix" it by adding the opt-out here.

Throwaway. Delete the engine after reading the result.
"""
from __future__ import annotations

import os
import traceback

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "csf-assessor-hackathon")

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

PROJECT = "csf-assessor-hackathon"
COLLECTION = "identity_probe"


def _event(author: str, invocation_id: str, text: str) -> Event:
    return Event(
        author=author,
        invocation_id=invocation_id,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


def _short(e: BaseException) -> str:
    """One-line error summary. The status code is the whole story here:
    401 = credential not accepted, 403 = accepted but not authorized."""
    name = type(e).__name__
    msg = str(e).replace("\n", " ")[:180]
    return f"{name}: {msg}"


def _probe_firestore_sync() -> str:
    from google.cloud import firestore

    client = firestore.Client(project=PROJECT)
    client.collection(COLLECTION).document("sync").set({"ok": True})
    snap = client.collection(COLLECTION).document("sync").get()
    return f"wrote+read, exists={snap.exists}"


async def _probe_firestore_async() -> str:
    from google.cloud.firestore import AsyncClient

    client = AsyncClient(project=PROJECT)
    await client.collection(COLLECTION).document("async").set({"ok": True})
    snap = await client.collection(COLLECTION).document("async").get()
    return f"wrote+read, exists={snap.exists}"


def _probe_pubsub_sync() -> str:
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(PROJECT, "csf-results")
    future = publisher.publish(topic, b"identity-probe")
    return f"published msg_id={future.result(timeout=30)}"


def _probe_firestore_rest() -> str:
    """No gRPC at all: plain HTTPS with the ADC bearer token. Isolates whether the
    TOKEN is usable from whether the gRPC TRANSPORT can present it."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sess = AuthorizedSession(creds)
    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT}"
        f"/databases/(default)/documents/{COLLECTION}/rest"
    )
    r = sess.patch(url, json={"fields": {"ok": {"booleanValue": True}}}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    return f"HTTP {r.status_code}"


class IdentityProbeAgent(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext):
        yield _event(self.name, ctx.invocation_id, "identity probe starting (token binding ON)")

        results: list[str] = []

        # Report the identity this container is actually running as, so the result
        # can't be misread as having tested the wrong thing.
        try:
            import google.auth

            creds, proj = google.auth.default()
            ident = getattr(creds, "service_account_email", None) or type(creds).__name__
            results.append(f"[identity] adc={ident} project={proj}")
        except Exception as e:
            results.append(f"[identity] FAILED {_short(e)}")

        for label, fn, is_async in (
            ("firestore-sync-grpc", _probe_firestore_sync, False),
            ("firestore-async-grpc", _probe_firestore_async, True),
            ("pubsub-sync-grpc", _probe_pubsub_sync, False),
            ("firestore-rest-https", _probe_firestore_rest, False),
        ):
            try:
                out = await fn() if is_async else fn()
                results.append(f"[PASS] {label}: {out}")
            except Exception as e:  # noqa: BLE001 — every failure must be reported, not raised
                results.append(f"[FAIL] {label}: {_short(e)}")
                print(f"--- {label} traceback ---")
                traceback.print_exc()

        yield _event(self.name, ctx.invocation_id, "PROBE RESULTS\n" + "\n".join(results))


root_agent = IdentityProbeAgent(name="identity_probe")
