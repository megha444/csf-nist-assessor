"""
Provision Google's native **Agent Gateway** (GEAP) in Agent-to-Anywhere / egress mode.

    poetry run python infra/setup_agent_gateway.py --status          # read-only, safe
    poetry run python infra/setup_agent_gateway.py --list            # destinations + why
    poetry run python infra/setup_agent_gateway.py --create-gateway  --dry-run
    poetry run python infra/setup_agent_gateway.py --register --probe-only
    poetry run python infra/setup_agent_gateway.py --grant-egress ENGINE_ID
    poetry run python infra/setup_agent_gateway.py --attach ENGINE_ID
    poetry run python infra/setup_agent_gateway.py --create-authz
    poetry run python infra/setup_agent_gateway.py --create-model-armor
    poetry run python infra/setup_agent_gateway.py --teardown

NAMING — READ THIS FIRST
------------------------
`csf_gateway/` in this repo is our own FastAPI front door (API-key auth + rate
limiting). Google's **Agent Gateway** is an unrelated product: a managed
`networkservices.googleapis.com/agentGateways` resource that intercepts an Agent
Runtime agent's traffic and runs policy on it. They are different things and the
docs in this repo have conflated them before. Everything in this file is the
Google product.

WHAT THIS BUILDS
----------------
    Agent Runtime engine  --(all outbound calls)-->  Agent Gateway
                                                       |- IAP REQUEST_AUTHZ  (IAM, DRY_RUN)
                                                       |- Model Armor CONTENT_AUTHZ
                                                       v
                          Gemini / Firestore / Pub-Sub / Cloud Run Jobs / Trace

The gateway is DEFAULT-DENY: a destination not registered in Agent Registry is
refused. Hostname matching is EXACT — registering `aiplatform.googleapis.com`
does NOT cover `us-central1-aiplatform.mtls.googleapis.com`. That is why the
table below is long and why every entry carries its reason.

WHY EGRESS AND NOT INGRESS
--------------------------
Agent Gateway mediates only Agent Runtime and Gemini Enterprise. Our sole Agent
Runtime workload is the Coordinator, so this governs the Coordinator's *outbound*
calls. Ingress (client -> agent) would govern one hop, `streamQuery` from
csf-gateway, and would not exercise Agent Registry at all. Egress is what turns
the registry into a live allowlist rather than a catalogue.

WHY NOT IN register_agent_registry.py
-------------------------------------
That script is the fleet CATALOGUE: 7 entries, each individually argued, meant to
be read by a human. These ~24 egress destinations are an ALLOWLIST with a totally
different failure mode (a bad entry breaks egress, not a description). They are
namespaced `egress-*` so a bug here can never collide with the fleet entries.

WHY REST AND NOT gcloud
-----------------------
Local gcloud is 552.0.0 and has no `network-services agent-gateways` group; its
`iap web add-iam-policy-binding` has no `--endpoint` flag. `components install
alpha beta` pins the new components AT 552, so it does not help, and a full
`components update` would re-version the CLI every deploy script depends on days
before submission. All of these surfaces are v1 GA REST, so we use REST.

SAFETY INVARIANT
----------------
Production engine PROD_ENGINE_ID must ALWAYS have `agentGatewayConfig == null`.
`--status` asserts it. Re-run `--status` after every mutating step.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.auth.transport.requests import AuthorizedSession  # noqa: E402
import google.auth  # noqa: E402

PROJECT = "csf-assessor-hackathon"
PROJECT_NUMBER = "220244569524"
LOCATION = "us-central1"

# The engine that serves the live demo. Never attach a gateway to it.
PROD_ENGINE_ID = "403007845219434496"

GATEWAY_ID = "csf-egress-gateway"
IAP_EXTENSION_ID = "csf-gateway-iap-authz"
IAP_ENFORCED_EXTENSION_ID = "csf-gateway-iap-authz-enforced"
MA_EXTENSION_ID = "csf-gateway-modelarmor-authz"
AUTHZ_POLICY_ID = "csf-gateway-authz-policy"
MA_REQUEST_TEMPLATE_ID = "agw-request-template"
MA_RESPONSE_TEMPLATE_ID = "agw-response-template"

NS = "https://networkservices.googleapis.com/v1"
NSEC = "https://networksecurity.googleapis.com/v1beta1"
AR = "https://agentregistry.googleapis.com/v1"
AIP = f"https://{LOCATION}-aiplatform.googleapis.com/v1"
MA = f"https://modelarmor.{LOCATION}.rep.googleapis.com/v1"

NS_PARENT = f"{NS}/projects/{PROJECT}/locations/{LOCATION}"
NSEC_PARENT = f"{NSEC}/projects/{PROJECT}/locations/{LOCATION}"
AR_PARENT = f"{AR}/projects/{PROJECT}/locations/{LOCATION}"
MA_PARENT = f"{MA}/projects/{PROJECT}/locations/{LOCATION}"

GATEWAY_RESOURCE = f"projects/{PROJECT}/locations/{LOCATION}/agentGateways/{GATEWAY_ID}"

# IAP resource path for the roles/iap.egressor grant. agentregistry v1 exposes no
# {get,set}IamPolicy of its own, so the grant goes through IAP's wildcard
# `v1/{resource}:setIamPolicy`. This exact string is NOT guessable and cost an
# hour to find — it came out of gcloud 582's own source
# (api_lib/iap/util.py::AgentRegistry + generated_clients/apis/iap/v1/resources.py):
#
#   projects/{PROJECT_NUMBER}/locations/{location}/iap_web/agentRegistry
#   projects/{PROJECT_NUMBER}/locations/{location}/iap_web/agentRegistry/endpoints/{id}
#
# Two traps, both of which return an unhelpful 400 "Fail to resolve resource":
#   - iapWebId is `agentRegistry` (camelCase), NOT the `agent-registry` value you
#     pass to gcloud's --resource-type flag
#   - there is a `locations/{region}` segment; the classic `projects/{p}/iap_web/...`
#     shape used by compute/appengine does not apply here
# gcloud builds this with the project NUMBER, so we do too, but the API accepts
# the project id equally (both verified 200 live). Registry-level and per-endpoint
# paths both work; registry-level is one binding covering every destination.
IAP_REGISTRY_RESOURCE = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/iap_web/agentRegistry"
# NO TRAILING SLASH. The v1 discovery doc states the format as
# "//agentregistry.googleapis.com/projects/{project}/locations/{location}/" — with a
# trailing slash — and the API rejects precisely that with HTTP 400
# "Config validation failed ... field: resource.registries" (verified 2026-08-30).
# The documented spelling is wrong; this one is what the server accepts.
REGISTRY_REF = f"//agentregistry.googleapis.com/projects/{PROJECT}/locations/{LOCATION}"
# Max two registries, and one of them MUST be global (Google's egress setup doc).
# This is also the location IAP resolves egress endpoints in — see set_registries().
GLOBAL_REGISTRY_REF = f"//agentregistry.googleapis.com/projects/{PROJECT}/locations/global"
# IAP evaluates against locations/global regardless of the gateway's own region.
# The us-central1 binding alone leaves the global policy empty ({"etag":"ACAB"},
# no bindings), which DRY_RUN masks by logging granted:true on everything.
IAP_GLOBAL_REGISTRY_RESOURCE = f"projects/{PROJECT_NUMBER}/locations/global/iap_web/agentRegistry"


# --------------------------------------------------------------- destinations
# (host, protocolBinding, tier, justification)
#
# tier:
#   confirmed - traced to a specific call site in this repo
#   docs      - named in Google's required-allowlist or troubleshooting docs
#   guess     - plausible, unverified; cheap to include, silent failure if wrong
#
# Every host gets its `.mtls.` twin. Token binding is off
# (GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False), which unbinds
# tokens but does not obviously stop generated clients selecting mTLS endpoints.
# Registering both costs one extra registry entry; guessing wrong costs a silent
# egress failure that looks exactly like the 401 this project just escaped.
DESTINATIONS: list[tuple[str, str, str, str]] = [
    ("aiplatform.googleapis.com", "HTTP_JSON", "confirmed",
     "Gemini. judge.py:74 -> gemini_model(); GOOGLE_CLOUD_LOCATION=global resolves here."),
    (f"{LOCATION}-aiplatform.googleapis.com", "HTTP_JSON", "confirmed",
     "Managed session service: async_create_session / async_stream_query are regional."),
    ("firestore.googleapis.com", "GRPC", "confirmed",
     "Source of truth. AsyncClient at steps.py:82, coordinator.py:136, aggregate.py:46, "
     "judge.py:64, memory_bank.py:65."),
    ("pubsub.googleapis.com", "GRPC", "confirmed",
     "pubsub_client.py:34,41 — DispatchStep publishes, CollectResultsStep pulls."),
    ("run.googleapis.com", "GRPC", "confirmed",
     "steps.py:55 run_v2.JobsClient().run_job triggers csf-worker. Blocked => zero scores."),
    ("cloudtrace.googleapis.com", "GRPC", "confirmed",
     "tracing.py:47 CloudTraceSpanExporter. FAILS SILENTLY — blocking this kills the "
     "Agent Observability claim with no error surfaced anywhere."),
    ("telemetry.googleapis.com", "HTTP_JSON", "confirmed",
     "--otel_to_cloud; adk/telemetry/google_cloud.py:61-69."),
    ("agentregistry.googleapis.com", "HTTP_JSON", "docs",
     "Named in Google's minimum allowlist. Our container does not call it directly."),
    ("logging.googleapis.com", "HTTP_JSON", "docs",
     "Named in Google's minimum allowlist; platform log path may traverse it."),
    ("cloudresourcemanager.googleapis.com", "HTTP_JSON", "docs",
     "Troubleshooting doc: project-number->id resolution at agent init needs this."),
    ("oauth2.googleapis.com", "HTTP_JSON", "guess",
     "Token minting. A blocked token endpoint is indistinguishable from a 401."),
    ("sts.googleapis.com", "HTTP_JSON", "guess",
     "Token exchange for the SPIFFE identity. Same reasoning as oauth2."),
    ("iamcredentials.googleapis.com", "HTTP_JSON", "guess",
     "Token minting fallback path."),
    ("www.googleapis.com", "HTTP_JSON", "guess",
     "Legacy client fallback host."),
]

# Registered first in --probe-only: gRPC and HTTP destinations, enough to tell
# 'the gateway cannot carry gRPC' apart from 'the allowlist is incomplete' in ONE
# run, before sinking time into the full table.
#
# us-central1-aiplatform is NOT optional here, learned the hard way on 2026-08-30:
# the managed session service is the FIRST outbound call the container makes, before
# any assessment work. Omitting it produced a TLS handshake failure against
# us-central1-aiplatform.mtls.googleapis.com and a useless "stream timeout" at
# async_create_session — a failure that says nothing at all about gRPC, which is the
# only thing this probe exists to answer. A probe that cannot reach the starting
# line is not a probe.
PROBE_HOSTS = {
    "firestore.googleapis.com",        # gRPC, hot path
    "pubsub.googleapis.com",           # gRPC, hot path
    "aiplatform.googleapis.com",       # HTTP_JSON, Gemini (global endpoint)
    "us-central1-aiplatform.googleapis.com",  # HTTP_JSON, managed session service
    "telemetry.googleapis.com",        # HTTP_JSON, --otel_to_cloud
}

# Deliberately NOT registered — each for a reason, so nobody "helpfully" adds them:
#   modelarmor.us.rep.googleapis.com  MODEL_ARMOR_ENABLED is absent from
#       coordinator_engine/.env, so model_armor.py:179 returns before a client exists.
#   Qdrant Cloud                      vector_store._client_get() is lazy and only
#       reached from upsert_chunks/_search; the Coordinator calls neither.
#   metadata.google.internal          link-local, not a registrable destination. A
#       credential-fetch failure there is an abort signal, not a missing entry.


def _mtls(host: str) -> str:
    """`foo.googleapis.com` -> `foo.mtls.googleapis.com`."""
    return host.replace(".googleapis.com", ".mtls.googleapis.com", 1)


def _service_id(host: str) -> str:
    return "egress-" + host.replace(".", "-")


def _expanded() -> list[tuple[str, str, str, str]]:
    """Each destination plus its mTLS twin, flattened."""
    out: list[tuple[str, str, str, str]] = []
    for host, binding, tier, why in DESTINATIONS:
        out.append((host, binding, tier, why))
        out.append((_mtls(host), binding, tier, f"mTLS variant of {host}. {why}"))
    return out


# ------------------------------------------------------------------- helpers
def _session() -> AuthorizedSession:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return AuthorizedSession(creds)


def _wait(sess: AuthorizedSession, api_root: str, op: dict, timeout: float = 900.0) -> dict:
    """Poll a long-running Operation. Same shape as register_agent_registry.py::_wait,
    but parameterised by API root because four different services are involved here
    and each hosts its own operations collection.

    900s, not the 120s the registry script uses: attaching agentGatewayConfig
    REDEPLOYS the engine container. Measured live 2026-08-30 at 5m14s, which blew
    through an earlier 300s ceiling and raised a TimeoutError for an operation that
    then completed fine — a false alarm is worse than a slow wait here, because the
    natural next move is to retry a mutation that already succeeded."""
    name = op.get("name", "")
    if "/operations/" not in name and not name.startswith("operations/"):
        return op  # already a resource
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = sess.get(f"{api_root}/{name}", timeout=30).json()
        if d.get("done"):
            if "error" in d:
                raise RuntimeError(f"operation failed: {d['error']}")
            return d.get("response", d)
        time.sleep(3)
    raise TimeoutError(f"operation {name} did not complete in {timeout}s")


def _post(sess, url: str, body: dict, api_root: str, dry_run: bool, label: str) -> bool:
    if dry_run:
        print(f"[dry-run] POST {url}")
        print(json.dumps(body, indent=2))
        return True
    r = sess.post(url, json=body, timeout=60)
    if r.status_code == 409:
        print(f"  exists:  {label}")
        return True
    if r.status_code >= 400:
        print(f"  FAIL {label}: HTTP {r.status_code} {r.text[:400]}")
        return False
    _wait(sess, api_root, r.json())
    print(f"  created: {label}")
    return True


def _engine_gateway(sess: AuthorizedSession, engine_id: str):
    """Returns the engine's agentGatewayConfig, or the string 'MISSING' if the
    engine cannot be read at all."""
    r = sess.get(f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}",
                 timeout=30)
    if r.status_code >= 400:
        return "MISSING"
    return (r.json().get("spec", {}).get("deploymentSpec", {}) or {}).get("agentGatewayConfig")


# ------------------------------------------------------------------- actions
def status(sess: AuthorizedSession) -> int:
    """Read-only. The production-engine assertion is the point of this command."""
    print(f"=== production engine {PROD_ENGINE_ID} ===")
    gw = _engine_gateway(sess, PROD_ENGINE_ID)
    if gw in (None, "MISSING"):
        print(f"  agentGatewayConfig = {gw}  <- OK, production is unmediated")
        breach = 0
    else:
        print(f"  agentGatewayConfig = {json.dumps(gw)}")
        print("  !! INVARIANT BREACH: production is behind the gateway. Detach it now:")
        print(f"     poetry run python infra/setup_agent_gateway.py --detach {PROD_ENGINE_ID}")
        breach = 1

    print(f"\n=== agent gateways ({LOCATION}) ===")
    gws = sess.get(f"{NS_PARENT}/agentGateways", timeout=30).json().get("agentGateways", [])
    for g in gws or []:
        card = g.get("agentGatewayCard") or {}
        print(f"  {g['name'].split('/')[-1]}  mode={(g.get('googleManaged') or {}).get('governedAccessPath')}")
        print(f"      registries={g.get('registries')}")
        print(f"      mtlsEndpoint={card.get('mtlsEndpoint')}")
        print(f"      serviceExtensionsSA={card.get('serviceExtensionsServiceAccount')}")
    if not gws:
        print("  (none)")

    print("\n=== authz extensions ===")
    exts = sess.get(f"{NS_PARENT}/authzExtensions", timeout=30).json().get("authzExtensions", [])
    for e in exts or []:
        print(f"  {e['name'].split('/')[-1]:32s} service={e.get('service')} metadata={e.get('metadata')}")
    if not exts:
        print("  (none)")

    print("\n=== authz policies ===")
    pols = sess.get(f"{NSEC_PARENT}/authzPolicies", timeout=30).json().get("authzPolicies", [])
    for p in pols or []:
        print(f"  {p['name'].split('/')[-1]:32s} profile={p.get('policyProfile')} action={p.get('action')}")
        print(f"      target={(p.get('target') or {}).get('resources')}")
    if not pols:
        print("  (none)")

    print("\n=== registered egress destinations ===")
    svcs = sess.get(f"{AR_PARENT}/services?pageSize=200", timeout=30).json().get("services", [])
    egress = [s for s in svcs if s["name"].split("/")[-1].startswith("egress-")]
    print(f"  {len(egress)} egress-* of {len(svcs)} total services")

    # Two DIFFERENT Model Armor deployments, and conflating them causes a scare.
    # The app-layer one (`us` multi-region, my-test-template) is what csf-gateway
    # and csf-worker actually enforce with today and is nothing to do with the
    # gateway. The regional one below is the gateway's own network-layer
    # extension, which --create-model-armor would create. Printing only the
    # regional list made an untouched, healthy app-layer setup read as "(none)".
    print("\n=== model armor: app layer (us multi-region, live on csf-gateway/worker) ===")
    app_url = (f"https://modelarmor.us.rep.googleapis.com/v1"
               f"/projects/{PROJECT}/locations/us/templates")
    try:
        app_t = sess.get(app_url, timeout=30).json().get("templates", [])
        for t in app_t:
            print(f"  {t['name'].split('/')[-1]}")
        if not app_t:
            print("  (none) <- unexpected; MODEL_ARMOR_TEMPLATE_ID points here")
    except Exception as e:
        print(f"  (could not read: {e})")

    print("\n=== model armor: gateway network layer (us-central1) ===")
    tpls = sess.get(f"{MA_PARENT}/templates", timeout=30).json().get("templates", [])
    for t in tpls or []:
        print(f"  {t['name'].split('/')[-1]}")
    if not tpls:
        print("  (none) — expected unless you ran --create-model-armor; the "
              "app-layer templates above are the ones in use")
    return breach


def list_destinations() -> int:
    """The allowlist with its reasoning. This output is the evidence artifact —
    'here is every destination our agent may reach, and why' is the whole claim."""
    rows = _expanded()
    by_tier = {"confirmed": [], "docs": [], "guess": []}
    for host, binding, tier, why in rows:
        by_tier[tier].append((host, binding, why))
    for tier, label in (
        ("confirmed", "CONFIRMED — traced to a call site in this repo"),
        ("docs", "PER GOOGLE DOCS — required allowlist, not seen in our code"),
        ("guess", "GUESS — unverified, included because a miss fails silently"),
    ):
        print(f"\n=== {label} ({len(by_tier[tier])}) ===")
        for host, binding, why in by_tier[tier]:
            print(f"  {host:46s} {binding}")
            print(f"      {why}")
    print(f"\nTotal: {len(rows)} destinations "
          f"({len(PROBE_HOSTS) * 2} in the --probe-only subset)")
    return 0


def create_gateway(sess: AuthorizedSession, dry_run: bool) -> int:
    """ALWAYS create with `registries` set — see set_registries() for why omitting
    it produces a gateway that creates cleanly and then denies 100% of traffic.
    Only the exact reference spelling is uncertain, so that is what we retry."""
    for attempt, body in enumerate((
        {"googleManaged": {"governedAccessPath": "AGENT_TO_ANYWHERE"},
         "registries": [REGISTRY_REF]},
        {"googleManaged": {"governedAccessPath": "AGENT_TO_ANYWHERE"},
         "registries": [REGISTRY_REF + "/"]},
    ), start=1):
        print(f"-- attempt {attempt}: registries={body.get('registries', '<omitted>')}")
        if dry_run:
            print(json.dumps(body, indent=2))
            return 0
        r = sess.post(f"{NS_PARENT}/agentGateways?agentGatewayId={GATEWAY_ID}",
                      json=body, timeout=60)
        if r.status_code == 409:
            print(f"  exists: {GATEWAY_ID}")
            return 0
        if r.status_code < 400:
            _wait(sess, NS, r.json())
            print(f"  created: {GATEWAY_ID}")
            return 0
        print(f"  HTTP {r.status_code}: {r.text[:400]}")
    print("!! all attempts failed — read the last error before guessing again")
    return 1


def set_registries(sess: AuthorizedSession, dry_run: bool) -> int:
    """Link the Agent Registry to the gateway.

    DO NOT omit this for AGENT_TO_ANYWHERE, however tempting the schema looks.
    `registries` is documented Optional and the gateway CREATES FINE without it —
    but for egress the registry IS the allowlist, so a gateway with no registry
    knows about zero destinations and denies everything. Verified live 2026-08-30:
    with registries unset, every request logged

        enforcedGatewaySecurityPolicy.hostname = "240.0.0.2:443"   (synthetic IP)
        matchedRules = [{action: DENIED, name: "default_denied"}]
        agentGatewayInfo = {}                                       (no match)

    and IAP was never invoked at all (zero iap.googleapis.com audit entries), which
    reads exactly like an IAM problem and is not one. The Optional flag applies to
    CLIENT_TO_AGENT ingress, which has no registry to link.

    ONE registry only, and it must be the regional one. Google's egress setup doc
    says "Agent Gateway supports a maximum of two bound registries, one of which
    must be `global`. If you omit the global registry, requests to Google-managed
    MCP servers fail with a NOT_FOUND error." That is wrong for this API today —
    sending both is rejected (verified live 2026-08-31):

        HTTP 400 Config validation failed
        field: "resource.registries"  description: "only a single registry is supported"

    So the two-registry rule is unimplementable here. Regional is the correct
    single choice: our 28 egress destinations live in us-central1 (manual
    endpoint registration is barred in the us/eu multi-regions), and regional
    matching is proven — firestore/telemetry/us-central1-aiplatform all resolve
    to their own endpoint via agentGatewayInfo.agentRegistryResource.

    Note this does NOT fix IAP, which evaluates against
    `projects/{num}/locations/global/iap_web/agentRegistry/endpoints/...` — note
    `global`, not the gateway's region. That is a separate IAM namespace and is
    handled by granting roles/iap.egressor at IAP_GLOBAL_REGISTRY_RESOURCE."""
    url = f"{NS_PARENT}/agentGateways/{GATEWAY_ID}?updateMask=registries"
    body = {"registries": [REGISTRY_REF]}
    if dry_run:
        print(f"[dry-run] PATCH {url}")
        print(json.dumps(body, indent=2))
        return 0
    r = sess.patch(url, json=body, timeout=60)
    if r.status_code >= 400:
        # Fall back to the (documented but server-rejected) trailing-slash spelling,
        # in case the API is ever corrected to match its own discovery doc.
        print(f"  HTTP {r.status_code} without trailing slash: {r.text[:200]}")
        body = {"registries": [REGISTRY_REF + "/"]}
        r = sess.patch(url, json=body, timeout=60)
        if r.status_code >= 400:
            print(f"  HTTP {r.status_code} without: {r.text[:300]}")
            return 1
    _wait(sess, NS, r.json())
    got = sess.get(f"{NS_PARENT}/agentGateways/{GATEWAY_ID}", timeout=30).json()
    print(f"  registries now: {got.get('registries')}")
    return 0 if got.get("registries") else 1


def _url_variants(host: str) -> list[str]:
    """Every spelling of a destination the gateway might present for matching.

    The gateway matches the hostname EXACTLY (Google's troubleshooting doc is
    explicit about this) against the registered interface URLs, and different
    clients present the authority differently. Measured in gateway_requests on
    2026-08-30:

        firestore.googleapis.com                    -> matched (bare)
        telemetry.mtls.googleapis.com               -> matched (bare)
        us-central1-aiplatform.mtls.googleapis.com  -> matched (bare)
        run.mtls.googleapis.com:443                 -> NO MATCH, yet registered
        cloudresourcemanager.mtls.googleapis.com:443-> NO MATCH, not registered

    `run.mtls` was registered as `https://run.mtls.googleapis.com/` and still
    missed, and it is the one that arrived port-qualified. So register all three
    spellings rather than betting on which one a given client library emits.
    Google's own reference script registers bare `https://{hostname}`; Google's
    startup-hostname list redundantly gives both the bare and trailing-slash
    forms for the same host, which reads like they hit this too."""
    return [f"https://{host}", f"https://{host}/", f"https://{host}:443"]


def register_destinations(sess: AuthorizedSession, dry_run: bool, probe_only: bool) -> int:
    rows = _expanded()
    if probe_only:
        rows = [r for r in rows if r[0].replace(".mtls.", ".") in PROBE_HOSTS]
        print(f"probe subset: {len(rows)} destinations (gRPC + HTTP, both transports)")
    failures = 0
    for host, binding, tier, why in rows:
        sid = _service_id(host)
        ifaces = [{"url": u, "protocolBinding": binding} for u in _url_variants(host)]
        body = {
            "displayName": host,
            "description": f"[{tier}] Agent Gateway egress destination. {why}",
            "endpointSpec": {"type": "NO_SPEC"},
            "interfaces": ifaces,
        }
        if dry_run:
            print(f"[dry-run] UPSERT {sid} ({binding})")
            for u in _url_variants(host):
                print(f"[dry-run]     {u}")
            continue
        existing = sess.get(f"{AR_PARENT}/services/{sid}", timeout=30)
        if existing.status_code == 200:
            # Do NOT skip. The 17 pre-existing entries carry only the
            # trailing-slash URL, which is exactly what left run.mtls unmatched.
            have = {i.get("url") for i in existing.json().get("interfaces", [])}
            if have >= set(_url_variants(host)):
                print(f"  ok:      {sid} (all variants present)")
                continue
            url = f"{AR_PARENT}/services/{sid}?updateMask=interfaces"
            r = sess.patch(url, json={"interfaces": ifaces}, timeout=60)
            if r.status_code >= 400:
                print(f"  FAIL patch {sid}: HTTP {r.status_code} {r.text[:300]}")
                failures += 1
            else:
                _wait(sess, AR, r.json())
                print(f"  patched: {sid} (+{len(set(_url_variants(host)) - have)} variants)")
            continue
        if not _post(sess, f"{AR_PARENT}/services?serviceId={sid}", body, AR, False, sid):
            failures += 1
    return failures


def probe_iap_resource(sess: AuthorizedSession) -> int:
    """The one genuine unknown: what resource string does IAP want for an Agent
    Registry endpoint? agentregistry v1 exposes no {get,set}IamPolicy of its own,
    so the grant must go through IAP's wildcard `v1/{resource}:setIamPolicy`.
    getIamPolicy is a POST but changes nothing, so it is safe to probe with."""
    candidates = [
        IAP_REGISTRY_RESOURCE,                                       # the known-good one
        f"{IAP_REGISTRY_RESOURCE}/endpoints/EXAMPLE_ENDPOINT_ID",     # per-endpoint shape
        f"projects/{PROJECT_NUMBER}/locations/global/iap_web/agentRegistry",
        # Kept as negative controls: these are the plausible-looking shapes that
        # all fail with "Fail to resolve resource". If the first entry ever stops
        # working, seeing these still fail tells you the API changed rather than
        # the project.
        f"projects/{PROJECT}/locations/{LOCATION}/iap_web/agentRegistry",  # id, not number
        f"projects/{PROJECT_NUMBER}/iap_web/agentRegistry",                # no locations/
        f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/iap_web/agent-registry",  # kebab
    ]
    print("Probing IAP resource paths with :getIamPolicy (read-only)...\n")
    found = []
    for c in candidates:
        r = sess.post(f"https://iap.googleapis.com/v1/{c}:getIamPolicy", json={}, timeout=30)
        marker = "  <-- USABLE" if r.status_code < 400 else ""
        print(f"  [{r.status_code}] {c}{marker}")
        if r.status_code >= 400:
            print(f"        {r.text[:160]}")
        else:
            found.append(c)
    if found:
        print(f"\nUse: {found[0]}")
        return 0
    print("\nNone worked. Read the 404/400 bodies above — they usually name the "
          "expected format. Also check a registered endpoint's `registryResource`.")
    return 1


def grant_egress(sess: AuthorizedSession, engine_id: str, iap_resource: str, dry_run: bool) -> int:
    """Bind roles/iap.egressor to the engine's SPIFFE principal. The member is
    `principal://` + the engine's own effectiveIdentity — NOT a serviceAccount:."""
    r = sess.get(f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}",
                 timeout=30)
    if r.status_code >= 400:
        print(f"!! cannot read engine {engine_id}: HTTP {r.status_code}")
        return 1
    spec = r.json().get("spec", {})
    identity = spec.get("effectiveIdentity")
    if not identity:
        print(f"!! engine {engine_id} has no effectiveIdentity "
              f"(identityType={spec.get('identityType')}). Agent Gateway egress needs "
              f"AGENT_IDENTITY, which is fixed at creation — this engine cannot be used.")
        return 1
    member = f"principal://{identity}"
    print(f"member: {member}")

    cur = sess.post(f"https://iap.googleapis.com/v1/{iap_resource}:getIamPolicy",
                    json={}, timeout=30)
    if cur.status_code >= 400:
        print(f"!! getIamPolicy failed: HTTP {cur.status_code} {cur.text[:300]}")
        print("   Run --probe-iap-resource to find the right path.")
        return 1
    policy = cur.json()
    bindings = policy.setdefault("bindings", [])
    for b in bindings:
        if b.get("role") == "roles/iap.egressor":
            if member in b.setdefault("members", []):
                print("  already bound")
                return 0
            b["members"].append(member)
            break
    else:
        bindings.append({"role": "roles/iap.egressor", "members": [member]})

    if dry_run:
        print("[dry-run] setIamPolicy:")
        print(json.dumps(policy, indent=2))
        return 0
    w = sess.post(f"https://iap.googleapis.com/v1/{iap_resource}:setIamPolicy",
                  json={"policy": policy}, timeout=60)
    if w.status_code >= 400:
        print(f"!! setIamPolicy failed: HTTP {w.status_code} {w.text[:300]}")
        return 1
    print("  granted roles/iap.egressor")
    return 0


