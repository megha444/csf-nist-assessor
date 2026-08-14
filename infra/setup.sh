#!/usr/bin/env bash
#
# CSF Assessor Fleet - GCP Infrastructure Setup
# All Things Agentic Hackathon 2026
#
# Idempotent-ish: safe to re-run. Existing resources will be skipped with warnings.
# Prerequisites: gcloud CLI installed, authenticated (gcloud auth login + gcloud auth application-default login)
#
# Usage:
#   1. Edit PROJECT_ID below if starting fresh, or leave as-is if continuing
#   2. chmod +x infra/setup.sh
#   3. ./infra/setup.sh
#
set -euo pipefail

# =============================================================================
# CONFIGURATION - edit these
# =============================================================================
export PROJECT_ID="csf-assessor-hackathon"
export PROJECT_NAME="CSF Assessor Fleet"
export REGION="us-central1"
export ZONE="us-central1-a"

# =============================================================================
# HELPERS
# =============================================================================
info()  { echo -e "\n\033[1;34m[info]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[warn]\033[0m  $*"; }
error() { echo -e "\033[1;31m[error]\033[0m $*" >&2; }

# =============================================================================
# STEP 1: Project creation and billing (skip if already done)
# =============================================================================
info "Checking project $PROJECT_ID"
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  info "Creating project $PROJECT_ID"
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"
else
  warn "Project $PROJECT_ID already exists, skipping create"
fi

gcloud config set project "$PROJECT_ID"
gcloud config set compute/region "$REGION"
gcloud config set compute/zone "$ZONE"

# ADC alignment (fixes the "quota project" warning)
gcloud auth application-default set-quota-project "$PROJECT_ID" || true

# Verify billing is linked (manual step if not)
if ! gcloud billing projects describe "$PROJECT_ID" --format="value(billingEnabled)" 2>/dev/null | grep -q "True"; then
  error "Billing not linked. Link manually at:"
  error "  https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
  exit 1
fi

# =============================================================================
# STEP 2: Enable required APIs
# =============================================================================
info "Enabling APIs (takes 2-3 min)"
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  dlp.googleapis.com \
  artifactregistry.googleapis.com

# =============================================================================
# STEP 3: Firestore (native mode, single region)
# =============================================================================
info "Creating Firestore database"
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create \
    --location="$REGION" \
    --type=firestore-native
else
  warn "Firestore already exists, skipping"
fi

# =============================================================================
# STEP 4: Cloud Storage buckets
# =============================================================================
info "Creating Cloud Storage buckets"

# Raw uploaded policy documents (keep forever, they are user uploads)
if ! gcloud storage buckets describe "gs://${PROJECT_ID}-raw-docs" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${PROJECT_ID}-raw-docs" \
    --location="$REGION" \
    --uniform-bucket-level-access
else
  warn "Bucket ${PROJECT_ID}-raw-docs already exists, skipping"
fi

# Processed artifacts (embeddings, extracted evidence, reports) with 30-day lifecycle
if ! gcloud storage buckets describe "gs://${PROJECT_ID}-artifacts" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${PROJECT_ID}-artifacts" \
    --location="$REGION" \
    --uniform-bucket-level-access

  cat > /tmp/lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 30}
      }
    ]
  }
}
EOF
  gcloud storage buckets update "gs://${PROJECT_ID}-artifacts" \
    --lifecycle-file=/tmp/lifecycle.json
  rm /tmp/lifecycle.json
else
  warn "Bucket ${PROJECT_ID}-artifacts already exists, skipping"
fi

# =============================================================================
# STEP 5: Artifact Registry (for Cloud Run container images)
# =============================================================================
info "Creating Artifact Registry repository"
if ! gcloud artifacts repositories describe csf-images \
    --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create csf-images \
    --repository-format=docker \
    --location="$REGION" \
    --description="Container images for CSF Assessor agents"
else
  warn "Artifact Registry csf-images already exists, skipping"
fi

# =============================================================================
# STEP 6: Pub/Sub topics + subscriptions
# One topic per Function agent (coordinator dispatches to these)
# One shared results topic (Function agents publish scores back)
# =============================================================================
info "Creating Pub/Sub topics + subscriptions"

for FN in govern identify protect detect respond recover; do
  TOPIC="csf-dispatch-$FN"
  SUB="${TOPIC}-sub"

  if ! gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1; then
    gcloud pubsub topics create "$TOPIC"
  else
    warn "Topic $TOPIC exists, skipping"
  fi

  if ! gcloud pubsub subscriptions describe "$SUB" >/dev/null 2>&1; then
    gcloud pubsub subscriptions create "$SUB" \
      --topic="$TOPIC" \
      --ack-deadline=600
  else
    warn "Subscription $SUB exists, skipping"
  fi
