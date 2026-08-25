#!/usr/bin/env bash
#
# CSF Assessor Fleet — Cloud Run deploy for csf-gateway.
#
# Idempotent-ish: SA, IAM bindings, and secret are created only if missing.
# The Cloud Run service itself is (re)deployed on every run.
#
# Requires: gcloud CLI authenticated (gcloud auth login) with the target
# project as the active config. Reads QDRANT_URL, QDRANT_API_KEY, and
# QDRANT_COLLECTION from .env at repo root.
#
# Usage:
#   chmod +x infra/deploy_gateway.sh
#   ./infra/deploy_gateway.sh
#
set -euo pipefail

# =============================================================================
# CONFIG
# =============================================================================
PROJECT_ID="csf-assessor-hackathon"
REGION="us-central1"             # Cloud Run region (Vertex/Gemini stays 'global')
SERVICE="csf-gateway"
SA_NAME="csf-gateway"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="qdrant-api-key"
GATEWAY_KEY_SECRET_NAME="gateway-api-key"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

info()  { echo -e "\n\033[1;34m[info]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[warn]\033[0m  $*"; }
error() { echo -e "\033[1;31m[error]\033[0m $*" >&2; }

env_read() {
    # Read a KEY from .env, strip surrounding whitespace + trailing comments
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" | head -1 | sed -E "s/^${key}=//" | sed -E 's/[[:space:]]*#.*$//' | awk '{$1=$1};1'
}

if [ ! -f "$ENV_FILE" ]; then
    error ".env not found at $ENV_FILE"
    exit 1
fi

QDRANT_URL="$(env_read QDRANT_URL)"
QDRANT_API_KEY="$(env_read QDRANT_API_KEY)"
QDRANT_COLLECTION="$(env_read QDRANT_COLLECTION)"
GATEWAY_API_KEY="$(env_read GATEWAY_API_KEY)"
GATEWAY_RATE_LIMIT_PER_MINUTE="$(env_read GATEWAY_RATE_LIMIT_PER_MINUTE)"
GATEWAY_RATE_LIMIT_PER_MINUTE="${GATEWAY_RATE_LIMIT_PER_MINUTE:-2000}"

if [ -z "$QDRANT_URL" ] || [ -z "$QDRANT_API_KEY" ] || [ -z "$QDRANT_COLLECTION" ]; then
    error "QDRANT_URL / QDRANT_API_KEY / QDRANT_COLLECTION must all be set in .env"
    exit 1
fi

if [ -z "$GATEWAY_API_KEY" ]; then
    error "GATEWAY_API_KEY must be set in .env before deploying — this service is --allow-unauthenticated,"
    error "so a blank key means anyone with the URL can call every route. Generate one with:"
    error "  openssl rand -hex 32"
    exit 1
fi

info "Project=$PROJECT_ID  Region=$REGION  Service=$SERVICE"

# =============================================================================
# 1. Service account
# =============================================================================
info "Ensuring service account $SA_EMAIL"
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="CSF Gateway Cloud Run SA" \
        --project="$PROJECT_ID"
else
    warn "SA already exists, skipping create"
fi

# =============================================================================
# 2. IAM roles for the SA (idempotent — safe to re-apply)
# =============================================================================
info "Granting IAM roles"
for role in \
        roles/aiplatform.user \
        roles/datastore.user \
        roles/storage.objectAdmin \
        roles/secretmanager.secretAccessor \
        roles/logging.logWriter \
        roles/monitoring.metricWriter \
        roles/pubsub.publisher \
        roles/pubsub.subscriber \
        roles/run.invoker \
        roles/run.developer \
        roles/cloudtrace.agent; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$role" \
        --condition=None \
        --quiet > /dev/null
    echo "  ✓ $role"
done

# =============================================================================
# 3. Qdrant API key → Secret Manager
# =============================================================================
info "Ensuring secret '$SECRET_NAME' contains the current Qdrant API key"
if ! gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo -n "$QDRANT_API_KEY" | gcloud secrets create "$SECRET_NAME" \
        --data-file=- \
        --replication-policy=user-managed \
        --locations="$REGION" \
        --project="$PROJECT_ID"
    echo "  ✓ secret created"