def bootstrap_engine(sess: AuthorizedSession, engine_id: str) -> int:
    """Print the gcloud commands that mirror production's IAM onto a new engine.

    A new engine gets a BRAND NEW SPIFFE identity keyed to its own resource path,
    so it inherits none of production's bindings. Forgetting this is the single
    most likely way a fresh engine "mysteriously" 401s/403s — the symptom looks
    exactly like the Agent Identity bug that cost this project a day.

    Deliberately PRINTS rather than executes: writing the project IAM policy is
    the riskiest call in this workstream, and the standing rule here is that
    infra actions get staged as exact commands and run by a human.

    Note roles/aiplatform.agentDefaultAccess arrives free via the project-wide
    principalSet binding (attribute.platformContainer), so it is skipped."""
    prod = sess.get(f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{PROD_ENGINE_ID}",
                    timeout=30)
    new = sess.get(f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}",
                   timeout=30)
    if prod.status_code >= 400 or new.status_code >= 400:
        print(f"!! cannot read engines (prod={prod.status_code}, new={new.status_code})")
        return 1
    new_identity = new.json().get("spec", {}).get("effectiveIdentity")
    if not new_identity:
        print(f"!! engine {engine_id} has no effectiveIdentity — it was not created with "
              f"identity_type=AGENT_IDENTITY, and that is fixed at creation. Recreate it.")
        return 1

    pol = sess.post(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:getIamPolicy",
        json={}, timeout=30).json()
    roles = sorted({
        b["role"] for b in pol.get("bindings", [])
        for m in b.get("members", []) if PROD_ENGINE_ID in m
    })
    inherited = {
        b["role"] for b in pol.get("bindings", [])
        for m in b.get("members", []) if m.startswith("principalSet://")
    }
    todo = [r for r in roles if r not in inherited]

    print(f"production {PROD_ENGINE_ID} holds {len(roles)} roles; "
          f"{len(roles) - len(todo)} arrive free via the project principalSet.\n")
    print(f"member: principal://{new_identity}\n")
    print("Run these to mirror them onto the new engine:\n")
    for r in todo:
        print(f"gcloud projects add-iam-policy-binding {PROJECT} \\\n"
              f"    --member='principal://{new_identity}' \\\n"
              f"    --role='{r}' --condition=None --quiet\n")
    print(f"# {len(todo)} bindings. Then smoke it BEFORE any gateway exists:")
    print(f"REASONING_ENGINE_RESOURCE=projects/{PROJECT_NUMBER}/locations/{LOCATION}/"
          f"reasoningEngines/{engine_id} \\")
    print("  .venv/bin/python -m spike.verify_native_run "
          "f56a9039-877e-4a24-adc6-efafa22d104b govern")
    return 0


