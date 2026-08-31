#!/usr/bin/env bash
# =============================================================================
# Read-only verification of the whole CSF Assessor Fleet.
#
#   bash infra/verify_deployment.sh              # everything
#   bash infra/verify_deployment.sh identity     # one section
#
# Sections: services identity runtime registry pubsub firestore endpoints traces iam
#
# Every command here is READ-ONLY -- nothing is created, changed, or deleted, so
# this is safe to run mid-demo. Use it before recording, after any deploy, and
# whenever you need to prove a Fortified component is real rather than claimed.
# =============================================================================
set -uo pipefail          # deliberately NOT -e: one failing check must not abort the report

PROJECT="csf-assessor-hackathon"
PROJNUM="220244569524"
REGION="us-central1"
GW_URL="https://csf-gateway-jdogd2dq2q-uc.a.run.app"
UI_URL="https://csf-ui-jdogd2dq2q-uc.a.run.app"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WANT="${1:-all}"
want() { [[ "$WANT" == "all" || "$WANT" == "$1" ]]; }
hdr() { printf '\n\033[1;34m=== %s ===\033[0m\n' "$1"; }

TOKEN="$(gcloud auth print-access-token 2>/dev/null)"
[[ -z "$TOKEN" ]] && { echo "No gcloud token — run: gcloud auth login"; exit 1; }

# ---------------------------------------------------------------- services
if want services; then
hdr "Cloud Run — services, revisions, and the identity each RUNS AS"
gcloud run services list --project="$PROJECT" --region="$REGION" \
  --format="table(metadata.name,status.latestReadyRevisionName,spec.template.spec.serviceAccountName)" 2>&1

echo
echo "Cloud Run Job (the 6 specialists):"
gcloud run jobs describe csf-worker --project="$PROJECT" --region="$REGION" \
  --format="value[separator='  '](metadata.name,spec.template.spec.template.spec.serviceAccountName)" 2>&1 | sed 's/^/  /'

echo
echo "Coordinator host + mode (proves the demo path is GEAP-native):"
gcloud run services describe csf-gateway --project="$PROJECT" --region="$REGION" \
  --format="value(spec.template.spec.containers[0].env)" 2>/dev/null \
  | tr ';' '\n' | grep -E 'COORDINATOR_MODE|REASONING_ENGINE|AGENT_REGISTRY' | sed 's/^/  /'
fi

# ---------------------------------------------------------------- runtime
if want runtime; then
hdr "Agent Runtime — deployed Agent Engines and their identity type"
curl -s --max-time 30 -H "Authorization: Bearer $TOKEN" \
 "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT}/locations/${REGION}/reasoningEngines" \
 | python3 -c "
