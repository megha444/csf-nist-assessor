# CSF Assessor Fleet — Architecture

**Companion doc:** `csf_assessor_hackathon_plan.md` (schedule) + `~/.claude/plans/now-lets-plan-the-mossy-glacier.md` (system plan) + `docs/lld.md` (low-level design).

All Mermaid diagrams below render natively on GitHub.

---

## 1. System context (who talks to what)

```mermaid
flowchart LR
    User([Demo User<br/>Megha or Sakina])

    subgraph "GCP: csf-assessor-hackathon"
        GW[csf-gateway<br/>Streamlit + FastAPI]
        CO[csf-coordinator<br/>Coordinator + Interview Director]
        SP[csf-specialists<br/>6 Function Agents]

        VX[(Vertex AI<br/>Gemini 2.5 Flash + Pro<br/>text-embedding-004)]
        VS[(Vertex AI<br/>Vector Search<br/>csf-assessor-index)]
        FS[(Firestore<br/>sessions, runs, scores)]
        GCS[(Cloud Storage<br/>raw docs + artifacts)]
        PS>Pub/Sub<br/>csf-dispatch-* + csf-results]
        TR[(Cloud Trace<br/>OpenTelemetry spans)]
        SM[(Secret Manager)]
        AR[(Artifact Registry<br/>csf-images)]
    end

    User -->|HTTPS| GW
    GW -->|internal HTTPS| CO
    CO -->|publish| PS
    PS -->|push| SP
    SP -->|publish results| PS
    PS -->|push results| CO

    GW --> GCS
    GW --> FS
    GW --> VX
    GW --> VS
    CO --> FS
    CO --> VX
    SP --> FS
    SP --> VS
    SP --> VX

    GW -.->|traces| TR
    CO -.->|traces| TR
    SP -.->|traces| TR

    GW -.-> SM
    AR -.->|images| GW
    AR -.->|images| CO
    AR -.->|images| SP
```

---

## 2. Deployment topology (three Cloud Run services + per-agent identity)

```mermaid
flowchart TB
    subgraph "Cloud Run: csf-gateway"
        direction TB
        ST[Streamlit UI<br/>upload, chat, report]
        API[FastAPI routes<br/>/sessions /documents /preseed<br/>/chat /run /report]
        IN[Ingest worker<br/>Gemini multimodal<br/>chunker, embedder]
        DT[Doc-type taxonomy<br/>hardcoded ~15]
        SAgw[IAM SA:<br/>csf-gateway@…]
        ST --- API --- IN --- DT
        API --- SAgw
    end

    subgraph "Cloud Run: csf-coordinator"
        direction TB
        COagent[Coordinator agent<br/>ADK]
        IDagent[Interview Director agent<br/>ADK]
        AGG[Aggregation<br/>CMMI → Tier]
        JUD[LLM-as-Judge<br/>Gemini Pro]
        SAco[IAM SA:<br/>csf-coordinator@…]
        COagent --- IDagent --- AGG --- JUD --- SAco
    end

    subgraph "Cloud Run: csf-specialists"
        direction TB
        GVagent[Govern agent]
        IDagent2[Identify agent]
        PRagent[Protect agent]
        DTagent[Detect agent]
        RSagent[Respond agent]
        RCagent[Recover agent]
        BASE[agent_base.py<br/>retrieval + scoring loop]

        SAgv[SA:<br/>csf-agent-govern]
        SAid[SA:<br/>csf-agent-identify]
        SApr[SA:<br/>csf-agent-protect]
        SAdt[SA:<br/>csf-agent-detect]
        SArs[SA:<br/>csf-agent-respond]
        SArc[SA:<br/>csf-agent-recover]

        GVagent -.impersonates.-> SAgv
        IDagent2 -.impersonates.-> SAid
        PRagent -.impersonates.-> SApr
        DTagent -.impersonates.-> SAdt
        RSagent -.impersonates.-> SArs
        RCagent -.impersonates.-> SArc

        GVagent --- BASE
        IDagent2 --- BASE
        PRagent --- BASE
        DTagent --- BASE
        RSagent --- BASE
        RCagent --- BASE
    end
```

**Ingress rules:**
- `csf-gateway` — public (session URL is the boundary)
- `csf-coordinator` — internal only, invoked from gateway
- `csf-specialists` — internal only, Pub/Sub-triggered

**Per-agent identity:** the specialists container has permission to impersonate 6 dedicated service accounts. Every Firestore read and Vertex AI call an agent makes is authenticated as its own SA, and Cloud Trace records which identity ran each span. Preserves the "one IAM identity per agent" Fortified track claim without paying 8× cold starts.

---

## 3. User journey (happy path)