def attach(sess: AuthorizedSession, engine_id: str, dry_run: bool) -> int:
    if engine_id == PROD_ENGINE_ID:
        print(f"!! Refusing: {PROD_ENGINE_ID} is the production engine serving the live demo.")
        print("   Attach the gateway to a dedicated engine instead.")
        return 1
    body = {"spec": {"deploymentSpec": {"agentGatewayConfig": {
        "agentToAnywhereConfig": {"agentGateway": GATEWAY_RESOURCE}}}}}
    url = (f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}"
           f"?updateMask=spec.deploymentSpec.agentGatewayConfig")
    if dry_run:
        print(f"[dry-run] PATCH {url}")
        print(json.dumps(body, indent=2))
        return 0
    r = sess.patch(url, json=body, timeout=60)
    if r.status_code >= 400:
        print(f"!! HTTP {r.status_code} {r.text[:400]}")
        return 1
    _wait(sess, AIP, r.json())
    print(f"  attached {engine_id} -> {GATEWAY_ID}")
    print(f"  verify: agentGatewayConfig = {json.dumps(_engine_gateway(sess, engine_id))}")
    return 0


def detach(sess: AuthorizedSession, engine_id: str, dry_run: bool) -> int:
    """Clearing a field by masked PATCH with the field absent is the documented
    pattern, but preview APIs are inconsistent about honouring it. Test this
    EARLY — discovering it does not work during an incident is the bad path.
    Fallback if it no-ops: redeploy the engine from a config without the key."""
    url = (f"{AIP}/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}"
           f"?updateMask=spec.deploymentSpec.agentGatewayConfig")
    if dry_run:
        print(f"[dry-run] PATCH {url} with empty deploymentSpec")
        return 0
    r = sess.patch(url, json={"spec": {"deploymentSpec": {}}}, timeout=60)
    if r.status_code >= 400:
        print(f"!! HTTP {r.status_code} {r.text[:400]}")
        return 1
    _wait(sess, AIP, r.json())
    after = _engine_gateway(sess, engine_id)
    print(f"  agentGatewayConfig now: {json.dumps(after)}")
    if after not in (None, "MISSING"):
        print("  !! detach did NOT clear the field. Redeploy the engine instead.")
        return 1
    return 0


