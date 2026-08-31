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
# WHICH ENGINE IS PRODUCTION (this default is load-bearing — check it before
# you trust a deploy): 403007845219434496. It runs under native Agent Identity
# (SPIFFE), and `csf-gateway` points REASONING_ENGINE_RESOURCE at it, so it is
# the live judge-facing path. 4356534999353131008 is the SUPERSEDED pre-Agent-
# Identity engine, kept only as an emergency fallback; deploying to it is almost
# always a mistake, so the guard below refuses unless you say so explicitly.
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
PROD_ENGINE_ID="403007845219434496"          # native Agent Identity; the live path
SUPERSEDED_ENGINE_ID="4356534999353131008"   # pre-Agent-Identity; fallback only
AGENT_ENGINE_ID="${AGENT_ENGINE_ID-$PROD_ENGINE_ID}"

# Deploying to the superseded engine is a silent no-op on production: the fix
# lands somewhere nothing invokes.
#
# CORRECTION 2026-08-31: an earlier version of this comment claimed
# identity_type was "immutable after creation, so the update is rejected or
# ignored". That is FALSE and it cost an afternoon. .agent_engine_config.json
# carries identity_type=AGENT_IDENTITY, ADK puts it in the update mask, and the
# platform APPLIES it — converting an existing managed-SA engine to a brand-new
# SPIFFE identity. Engine 4356534999353131008 was converted this way at
# 11:36 UTC and every Firestore call then failed PERMISSION_DENIED, because
# `principal://` bindings do not follow an identity change: the roles stayed on
# service-220244569524@gcp-sa-aiplatform-re, which the engine no longer runs as.
# The conversion itself is CORRECT (Agent Identity is the native posture) — the
# defect was that it happened silently. Hence the pre-flight below.
if [[ "$AGENT_ENGINE_ID" == "$SUPERSEDED_ENGINE_ID" && "${ALLOW_SUPERSEDED_ENGINE:-0}" != "1" ]]; then
    echo "!! Refusing to deploy to $SUPERSEDED_ENGINE_ID — that is the superseded"
    echo "   pre-Agent-Identity engine, not production ($PROD_ENGINE_ID)."
    echo "   If you really mean it: ALLOW_SUPERSEDED_ENGINE=1 $0"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Pre-flight: will this deploy orphan the target engine's IAM? --------------
# A deploy that silently strips an engine's permissions is indistinguishable, at
# the call site, from a code bug: the container starts fine and then every
# outbound call returns PERMISSION_DENIED. Catch it here instead.
#
# Two checks against the engine as it exists RIGHT NOW:
#   1. identityType != AGENT_IDENTITY  -> this deploy will convert it, and the
#      new principal starts with zero bindings.
#   2. identityType == AGENT_IDENTITY but its principal has no project-level IAM
#      -> already orphaned (a previous deploy converted it and nobody re-granted).
# Either way the fix is the same: bind roles to the principal:// member, wait a
# few minutes for propagation, then deploy.
if [[ -n "$AGENT_ENGINE_ID" && "${SKIP_IAM_PREFLIGHT:-0}" != "1" ]]; then
    _ENG_JSON="$(curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID}" 2>/dev/null || true)"
    _ID_TYPE="$(printf '%s' "$_ENG_JSON" | python3 -c \
        "import json,sys
try: d=json.load(sys.stdin)
except Exception: print(''); raise SystemExit
print((d.get('spec') or {}).get('identityType') or d.get('identityType') or '')" 2>/dev/null || true)"

    if [[ -n "$_ID_TYPE" ]]; then
        _PRINCIPAL="principal://agents.global.proj-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null).system.id.goog/resources/aiplatform/projects/$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null)/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID}"
        _NROLES="$(gcloud projects get-iam-policy "$PROJECT_ID" --format=json 2>/dev/null | python3 -c \
            "import json,sys
d=json.load(sys.stdin)
print(sum(1 for b in d.get('bindings',[]) if any('${AGENT_ENGINE_ID}' in m for m in b.get('members',[]))))" 2>/dev/null || echo 0)"

        if [[ "$_ID_TYPE" != "AGENT_IDENTITY" ]]; then
            echo "!! Engine $AGENT_ENGINE_ID currently has identityType=$_ID_TYPE."
            echo "   .agent_engine_config.json requests AGENT_IDENTITY, so THIS DEPLOY WILL"
            echo "   CONVERT IT. The new SPIFFE principal inherits NO IAM — every Firestore,"
            echo "   Pub/Sub and Cloud Run call will fail PERMISSION_DENIED afterwards."
            echo "   Grant roles to this member first, then re-run:"
            echo "     $_PRINCIPAL"
            echo "   Override (you have already granted them): SKIP_IAM_PREFLIGHT=1 $0"
            exit 1
        fi
        if [[ "$_NROLES" -eq 0 ]]; then
            echo "!! Engine $AGENT_ENGINE_ID is AGENT_IDENTITY but its principal holds"
            echo "   ZERO project IAM bindings — it is already orphaned, and deploying"
            echo "   will produce a container that starts fine then fails every call."
            echo "   Grant roles to:  $_PRINCIPAL"
            echo "   Override: SKIP_IAM_PREFLIGHT=1 $0"
            exit 1
        fi
        echo "   pre-flight OK: identityType=$_ID_TYPE, ${_NROLES} project roles bound"
    else
        echo "   pre-flight skipped: engine $AGENT_ENGINE_ID not found (new engine?)"
    fi
