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

if [ -z "$QDRANT_URL" ] || [ -z "$QDRANT_API_KEY" ] || [ -z "$QDRANT_COLLECTION" ]; then
    error "QDRANT_URL / QDRANT_API_KEY / QDRANT_COLLECTION must all be set in .env"
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
        roles/run.invoker; do
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
# 4. Deploy
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
    --set-secrets="QDRANT_API_KEY=${SECRET_NAME}:latest"

# =============================================================================
# 5. Post-deploy smoke test
# =============================================================================
URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")
info "Deployed to: $URL"

info "Smoke test: GET /health"
sleep 3
curl -sS "$URL/health" | python3 -m json.tool || warn "smoke test failed"

echo ""
info "Done."
echo "  Try:  curl -X POST $URL/sessions"
echo "  Docs: $URL/docs"