else
    # Add a new version if the value has changed; harmless if it hasn't
    CURRENT=$(gcloud secrets versions access latest --secret="$SECRET_NAME" --project="$PROJECT_ID" 2>/dev/null || echo "")
    if [ "$CURRENT" != "$QDRANT_API_KEY" ]; then
        echo -n "$QDRANT_API_KEY" | gcloud secrets versions add "$SECRET_NAME" \
            --data-file=- --project="$PROJECT_ID" > /dev/null
        echo "  ✓ secret updated (new version)"
    else
        warn "secret already matches .env, no new version created"
    fi
fi

# =============================================================================
# 4. Gateway API key → Secret Manager
# =============================================================================
info "Ensuring secret '$GATEWAY_KEY_SECRET_NAME' contains the current gateway API key"
if ! gcloud secrets describe "$GATEWAY_KEY_SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo -n "$GATEWAY_API_KEY" | gcloud secrets create "$GATEWAY_KEY_SECRET_NAME" \
        --data-file=- \
        --replication-policy=user-managed \
        --locations="$REGION" \
        --project="$PROJECT_ID"
    echo "  ✓ secret created"
else
    CURRENT=$(gcloud secrets versions access latest --secret="$GATEWAY_KEY_SECRET_NAME" --project="$PROJECT_ID" 2>/dev/null || echo "")
    if [ "$CURRENT" != "$GATEWAY_API_KEY" ]; then
        echo -n "$GATEWAY_API_KEY" | gcloud secrets versions add "$GATEWAY_KEY_SECRET_NAME" \
            --data-file=- --project="$PROJECT_ID" > /dev/null
        echo "  ✓ secret updated (new version)"
    else
        warn "secret already matches .env, no new version created"
    fi
fi

# =============================================================================
# 5. Deploy
# =============================================================================
info "Deploying $SERVICE (this uses Cloud Build; expect 3-5 min the first time)"

ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
ENV_VARS+=",GOOGLE_CLOUD_LOCATION=global"
ENV_VARS+=",GOOGLE_GENAI_USE_VERTEXAI=TRUE"
ENV_VARS+=",GCS_RAW_BUCKET=${PROJECT_ID}-raw-docs"
ENV_VARS+=",GCS_ARTIFACTS_BUCKET=${PROJECT_ID}-artifacts"
ENV_VARS+=",GEMINI_FLASH_MODEL=gemini-3.5-flash"
ENV_VARS+=",GEMINI_PRO_MODEL=gemini-3.7-flash"
ENV_VARS+=",EMBEDDING_MODEL=text-embedding-004"
ENV_VARS+=",QDRANT_URL=${QDRANT_URL}"
ENV_VARS+=",QDRANT_COLLECTION=${QDRANT_COLLECTION}"
ENV_VARS+=",GATEWAY_RATE_LIMIT_PER_MINUTE=${GATEWAY_RATE_LIMIT_PER_MINUTE}"

gcloud run deploy "$SERVICE" \
    --source "$REPO_ROOT" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --no-cpu-throttling \
    --min-instances=0 \
    --max-instances=3 \
    --timeout=600s \
    --set-env-vars="$ENV_VARS" \
    --set-secrets="QDRANT_API_KEY=${SECRET_NAME}:latest,GATEWAY_API_KEY=${GATEWAY_KEY_SECRET_NAME}:latest"

# =============================================================================
# 6. Post-deploy smoke test
# =============================================================================
URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")
info "Deployed to: $URL"

info "Smoke test: GET /health (open, no key needed)"
sleep 3
curl -sS "$URL/health" | python3 -m json.tool || warn "smoke test failed"

info "Smoke test: POST /sessions with no key (expect 401)"
STATUS=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$URL/sessions")
if [ "$STATUS" = "401" ]; then
    echo "  ✓ unauthenticated request correctly rejected (401)"
else
    warn "expected 401 with no X-API-Key, got $STATUS — auth may not be enforced"
fi

info "Smoke test: POST /sessions with the real key (expect 201)"
STATUS=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$URL/sessions" -H "X-API-Key: ${GATEWAY_API_KEY}")
if [ "$STATUS" = "201" ]; then
    echo "  ✓ authenticated request succeeded (201)"
else
    warn "expected 201 with a valid X-API-Key, got $STATUS"
fi

echo ""
info "Done."
echo "  Try:  curl -X POST $URL/sessions -H \"X-API-Key: \${GATEWAY_API_KEY}\""
echo "  Docs: $URL/docs  (use the Authorize button to set X-API-Key once for all Try-it-out calls)"
