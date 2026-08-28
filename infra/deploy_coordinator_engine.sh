#!/usr/bin/env bash
# =============================================================================
# Deploy the Coordinator to Vertex AI Agent Engine — GEAP "Agent Runtime".
#
#   bash infra/deploy_coordinator_engine.sh
#
# Updates the EXISTING engine in place (--agent_engine_id) rather than creating
# a new resource, so REASONING_ENGINE_RESOURCE in deploy_gateway.sh keeps
# pointing at a valid engine and the gateway needs no redeploy to follow it.
# Pass AGENT_ENGINE_ID="" to create a brand-new engine instead (then update
# DEFAULT_ENGINE in infra/deploy_gateway.sh with the resource it prints).
#
# Until Aug 27 this command lived only in docs/rearchitect_agent_runtime_plan.md
# §9 as prose. It is a script now because two of its flags are load-bearing and
# silently degrade the system if dropped on a later redeploy:
#
#   --otel_to_cloud    IS the Agent Observability component. Without it the
#                      native ADK spans stop reaching Cloud Trace and a claimed
#                      Fortified component quietly stops being true.
#   --extra_packages   stages csf_coordinator/csf_specialists/csf_gateway into
#                      the container. Without them the container fails at import.
#
# Deliberately NOT passed:
#   --trigger_sources pubsub   Gate 3 held a synchronous invocation for 321s, so
#                              the fire-and-forget trigger path is unnecessary.
#   --memory_service_uri       native Memory Bank is ADK session/conversational
#                              memory — a different data model than our cross-run
#                              Tier tracking (G3, resolved & declined).
#
# HARD-WON: every runtime dependency must be listed in
# coordinator_engine/requirements.txt. A local import test CANNOT catch a
# missing container dep — that is exactly how Gate 3 first failed (qdrant-client
# was installed on the laptop, absent in the container, container died at
# import). If this deploy succeeds but the first invocation 500s, check Cloud
# Logging for importlib errors before assuming a code bug.
# =============================================================================
set -euo pipefail

PROJECT_ID="csf-assessor-hackathon"
REGION="us-central1"          # engine resource region; Gemini still resolves via 'global'
DISPLAY_NAME="csf-coordinator"
AGENT_DIR="coordinator_engine"
AGENT_ENGINE_ID="${AGENT_ENGINE_ID-4356534999353131008}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ARGS=(
    --project="$PROJECT_ID"
    --region="$REGION"
    --display_name="$DISPLAY_NAME"
    --extra_packages csf_coordinator
    --extra_packages csf_specialists
    --extra_packages csf_gateway
    --otel_to_cloud
)

if [[ -n "$AGENT_ENGINE_ID" ]]; then
    echo "==> Updating existing Agent Engine $AGENT_ENGINE_ID in place"
    ARGS+=(--agent_engine_id "$AGENT_ENGINE_ID")
else
    echo "==> Creating a NEW Agent Engine resource"
fi

echo "    project=$PROJECT_ID region=$REGION agent_dir=$AGENT_DIR"
echo "    (Cloud Build; expect ~5-15 min)"

poetry run adk deploy agent_engine "${ARGS[@]}" "$AGENT_DIR"

echo ""
echo "======================================================================"
echo "  Deployed. Verify before trusting it:"
echo "    poetry run python -m spike.call_coordinator \\"
echo "        projects/220244569524/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID:-<new-id>}"
echo ""
echo "  A clean exit here does NOT mean the container imports — Gate 3's"
echo "  failure exited 0 and died on first invocation. Always invoke once."
echo "======================================================================"