```mermaid
sequenceDiagram
    autonumber
    actor U as Demo User
    participant ST as Streamlit
    participant API as FastAPI (gateway)
    participant IN as Ingest worker
    participant GEM as Gemini Flash
    participant VS as Vector Search
    participant FS as Firestore
    participant CO as Coordinator
    participant ID as Interview Director
    participant PS as Pub/Sub
    participant SP as Specialists (6)
    participant JU as Judge (Pro)

    U->>ST: click "New assessment"
    ST->>API: POST /sessions
    API->>FS: create sessions/{sid}
    API-->>ST: {session_id}

    U->>ST: upload 5-7 PDFs + preseed.json
    ST->>API: POST /documents (multipart)
    API-->>ST: {doc_ids, status:processing}
    par background per doc
        IN->>GEM: convert PDF → structured MD
        IN->>IN: section-aware chunk
        IN->>GEM: embed chunks (text-embedding-004)
        IN->>VS: index datapoints (session_id filter)
        IN->>FS: write chunks + doc metadata
    end
    ST->>API: poll GET /documents/{id}/status
    API-->>ST: {status: ready}

    ST->>API: POST /preseed (northwind_preseed.json)
    API->>FS: write 50 answers, provenance=pre_seeded
    API-->>ST: {loaded_count: 50}

    loop 4-5 turns
        U->>ST: begin chat
        ST->>API: POST /chat/next
        API->>ID: pick next question
        ID->>FS: read coverage map + prev answers
        ID-->>API: {question, category_hint}
        API-->>ST: show question
        U->>ST: type answer
        ST->>API: POST /chat/answer
        API->>FS: write answer, provenance=live_chat
    end

    U->>ST: click "Run assessment"
    ST->>API: POST /run
    API->>CO: dispatch
    CO->>FS: snapshot to runs/{rid}
    CO->>PS: publish 6 dispatch messages

    par 6 agents in parallel
        PS->>SP: dispatch Govern
        SP->>VS: retrieve top-5 per category
        SP->>FS: read snapshot answers
        SP->>GEM: score CMMI per Category
        SP->>FS: write scores/{cat_id}
        SP->>PS: publish complete
    and
        PS->>SP: dispatch Identify
        Note over SP: same loop
    and
        PS->>SP: dispatch Protect
        Note over SP: same loop
    and
        PS->>SP: dispatch Detect
        Note over SP: same loop
    and
        PS->>SP: dispatch Respond
        Note over SP: same loop
    and
        PS->>SP: dispatch Recover
        Note over SP: same loop
    end

    PS-->>CO: 6 completion messages
    CO->>FS: aggregate CMMI → Tier per Function
    par per Category
        CO->>JU: judge defensibility
        JU->>FS: write judge flag
    end
    CO->>FS: runs/{rid}.status = ready_for_report

    ST->>API: GET /report/{rid}
    API->>FS: read tiers + scores + judge
    API-->>ST: render HTML (radar, table, roadmap)
    U->>ST: view report / download HTML
```

---

## 4. Data flow (from a policy PDF to a CMMI score citation)

```mermaid
flowchart LR
    PDF[Access Control<br/>Policy.pdf]
    MD[Structured<br/>Markdown]
    CH[Chunks<br/>500-1200 tok<br/>+ section title]
    EM[Vector<br/>embeddings]
    IDX[(Vector Search<br/>csf-assessor-index<br/>metadata: session_id)]
    Q[Query: PR.AA-05<br/>MFA privileged accts]
    HITS[Top-5<br/>evidence chunks]
    RUB[Rubric:<br/>PR.AA CMMI 1-5]
    QA[Interview Q&A<br/>function=protect]
    LLM[Gemini Flash<br/>scoring call]
    SC[Score:<br/>cmmi_level=2<br/>confidence=0.82<br/>evidence_citation<br/>reasoning]
    RPT[Report row:<br/>PR.AA · CMMI 2 · cite]

    PDF -->|Gemini multimodal| MD
    MD -->|section-aware chunker| CH
    CH -->|text-embedding-004| EM
    EM --> IDX

    Q --> IDX
    IDX --> HITS
    HITS --> LLM
    RUB --> LLM
    QA --> LLM
    LLM --> SC
    SC --> RPT
```

---

## 5. Fortified track components (where each lives)

```mermaid
flowchart LR
    subgraph "Ingest / gateway"
        F1[Agent Gateway<br/>FastAPI ingress]
    end

    subgraph "Coordinator"
        F2[Memory Bank<br/>runs/{rid} snapshot]
    end

    subgraph "Specialists"
        F3[Agent Identity<br/>per-agent SA impersonation]
        F4[Model Armor / DLP<br/>PII scrub before LLM]
    end

    subgraph "Cross-cutting"
        F5[Agent Registry<br/>Firestore on startup]
        F6[Agent Observability<br/>OTel → Cloud Trace]
    end
```

---

## 6. Environments + regions

| Item | Value |
|---|---|
| GCP project | `csf-assessor-hackathon` |
| Region | `us-central1` |
| Firestore mode | Native |
| Storage buckets | `csf-assessor-hackathon-raw-docs` (permanent), `csf-assessor-hackathon-artifacts` (30-day lifecycle) |
| Pub/Sub topics | `csf-dispatch-{govern,identify,protect,detect,respond,recover}` + `csf-results` |
| Artifact Registry | `csf-images` |
| Container image tags | `gcr.io/csf-assessor-hackathon/csf-images/{gateway,coordinator,specialists}:<git-sha>` |
| Traces | Cloud Trace (via `--trace_to_cloud` on `adk deploy cloud_run`) |
| Cost budget | $30 → $60 → $100 → $140 billing alerts already set |