fi

# --- Agent Gateway: trust its TLS inspection CA, NON-PRODUCTION ENGINES ONLY ----
# Agent Gateway inspects traffic, so it terminates TLS and re-signs with its own
# "Agent Gateway TLS Inspection CA". Containers that don't trust that CA fail every
# call with SSLCertVerificationError. AGENT_GATEWAY_CA_BUNDLE=1 makes
# coordinator_engine/agent.py::_trust_agent_gateway_ca() merge that CA into
# certifi's bundle and point requests/stdlib/gRPC at the result.
#
# DEAD END, recorded so nobody retries it: GOOGLE_API_USE_CLIENT_CERTIFICATE=false
# looks like the cheaper fix (stop dialing *.mtls.* endpoints so there is nothing
# to inspect-and-break). Tried 2026-08-30 — it does change the hostnames, and then
# every call dies with OSError 101 "Network is unreachable". Behind this gateway
# ONLY the mTLS endpoints are routable, so trusting the CA is the only path.
#
# Injected here rather than committed to .env because .env is SHARED with
# production, and production does not route through the gateway — it must not
# carry an extra trusted MITM CA it has no use for. Restored on exit.
ENV_FILE="${REPO_ROOT}/${AGENT_DIR}/.env"
ENV_BACKUP=""
CA_BUNDLE_LOCAL=""
CA_BUNDLE_CONTAINER_PATH="/app/agents/${AGENT_DIR}/ca_bundle_with_gateway.pem"
if [[ "$AGENT_ENGINE_ID" != "$PROD_ENGINE_ID" && "${GATEWAY_CA_BUNDLE:-1}" == "1" ]]; then
    ENV_BACKUP="$(mktemp)"
    cp "$ENV_FILE" "$ENV_BACKUP"
    if ! grep -q '^AGENT_GATEWAY_CA_BUNDLE=' "$ENV_FILE"; then
        printf '\n# Injected by deploy_coordinator_engine.sh for a non-production engine.\n' >> "$ENV_FILE"
        printf '# Trust the Agent Gateway TLS inspection CA; see the block in that script.\n' >> "$ENV_FILE"
        printf 'AGENT_GATEWAY_CA_BUNDLE=1\n' >> "$ENV_FILE"
        # The bundle must exist BEFORE the process starts, and the env vars must
        # come from the container environment — not from Python at import time.
        # Measured 2026-08-30: gRPC's first handshake failure was logged at
        # 17:15:56 and agent.py wrote its /tmp bundle at 17:20:05, four minutes
        # later. gRPC's C-core resolves and CACHES its default roots during
        # startup; finding no file at the named path, it fell back to its embedded
        # roots and never looked again — 1 bundle write vs 148 handshake failures.
        # So the bundle is baked into the image instead, at the path ADK stages
        # the agent to (/app/agents/<agent_dir>/, cli_deploy.py:98).
        printf 'SSL_CERT_FILE=%s\n'                   "$CA_BUNDLE_CONTAINER_PATH" >> "$ENV_FILE"
        printf 'REQUESTS_CA_BUNDLE=%s\n'              "$CA_BUNDLE_CONTAINER_PATH" >> "$ENV_FILE"
        printf 'GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=%s\n' "$CA_BUNDLE_CONTAINER_PATH" >> "$ENV_FILE"
    fi
    # certifi's roots + the gateway CA. Generated here rather than committed so a
    # 200KB derived blob does not rot in the repo; removed again on exit.
    CA_BUNDLE_LOCAL="${REPO_ROOT}/${AGENT_DIR}/ca_bundle_with_gateway.pem"
    "${REPO_ROOT}/.venv/bin/python" - "$CA_BUNDLE_LOCAL" "${REPO_ROOT}/${AGENT_DIR}/agent_gateway_ca.pem" <<'PY'