def create_authz(sess: AuthorizedSession, dry_run: bool) -> int:
    """IAP REQUEST_AUTHZ in DRY_RUN: traffic still routes through the gateway and
    every allow/deny decision is audit-logged, but nothing is blocked. Google's
    own docs say to start here. failOpen keeps a gateway outage from becoming an
    agent outage."""
    ext = {
        "service": "iap.googleapis.com",
        "failOpen": True,
        "timeout": "1s",
        "metadata": {"iamEnforcementMode": "DRY_RUN", "iapPolicyVersion": "V1"},
    }
    ok = _post(sess, f"{NS_PARENT}/authzExtensions?authzExtensionId={IAP_EXTENSION_ID}",
               ext, NS, dry_run, IAP_EXTENSION_ID)
    if not ok:
        return 1
    pol = {
        "target": {"resources": [GATEWAY_RESOURCE]},
        "policyProfile": "REQUEST_AUTHZ",
        "action": "CUSTOM",
        "customProvider": {"authzExtension": {"resources": [
            f"projects/{PROJECT}/locations/{LOCATION}/authzExtensions/{IAP_EXTENSION_ID}"]}},
    }
    ok = _post(sess, f"{NSEC_PARENT}/authzPolicies?authzPolicyId={AUTHZ_POLICY_ID}",
               pol, NSEC, dry_run, AUTHZ_POLICY_ID)
    return 0 if ok else 1