done

# Results topic (agents publish back to coordinator)
if ! gcloud pubsub topics describe csf-results >/dev/null 2>&1; then
  gcloud pubsub topics create csf-results
fi
if ! gcloud pubsub subscriptions describe csf-results-sub >/dev/null 2>&1; then
  gcloud pubsub subscriptions create csf-results-sub \
    --topic=csf-results \
    --ack-deadline=600
fi

# =============================================================================
# STEP 7: Secret Manager (placeholder pattern)
# Add real secrets later via:
#   echo -n "actual-value" | gcloud secrets versions add SECRET_NAME --data-file=-
# =============================================================================
info "Creating Secret Manager placeholder"
if ! gcloud secrets describe app-config >/dev/null 2>&1; then
  echo -n "placeholder-value" | gcloud secrets create app-config \
    --data-file=- \
    --replication-policy=user-managed \
    --locations="$REGION"
else
  warn "Secret app-config exists, skipping"
fi

# =============================================================================
# STEP 8 (OPTIONAL): Cloud SQL Postgres for scored subcategories
#
# NOT NEEDED for the hackathon demo. Firestore handles all persistence needs at
# this scale. Cloud SQL costs ~$8/month idle (eats hackathon credits).
#
# If you decide later that you need relational queries (complex aggregations,
# joins across assessments, cost dashboard with SQL), you have two options:
#   (a) uncomment this block and pay ~$8/mo out of credits
#   (b) use Supabase free tier (250MB, no cost)
#
# Uncomment below only if (a).
# =============================================================================
# info "Creating Cloud SQL Postgres instance (this takes ~5 min)"
# if ! gcloud sql instances describe csf-scoring-db >/dev/null 2>&1; then
#   gcloud sql instances create csf-scoring-db \
#     --database-version=POSTGRES_15 \
#     --tier=db-f1-micro \
#     --region="$REGION" \
#     --storage-size=10GB \
#     --storage-type=HDD \
#     --no-backup
#
#   gcloud sql databases create csf_scoring --instance=csf-scoring-db
#
#   # NOTE: change this password. Then store in Secret Manager:
#   #   echo -n "REAL_PASSWORD" | gcloud secrets create csf-db-password --data-file=- \
#   #     --replication-policy=user-managed --locations="$REGION"
#   gcloud sql users create csf_app --instance=csf-scoring-db --password="CHANGE_ME"
# else
#   warn "Cloud SQL instance csf-scoring-db exists, skipping"
# fi

# =============================================================================
# STEP 9: Vertex AI smoke test
# =============================================================================
info "Testing Vertex AI (Gemini) access"
TOKEN=$(gcloud auth print-access-token)

# Gemini 3.x on this project is only served via the `global` endpoint (not regional).
# Hackathon requires Gemini 3.5 or newer.
for MODEL in gemini-3.5-flash gemini-3.7-flash gemini-3.5-flash-lite; do
  RESPONSE=$(curl -s -o /tmp/gemini_test.json -w "%{http_code}" -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "https://aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/publishers/google/models/${MODEL}:generateContent" \
    -d '{
      "contents": [{"role": "user", "parts": [{"text": "Say hello in one word."}]}],
      "generationConfig": {"maxOutputTokens": 200}
    }')

  if [ "$RESPONSE" = "200" ]; then
    info "Vertex AI working with model: $MODEL"
    cat /tmp/gemini_test.json | head -20
    rm /tmp/gemini_test.json
    break
  else
    warn "Model $MODEL returned HTTP $RESPONSE, trying next"
  fi
done

# =============================================================================
# VERIFICATION
# =============================================================================
info "Setup complete. Verification:"

echo ""
echo "--- Enabled APIs ---"
gcloud services list --enabled \
  --filter="config.name:(aiplatform.googleapis.com OR run.googleapis.com OR firestore.googleapis.com OR pubsub.googleapis.com OR storage.googleapis.com OR secretmanager.googleapis.com)" \
  --format="value(config.name)"

echo ""
echo "--- Storage buckets ---"
gcloud storage buckets list --filter="name:${PROJECT_ID}" --format="value(name)"

echo ""
echo "--- Pub/Sub topics ---"
gcloud pubsub topics list --filter="name:csf-" --format="value(name)"

echo ""
echo "--- Firestore ---"
gcloud firestore databases describe --database="(default)" --format="value(locationId,type)"

echo ""
info "Done. Next: build the ADK hello-world agent (Thu Aug 13 EOD task)"
