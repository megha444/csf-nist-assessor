#!/usr/bin/env bash
# =============================================================================
# Agent Identity — one least-privilege service account per workload.
#
#   bash infra/setup_service_accounts.sh            # create + grant
#   bash infra/setup_service_accounts.sh --dry-run  # print, change nothing
#
# BEFORE: csf-gateway@ ran the API service, the scoring Job, AND the Streamlit
# UI, holding 13 roles including run.developer and storage.objectAdmin. The
# public UI therefore carried permission to trigger Cloud Run Jobs and administer
# every object in both buckets, neither of which it uses.
#
# AFTER: three accounts, each scoped to what its workload actually calls. The
# Coordinator is untouched — Agent Runtime assigns it its own managed identity
# (service-…@gcp-sa-aiplatform-re.iam), which is the Agent Identity component
# proper; this script covers the three workloads Agent Runtime does not host.
#
# Role sets were derived by reading the code, not by guessing:
#   * csf-ui imports csf_specialists.agents only to render a list of Function
#     names, but that import constructs all 6 agents and each writes its Firestore
#     registration -- so the UI genuinely needs datastore.user. It never touches
#     Qdrant, Vertex, GCS or Pub/Sub (verified: zero references in csf_ui/app.py),
#     so it gets none of those.
#   * csf-worker queries Qdrant and Vertex and reads/writes Firestore, but never
#     touches Cloud Storage (verified: no storage references in the scoring path)
#     and never triggers Cloud Run Jobs -- so no storage, no run.developer.
#   * csf-gateway keeps run.developer and the Pub/Sub roles ONLY because the
#     in-process fallback path (COORDINATOR_MODE=inprocess) still dispatches work
#     itself. If that fallback is ever removed, both can go.
#
# This script only ADDS bindings. It never removes them, so re-running is safe
# and it cannot lock you out. Roles being dropped from csf-gateway are listed at
# the end as explicit commands for you to run deliberately.
# =============================================================================
set -euo pipefail

PROJECT_ID="csf-assessor-hackathon"
DRY_RUN="${1:-}"

run() {
    if [[ "$DRY_RUN" == "--dry-run" ]]; then
        echo "    [dry-run] $*"
        return 0
    fi
    # Retry: rapid sequential add-iam-policy-binding calls race on the project
    # policy etag and fail with a concurrent-modification error. Observed live
    # on the very first run of this script. Idempotent, so retrying is safe.
    local attempt out
    for attempt in 1 2 3 4 5; do
        if out="$("$@" 2>&1)"; then
            return 0
        fi
        if [[ $attempt -lt 5 ]]; then
            sleep $(( attempt * 3 ))
        fi
    done
    echo "    FAILED after 5 attempts: $*"
    echo "      last error: $(echo "$out" | tail -2 | tr '\n' ' ')"
    return 1
}

ensure_sa() {
    local name="$1" display="$2"
    local email="${name}@${PROJECT_ID}.iam.gserviceaccount.com"
    if gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1; then
        echo "  exists: $email"
    else
        echo "  creating: $email"
        run gcloud iam service-accounts create "$name" \
            --project="$PROJECT_ID" --display-name="$display"
    fi
}

grant() {
    local email="$1"; shift
    for role in "$@"; do
        echo "    + $role"
        run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:$email" --role="$role" --condition=None
    done
}

echo "=== csf-worker: scoring Job (Firestore + Vertex + Qdrant + Pub/Sub) ==="
ensure_sa csf-worker "CSF Worker (scoring Job)"
grant "csf-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
    roles/datastore.user \
    roles/aiplatform.user \
    roles/pubsub.subscriber \
    roles/pubsub.publisher \
    roles/secretmanager.secretAccessor \
    roles/modelarmor.user \
    roles/cloudtrace.agent \
    roles/logging.logWriter \
    roles/monitoring.metricWriter

echo "=== csf-ui: Streamlit front end (Firestore reads + gateway API key only) ==="
ensure_sa csf-ui "CSF UI (Streamlit)"
grant "csf-ui@${PROJECT_ID}.iam.gserviceaccount.com" \
    roles/datastore.user \
    roles/secretmanager.secretAccessor \
    roles/logging.logWriter \
    roles/monitoring.metricWriter

cat <<EOF

=== Done. ===

csf-gateway@ keeps its existing roles; deploy_gateway.sh manages them.

Two roles on csf-gateway@ are broader than needed. They are NOT removed
automatically, because revoking IAM while services are live should be a
deliberate act. Run these yourself once the per-service SAs are deployed and
verified:

  # storage.objectAdmin -> objectUser (drops object-level IAM administration;
  # ingest only needs to create/read/delete objects)
  gcloud projects add-iam-policy-binding $PROJECT_ID \\
    --member="serviceAccount:csf-gateway@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/storage.objectUser" --condition=None
  gcloud projects remove-iam-policy-binding $PROJECT_ID \\
    --member="serviceAccount:csf-gateway@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/storage.objectAdmin"

  # run.invoker is unused: the UI reaches the gateway over public HTTPS with an
  # API key, not IAM, and job triggering is covered by run.developer.
  gcloud projects remove-iam-policy-binding $PROJECT_ID \\
    --member="serviceAccount:csf-gateway@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/run.invoker"

Verify the split afterwards:
  for sa in csf-gateway csf-worker csf-ui; do
    echo "== \$sa"
    gcloud projects get-iam-policy $PROJECT_ID \\
      --flatten="bindings[].members" \\
      --filter="bindings.members:\$sa@${PROJECT_ID}.iam.gserviceaccount.com" \\
      --format="value(bindings.role)" | sort
  done
EOF