def _point_policy_at(sess: AuthorizedSession, ext_id: str, dry_run: bool) -> int:
    """Repoint the existing authz policy at one of the two IAP extensions.
    This is the whole enforcement switch, and its whole rollback: one PATCH,
    seconds, no resource is created or destroyed."""
    url = f"{NSEC_PARENT}/authzPolicies/{AUTHZ_POLICY_ID}?updateMask=customProvider"
    body = {"customProvider": {"authzExtension": {"resources": [
        f"projects/{PROJECT}/locations/{LOCATION}/authzExtensions/{ext_id}"]}}}
    if dry_run:
        print(f"[dry-run] PATCH {url}")
        print(json.dumps(body, indent=2))
        return 0
    r = sess.patch(url, json=body, timeout=60)
    if r.status_code >= 400:
        print(f"!! HTTP {r.status_code} {r.text[:400]}")
        return 1
    _wait(sess, NSEC, r.json())
    got = sess.get(f"{NSEC_PARENT}/authzPolicies/{AUTHZ_POLICY_ID}", timeout=30).json()
    live = got.get("customProvider", {}).get("authzExtension", {}).get("resources", [])
    print(f"  policy now points at: {[r.split('/')[-1] for r in live]}")
    return 0 if any(ext_id == r.split("/")[-1] for r in live) else 1