import json,sys
d=json.load(sys.stdin)
for e in d.get('reasoningEngines',[]):
    s=e.get('spec',{}) or {}
    print(f\"  {e.get('displayName','?'):18s} {e['name'].split('/')[-1]}\")
    print(f\"     identityType     : {s.get('identityType') or 'None (service account)'}\")
    print(f\"     effectiveIdentity: {s.get('effectiveIdentity')}\")
    print(f\"     updated          : {e.get('updateTime')}\")
"
fi

# ---------------------------------------------------------------- identity
if want identity; then
hdr "Agent Identity — per-workload service accounts (least privilege)"
for sa in csf-gateway csf-worker csf-ui; do
  n=$(gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" \
      --filter="bindings.members:${sa}@${PROJECT}.iam.gserviceaccount.com" \
      --format="value(bindings.role)" 2>/dev/null | wc -l | tr -d ' ')
  echo "  ${sa}@ — ${n} roles:"
  gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" \
    --filter="bindings.members:${sa}@${PROJECT}.iam.gserviceaccount.com" \
    --format="value(bindings.role)" 2>/dev/null | sort | sed 's/^/      /'
done

echo
echo "  Coordinator identities (platform-assigned, NOT user-created):"
echo "    service-account engine:"
gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" \
  --filter="bindings.members:service-${PROJNUM}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --format="value(bindings.role)" 2>/dev/null | sort | sed 's/^/      /'
echo "    SPIFFE agent identity (principal://, if an AGENT_IDENTITY engine exists):"
gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" \
  --filter="bindings.members~principal://" \
  --format="value(bindings.role)" 2>/dev/null | sort -u | sed 's/^/      /'
fi

# ---------------------------------------------------------------- registry
if want registry; then
hdr "Agent Registry — native catalogue (auto- vs manually-registered)"
curl -s --max-time 30 -H "Authorization: Bearer $TOKEN" \
 "https://agentregistry.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/agents?pageSize=100" \
 | python3 -c "
import json,sys
d=json.load(sys.stdin)
if 'error' in d: print('  ERROR:', d['error'].get('message','')[:140]); raise SystemExit
ags=d.get('agents',[])
print(f'  agents: {len(ags)}')
for a in ags:
    uri=str(((a.get('attributes') or {}).get('agentregistry.googleapis.com/system/RuntimeReference') or {}).get('uri') or '')
    if uri.startswith('//aiplatform.googleapis.com/'):
        # Show the engine id: both our engines auto-register under the same
        # display name, so without it the two rows are indistinguishable.
        tag='AUTO (Agent Runtime) engine=' + uri.rstrip('/').split('/')[-1]
    elif str(a.get('agentId','')).startswith('urn:agent:googleapis.com:'): tag='Google built-in'
    else: tag='manual'
    print(f\"    {a.get('displayName','?'):32s} {tag}\")
"
for kind in endpoints services bindings; do
  cnt=$(curl -s --max-time 25 -H "Authorization: Bearer $TOKEN" \
    "https://agentregistry.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/${kind}" \
    | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('${kind}',[])))" 2>/dev/null)
  echo "  ${kind}: ${cnt:-0}"
done
echo "  (bindings: 0 is CORRECT — they require an OAuth authProvider we don't use)"
fi

# ---------------------------------------------------------------- pubsub
if want pubsub; then
hdr "Pub/Sub — dispatch topics and backlog"
gcloud pubsub topics list --project="$PROJECT" --format="value(name)" 2>/dev/null \
  | sed 's#.*/#  topic: #'
echo
echo "  Undelivered backlog (a stale backlog can hang a later run —"
echo "   clear with: gcloud pubsub subscriptions seek SUB --time=\$(date -u +%Y-%m-%dT%H:%M:%SZ))"
for sub in csf-results-sub csf-dispatch-govern-sub; do
  echo "    $sub: $(gcloud pubsub subscriptions describe "$sub" --project="$PROJECT" --format='value(name)' 2>/dev/null | sed 's#.*/##')"
done
fi

# ---------------------------------------------------------------- firestore
if want firestore; then
hdr "Firestore — data actually persisted"
cd "$REPO_ROOT" && poetry run python -c "
from google.cloud.firestore import Client
db = Client(project='$PROJECT')
sess = list(db.collection('sessions').stream())
runs = ready = 0
for s in sess:
    rs = list(db.collection('sessions').document(s.id).collection('runs').stream())
    runs += len(rs)
    ready += sum(1 for r in rs if (r.to_dict() or {}).get('status') in ('ready_for_report', 'complete'))
print(f'  sessions: {len(sess)}   runs: {runs}   completed: {ready}')
ag = list(db.collection('agents').stream())
print(f'  registered agents (Firestore mirror): {len(ag)}')
for a in sorted(ag, key=lambda x: x.id):
    d = a.to_dict() or {}
    print(f\"    {a.id:9s} caps={len(d.get('capabilities') or []):2d}  identity={d.get('iam_identity')}\")
# Memory Bank parents are phantom docs -- .stream() misses them, list_documents() does not.
orgs = list(db.collection('orgs').list_documents())
print(f'  Memory Bank orgs: {len(orgs)}')
for o in orgs:
    mem = list(o.collection('memory').stream())
    hist = max([len((m.to_dict() or {}).get('history') or []) for m in mem], default=0)
    print(f'    {o.id:24s} functions={len(mem)} deepest_history={hist}')
" 2>&1 | grep -viE 'futurewarning|gcs_utils'
fi

# ---------------------------------------------------------------- endpoints
if want endpoints; then
hdr "Live endpoints — health and auth enforcement"
printf '  gateway /health      : '; curl -s --max-time 25 "$GW_URL/health"; echo
printf '  gateway /agents nokey: '; curl -s -o /dev/null -w '%{http_code} (expect 401)\n' --max-time 25 "$GW_URL/agents"
printf '  UI                   : '; curl -s -o /dev/null -w '%{http_code} (expect 200)\n' --max-time 25 "$UI_URL"
if [[ -f "$REPO_ROOT/.env" ]]; then
  KEY=$(grep '^GATEWAY_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"'"'"' \r')
  printf '  gateway /agents +key : '
  curl -s --max-time 30 -H "X-API-Key: $KEY" "$GW_URL/agents" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['source'], '| registry reachable:', d['native_registry']['reachable'], '| specialists:', len(d['agents']))" 2>/dev/null \
    || echo "could not parse"
fi
fi

# ---------------------------------------------------------------- traces
if want traces; then
hdr "Agent Observability — Cloud Trace spans (last 2h)"
START=$(python3 -c "import datetime as dt;print((dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
for span in csf.coordinator.dispatch csf.specialist.score_category csf.model_armor; do
  n=$(curl -s --max-time 30 -H "Authorization: Bearer $TOKEN" \
    "https://cloudtrace.googleapis.com/v1/projects/${PROJECT}/traces?filter=span:${span}&startTime=${START}&pageSize=50" \
    | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('traces',[])))" 2>/dev/null)
  echo "  ${span}: ${n:-0} trace(s)"
done
echo "  Console: https://console.cloud.google.com/traces/list?project=${PROJECT}"
fi

# ---------------------------------------------------------------- iam
if want iam; then
hdr "Service accounts in the project"
gcloud iam service-accounts list --project="$PROJECT" --format="table(email,displayName)" 2>&1
fi

cat <<EOF

--------------------------------------------------------------------------
Console links
  Cloud Run        https://console.cloud.google.com/run?project=${PROJECT}
  Agent Engines    https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=${PROJECT}
                   (Sessions tab needs a user id: use  csf-gateway )
  Firestore        https://console.cloud.google.com/firestore/databases/-default-/data?project=${PROJECT}
  Pub/Sub          https://console.cloud.google.com/cloudpubsub/topic/list?project=${PROJECT}
  Cloud Trace      https://console.cloud.google.com/traces/list?project=${PROJECT}
  Logs             https://console.cloud.google.com/logs/query?project=${PROJECT}
  IAM              https://console.cloud.google.com/iam-admin/iam?project=${PROJECT}
  Agent Registry   no console page without Gemini Enterprise -- use the API above
--------------------------------------------------------------------------
EOF
