"""
Shared OpenTelemetry tracer setup — Cloud Trace export for agent calls.

Agent Observability v1 (Fortified track component): wraps the ADK-backed
calls in agent_base.py (specialist scoring) and interview.py (question
selection) in spans, exported to Cloud Trace. Purely additive — no new
IAM/security model needed; `cloudtrace.googleapis.com` is already enabled
(infra/setup.sh) and reuses whatever credentials already authenticate
Firestore/Vertex calls locally.

Tracing must never break the pipeline it's observing: exporter setup and span
creation are wrapped so a Cloud Trace failure (auth, quota, network) logs a
warning and no-ops instead of raising into the caller. Doesn't yet tag spans
with per-agent IAM identity — that's tied to Agent Identity (per-agent SA
impersonation), a separate not-yet-built Fortified item (`docs/decisions.md`
describes the intended combined end state); this just gets spans flowing.
"""
from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from csf_gateway.app.config import get_settings

log = logging.getLogger("csf-gateway.tracing")

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    try:
        # CloudTraceSpanExporter is flagged deprecated by opentelemetry-exporter-gcp-trace
        # (points at a migration guide toward OTLP-based export) but is still fully
        # functional today — verified live Aug 20, spans land in Cloud Trace correctly,
        # including nested under ADK's own auto-instrumented spans (invocation/
        # invoke_agent/call_llm/generate_content). Same "deprecated but proportionate"
        # call already made for SequentialAgent in csf_coordinator/coordinator.py.
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        s = get_settings()
        provider = TracerProvider(
            resource=Resource.create({"service.name": "csf-assessor-fleet"})
        )
        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=s.google_cloud_project))
        )
        trace.set_tracer_provider(provider)
        log.info("Cloud Trace exporter configured for project %s", s.google_cloud_project)
    except Exception as e:
        log.warning(
            "Cloud Trace exporter setup failed (%s: %s) — spans will still be created "
            "locally but not exported. Check the Cloud Trace API is enabled and the "
            "active credentials have roles/cloudtrace.agent.",
            type(e).__name__, e,
        )


def get_tracer(name: str) -> Tracer:
    """Call at module import time or lazily — safe either way, _configure()
    only runs its setup once regardless of how many tracers are requested."""
    _configure()
    return trace.get_tracer(name)
