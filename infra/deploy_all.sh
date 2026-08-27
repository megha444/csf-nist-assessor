#!/usr/bin/env bash
# =============================================================================
# Deploy the ENTIRE CSF Assessor Fleet to Cloud Run in one command:
#   1. csf-gateway  — API (Cloud Run service)      via infra/deploy_gateway.sh
#   2. csf-worker   — scoring (Cloud Run Job)
#   3. csf-ui       — Streamlit UI (Cloud Run service), pointed at the gateway
#
#   bash infra/deploy_all.sh
#
# Prereqs: run from the repo root, gcloud authed to the project, and a populated
# .env at repo root. deploy_gateway.sh (step 1) reads GATEWAY_API_KEY + the Qdrant
# creds from .env and provisions the `gateway-api-key` / `qdrant-api-key` Secret
# Manager secrets that the worker and UI reuse — so the gateway MUST run first.
# =============================================================================
set -euo pipefail

PROJECT_ID="csf-assessor-hackathon"
REGION="us-central1"
SA_EMAIL="csf-gateway@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Env shared by all three containers (Vertex + storage + models + Qdrant).
# Keep these in sync with the ENV_VARS block in deploy_gateway.sh (the gateway
# sets its own copy there); the worker + UI get them from here.
QDRANT_URL="https://4d43b98d-9fbe-4730-ab0a-0bf28924458b.us-east4-0.gcp.cloud.qdrant.io"
SHARED_ENV="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
SHARED_ENV+=",GOOGLE_CLOUD_LOCATION=global"
SHARED_ENV+=",GOOGLE_GENAI_USE_VERTEXAI=TRUE"
SHARED_ENV+=",GCS_RAW_BUCKET=${PROJECT_ID}-raw-docs"
SHARED_ENV+=",GCS_ARTIFACTS_BUCKET=${PROJECT_ID}-artifacts"
SHARED_ENV+=",GEMINI_FLASH_MODEL=gemini-3.5-flash"
SHARED_ENV+=",GEMINI_PRO_MODEL=gemini-3.7-flash"
SHARED_ENV+=",EMBEDDING_MODEL=text-embedding-004"
SHARED_ENV+=",QDRANT_URL=${QDRANT_URL}"
SHARED_ENV+=",QDRANT_COLLECTION=csf_chunks"

# Fortified — PII scrub + Model Armor threat gate (worker/scoring path).
# block=false on the always-on judge-facing deployment (a false positive must not
# reject legitimate evidence); the gateway sets its own copy in deploy_gateway.sh.
ARMOR_ENV="PII_SCRUB_ENABLED=true,MODEL_ARMOR_ENABLED=true,MODEL_ARMOR_LOCATION=us,MODEL_ARMOR_TEMPLATE_ID=my-test-template,MODEL_ARMOR_BLOCK_ON_INJECTION=false"

echo "==> [1/3] Gateway (API) — IAM roles, secrets, build, deploy, smoke test"
bash infra/deploy_gateway.sh

GATEWAY_URL="$(gcloud run services describe csf-gateway --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
echo "    gateway URL: $GATEWAY_URL"

echo "==> [2/3] Worker (scoring — Cloud Run Job)"
gcloud run jobs deploy csf-worker \
    --source . \
    --command python \
    --args csf_specialists/worker.py,--function,govern,--timeout,60 \
    --region "$REGION" --project "$PROJECT_ID" \
    --service-account "$SA_EMAIL" \
    --set-secrets QDRANT_API_KEY=qdrant-api-key:latest \
    --set-env-vars "${SHARED_ENV},${ARMOR_ENV}" \
    --quiet

echo "==> [3/3] UI (Streamlit — Cloud Run service), pointed at $GATEWAY_URL"
gcloud run deploy csf-ui \
    --source . \
    --command streamlit \
    --args run,csf_ui/app.py,--server.port=8080,--server.address=0.0.0.0,--server.headless=true \
    --region "$REGION" --project "$PROJECT_ID" \
    --service-account "$SA_EMAIL" \
    --allow-unauthenticated --port 8080 \
    --memory 1Gi --cpu 1 --min-instances 0 --max-instances 3 --timeout 600s --session-affinity \
    --set-env-vars "${SHARED_ENV},GATEWAY_URL=${GATEWAY_URL}" \
    --set-secrets QDRANT_API_KEY=qdrant-api-key:latest,GATEWAY_API_KEY=gateway-api-key:latest \
    --quiet

UI_URL="$(gcloud run services describe csf-ui --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
echo ""
echo "======================================================================"
echo "  Full system deployed to Cloud Run:"
echo "    UI  (share this): $UI_URL"
echo "    Gateway (API):    $GATEWAY_URL"
echo "    Worker (Job):     csf-worker"
echo "======================================================================"