def enforce_authz(sess: AuthorizedSession, dry_run: bool) -> int:
    """Turn on real enforcement.

    There is NO `ENFORCED` value. Enforcement is the ABSENCE of
    `iamEnforcementMode` — the string "ENFORCED" appears nowhere in Google's
    docs, and an early draft of this script that set it would have been wrong.
    Google's own codelab cuts over by creating a SECOND extension and repointing
    the policy, rather than mutating the dry-run one in place, and that is what
    this does: the dry-run extension survives untouched, so --unenforce is a
    single PATCH away at any time.

    failOpen also flips to False. It is an independent bypass: with failOpen
    True, a 1s extension timeout allows the request regardless of policy, so
    leaving it on would leave a hole even after enforcement is enabled.

    PRECONDITION, and the reason this is a separate subcommand: roles/iap.egressor
    must be granted at IAP_GLOBAL_REGISTRY_RESOURCE, not just the regional one.
    IAP evaluates egress against locations/global; the regional binding alone
    leaves that policy empty, and DRY_RUN hides it by logging granted:true on
    everything. Enforcing against an empty policy denies 100% of egress.

    TESTED 2026-08-31, and it is NOT currently in use. Three enforced runs each
    stalled the 5th of 6 judge calls (42-70s hang, then "Root node judge was
    cancelled") and returned `partial` with 4/6 verdicts. Raising timeout 1s->10s
    changed nothing. Critically, rolling back to DRY_RUN did NOT restore a clean
    pass either (5/6) — so enforcement is not the sole cause and the honest
    reading is a latency ceiling, not an authorization denial:

      - Zero denials across every enforced run. Every gateway_requests row was
        authzPolicyInfo.result=ALLOWED, 100% matched to a registered endpoint.
      - The govern assessment now takes ~275-305s. Gateway-mediated runs get
        cancelled in that band; the same assessment on the ungoverned production
        engine 403 completed at 296.2s with 6/6 verdicts.

    So the gateway-mediated path has a stream ceiling the direct path does not,
    and enforcement adds enough per-connection latency to make it bite sooner.
    Enforcement is a knob to revisit once the ceiling is understood; it is not
    what breaks authorization."""
    pol = sess.get(f"{NSEC_PARENT}/authzPolicies/{AUTHZ_POLICY_ID}", timeout=30)
    if pol.status_code != 200:
        print(f"!! no authz policy {AUTHZ_POLICY_ID}; run --create-authz first")
        return 1
    r = sess.post(f"https://iap.googleapis.com/v1/{IAP_GLOBAL_REGISTRY_RESOURCE}:getIamPolicy",
                  json={}, timeout=30)
    binds = r.json().get("bindings", []) if r.status_code == 200 else []
    if not any(b.get("role") == "roles/iap.egressor" for b in binds):
        print(f"!! REFUSING: no roles/iap.egressor at {IAP_GLOBAL_REGISTRY_RESOURCE}")
        print("   An etag with no bindings means no policy exists. Enforcing now "
              "would deny every egress call. Grant it, wait for propagation, retry.")
        return 1
    print(f"  precondition OK: iap.egressor present at global IAP resource")
    ext = {
        "service": "iap.googleapis.com",
        "failOpen": False,
        "timeout": "1s",
        "metadata": {"iapPolicyVersion": "V1"},   # no iamEnforcementMode == enforcing
    }
    if not _post(sess, f"{NS_PARENT}/authzExtensions?authzExtensionId={IAP_ENFORCED_EXTENSION_ID}",
                 ext, NS, dry_run, IAP_ENFORCED_EXTENSION_ID):
        return 1
    rc = _point_policy_at(sess, IAP_ENFORCED_EXTENSION_ID, dry_run)
    if rc == 0 and not dry_run:
        print("\n  ENFORCING. Rollback at any time:")
        print("    python infra/setup_agent_gateway.py --unenforce")
    return rc