import sys, certifi
out, ca = sys.argv[1], sys.argv[2]
with open(out, "w") as f:
    for src in (certifi.where(), ca):
        f.write(open(src).read().rstrip() + "\n")
print(f"    CA bundle: {out} ({open(out).read().count('BEGIN CERTIFICATE')} certs)")
PY
    echo "==> Non-production engine: injected AGENT_GATEWAY_CA_BUNDLE=1"
    echo "    (.env restored automatically on exit; production trusts no extra CA)"
fi
restore_env() {
    [[ -n "$ENV_BACKUP" ]] && cp "$ENV_BACKUP" "$ENV_FILE" && rm -f "$ENV_BACKUP"
    [[ -n "$CA_BUNDLE_LOCAL" ]] && rm -f "$CA_BUNDLE_LOCAL"
    return 0
}
trap restore_env EXIT

ARGS=(
    --project="$PROJECT_ID"
    --region="$REGION"
    --display_name="$DISPLAY_NAME"
    --extra_packages csf_coordinator
    --extra_packages csf_specialists
    --extra_packages csf_gateway
    --otel_to_cloud
    # Agent Identity: coordinator_engine/.agent_engine_config.json sets
    # identity_type=AGENT_IDENTITY, giving the agent a SPIFFE identity with an
    # auto-rotating 24h X.509 cert instead of the shared Google-managed
    # aiplatform-re service agent. identity_type is fixed AT CREATION — an
    # existing engine cannot be retrofitted, which is why adopting it required a
    # brand-new engine ($PROD_ENGINE_ID) rather than an in-place update, and why
    # any future identity change also means a new engine.
    # ABSOLUTE path is required. ADK validates this file with os.path.exists()
    # AFTER it has copied the agent into a coordinator_engine_tmp*/ staging dir
    # and changed directory (cli_deploy.py ~line 1016), so a relative path
    # silently stops resolving and the deploy dies with a "config file not
    # found" error naming a path that plainly does exist.
    --agent_engine_config_file "${REPO_ROOT}/${AGENT_DIR}/.agent_engine_config.json"
)

if [[ -n "$AGENT_ENGINE_ID" ]]; then
    echo "==> Updating existing Agent Engine $AGENT_ENGINE_ID in place"
    ARGS+=(--agent_engine_id "$AGENT_ENGINE_ID")
else
    echo "==> Creating a NEW Agent Engine resource"
fi

echo "    project=$PROJECT_ID region=$REGION agent_dir=$AGENT_DIR"
echo "    (Cloud Build; expect ~5-15 min)"

# `adk deploy` catches its own exceptions, prints "Deploy failed: ..." and STILL
# EXITS 0 -- observed live 2026-08-27, where a bad config path failed the deploy
# while this script cheerfully printed its success banner. set -e cannot catch
# that, so inspect the output instead of trusting the exit code.
DEPLOY_LOG="$(mktemp)"
# NOTE: must also restore .env — a bare `trap '...' EXIT` here would REPLACE the
# restore_env trap set above and leak GOOGLE_API_USE_CLIENT_CERTIFICATE into the
# shared env file that production deploys from.
trap 'rm -f "$DEPLOY_LOG"; restore_env' EXIT
poetry run adk deploy agent_engine "${ARGS[@]}" "$AGENT_DIR" 2>&1 | tee "$DEPLOY_LOG"

if grep -qiE 'Deploy failed|Traceback' "$DEPLOY_LOG"; then
    echo ""
    echo "!! DEPLOY FAILED (adk exited 0 anyway -- see the message above)."
    exit 1
fi
if ! grep -q 'Deployed to Agent Platform' "$DEPLOY_LOG"; then
    echo ""
    echo "!! No 'Deployed to Agent Platform' line -- treating as failure."
    exit 1
fi

echo ""
ENGINE_RESOURCE="projects/220244569524/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID:-<new-id>}"
echo "======================================================================"
echo "  Deployed. Verify before trusting it:"
echo "    REASONING_ENGINE_RESOURCE=${ENGINE_RESOURCE} \\"
echo "      poetry run python -m spike.verify_native_run <session-id> govern"
echo ""
echo "  A clean exit here does NOT mean the container imports — Gate 3's"
echo "  failure exited 0 and died on first invocation. Always invoke once."
echo ""
echo "  Agent Gateway binding (expect null unless this is the gateway engine —"
echo "  production ${PROD_ENGINE_ID} must always be null):"
echo "    curl -s -H \"Authorization: Bearer \$(gcloud auth print-access-token)\" \\"
echo "      https://${REGION}-aiplatform.googleapis.com/v1/${ENGINE_RESOURCE} \\"
echo "      | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"spec\"][\"deploymentSpec\"].get(\"agentGatewayConfig\"))'"
echo "======================================================================"