def unenforce_authz(sess: AuthorizedSession, dry_run: bool) -> int:
    """Rollback: repoint the policy at the DRY_RUN extension. Seconds, and it
    destroys nothing — the enforced extension stays for the next attempt."""
    return _point_policy_at(sess, IAP_EXTENSION_ID, dry_run)


def create_model_armor(sess: AuthorizedSession, dry_run: bool) -> int:
    """Network-layer Model Armor, independent of the in-process screening in
    csf_gateway/app/model_armor.py.

    The existing template lives in the `us` MULTI-region; a us-central1 extension
    cannot reference it, so these are new templates. Do NOT repoint
    MODEL_ARMOR_LOCATION / MODEL_ARMOR_TEMPLATE_ID — those are live on csf-gateway
    and csf-worker and must keep pointing at us/my-test-template."""
    filters = {
        "raiSettings": {"raiFilters": [
            {"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "HARASSMENT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "HATE_SPEECH", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "SEXUALLY_EXPLICIT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
        ]},
        "piAndJailbreakFilterSettings": {
            "filterEnforcement": "ENABLED", "confidenceLevel": "MEDIUM_AND_ABOVE"},
        "maliciousUriFilterSettings": {"filterEnforcement": "ENABLED"},
    }
    failures = 0
    for tid in (MA_REQUEST_TEMPLATE_ID, MA_RESPONSE_TEMPLATE_ID):
        if not _post(sess, f"{MA_PARENT}/templates?templateId={tid}",
                     {"filterConfig": filters}, MA, dry_run, tid):
            failures += 1
    if failures:
        return 1

    settings = [{
        "request_template_id":
            f"projects/{PROJECT}/locations/{LOCATION}/templates/{MA_REQUEST_TEMPLATE_ID}",
        "response_template_id":
            f"projects/{PROJECT}/locations/{LOCATION}/templates/{MA_RESPONSE_TEMPLATE_ID}",
    }]
    ext = {
        "service": f"modelarmor.{LOCATION}.rep.googleapis.com",
        "failOpen": True,
        "timeout": "1s",
        "metadata": {"model_armor_settings": json.dumps(settings)},
    }
    ok = _post(sess, f"{NS_PARENT}/authzExtensions?authzExtensionId={MA_EXTENSION_ID}",
               ext, NS, dry_run, MA_EXTENSION_ID)
    if not ok:
        return 1
    print("\nNEXT: grant roles/modelarmor.user to the gateway's service-extensions SA")
    print("      (read it from --status: serviceExtensionsSA=...)")
    return 0


def teardown(sess: AuthorizedSession, dry_run: bool) -> int:
    """Reverse creation order. Engines are NOT deleted here — detach first, then
    delete the engine yourself once you are sure nothing points at it."""
    targets = [
        (f"{NSEC_PARENT}/authzPolicies/{AUTHZ_POLICY_ID}", NSEC, "authzPolicy"),
        (f"{NS_PARENT}/authzExtensions/{MA_EXTENSION_ID}", NS, "modelarmor authzExtension"),
        (f"{NS_PARENT}/authzExtensions/{IAP_EXTENSION_ID}", NS, "iap authzExtension"),
        (f"{NS_PARENT}/agentGateways/{GATEWAY_ID}", NS, "agentGateway"),
        (f"{MA_PARENT}/templates/{MA_REQUEST_TEMPLATE_ID}", MA, "MA request template"),
        (f"{MA_PARENT}/templates/{MA_RESPONSE_TEMPLATE_ID}", MA, "MA response template"),
    ]
    for host, _binding, _tier, _why in _expanded():
        targets.append((f"{AR_PARENT}/services/{_service_id(host)}", AR, f"dest {host}"))

    failures = 0
    for url, root, label in targets:
        if dry_run:
            print(f"[dry-run] DELETE {label}")
            continue
        r = sess.delete(url, timeout=60)
        if r.status_code == 404:
            print(f"  absent:  {label}")
        elif r.status_code >= 400:
            print(f"  FAIL {label}: HTTP {r.status_code} {r.text[:200]}")
            failures += 1
        else:
            print(f"  deleted: {label}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print payloads, change nothing")
    ap.add_argument("--status", action="store_true",
                    help="read-only: gateway, extensions, policy, and the production-engine assertion")
    ap.add_argument("--list", action="store_true", help="show the destination allowlist and its reasoning")
    ap.add_argument("--create-gateway", action="store_true")
    ap.add_argument("--set-registries", action="store_true",
                    help="link the Agent Registry to the gateway (REQUIRED for egress)")
    ap.add_argument("--register", action="store_true", help="register egress destinations")
    ap.add_argument("--probe-only", action="store_true",
                    help="with --register: only the 4-host gRPC/HTTP probe subset")
    ap.add_argument("--probe-iap-resource", action="store_true",
                    help="read-only: find the IAP resource path for the egressor grant")
    ap.add_argument("--grant-egress", metavar="ENGINE_ID")
    ap.add_argument("--iap-resource", default=IAP_REGISTRY_RESOURCE,
                    help="IAP resource for the egressor grant. Default is REGISTRY-LEVEL, "
                         "which covers every registered destination in one binding. Append "
                         "/endpoints/<id> to scope the grant to a single destination "
                         "(that is how you manufacture a would-deny for the audit-log demo).")
    ap.add_argument("--bootstrap-engine", metavar="ENGINE_ID",
                    help="print the gcloud commands mirroring production's IAM onto a new engine")
    ap.add_argument("--attach", metavar="ENGINE_ID")
    ap.add_argument("--detach", metavar="ENGINE_ID")
    ap.add_argument("--create-authz", action="store_true")
    ap.add_argument("--enforce", action="store_true",
                    help="stop dry-running: point the policy at a failOpen=false "
                         "extension with no iamEnforcementMode. Refuses unless "
                         "iap.egressor exists at the GLOBAL IAP resource.")
    ap.add_argument("--unenforce", action="store_true",
                    help="rollback --enforce: repoint at the DRY_RUN extension")
    ap.add_argument("--create-model-armor", action="store_true")
    ap.add_argument("--teardown", action="store_true")
    args = ap.parse_args()

    if args.list:
        return list_destinations()

    sess = _session()
    if args.status:
        return status(sess)
    if args.probe_iap_resource:
        return probe_iap_resource(sess)
    if args.create_gateway:
        return create_gateway(sess, args.dry_run)
    if args.set_registries:
        return set_registries(sess, args.dry_run)
    if args.register:
        return register_destinations(sess, args.dry_run, args.probe_only)
    if args.bootstrap_engine:
        return bootstrap_engine(sess, args.bootstrap_engine)
    if args.grant_egress:
        return grant_egress(sess, args.grant_egress, args.iap_resource, args.dry_run)
    if args.attach:
        return attach(sess, args.attach, args.dry_run)
    if args.detach:
        return detach(sess, args.detach, args.dry_run)
    if args.create_authz:
        return create_authz(sess, args.dry_run)
    if args.enforce:
        return enforce_authz(sess, args.dry_run)
    if args.unenforce:
        return unenforce_authz(sess, args.dry_run)
    if args.create_model_armor:
        return create_model_armor(sess, args.dry_run)
    if args.teardown:
        return teardown(sess, args.dry_run)

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
