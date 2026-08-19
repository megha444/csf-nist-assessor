"""
Streamlit app v2 — multi-session dashboard with a chat-native interview and
tabbed reports. See docs/HANDOFF.md / task_list.md for the v1 -> v2 rationale.

Session/document/chat/qna go over HTTP to the running csf-gateway (those own
real async background work — ingest's fire-and-forget task, Firestore writes —
that has to run inside the gateway's own event loop, not Streamlit's).
Run-assessment and report generation call csf_coordinator/csf_specialists
directly as library functions — no server-side state of their own, so HTTP
would add nothing.

Nothing about a session lives only in Streamlit state: switching sessions
re-fetches everything (docs, chat history, chat_state.pending/done, run_id)
fresh from Firestore via the gateway, so reopening an old session can't show
stale data left over from a different one.

`run_assessment()` dispatches over real Pub/Sub and blocks until every
Function's worker publishes a result (up to 15 min, see
csf_coordinator/steps.py's CollectResultsStep) — nothing consumes those
dispatches unless a `csf_specialists/worker.py --function <fn>` process is
running. The "Run assessment" button spawns one one-shot worker subprocess
per Function right before calling it, so the button works standalone.

Usage:
  poetry run streamlit run csf_ui/app.py
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
import streamlit as st

from csf_gateway.app.csf_catalog import FUNCTION_NAMES
from csf_gateway.app.doctype_taxonomy import DocType
from csf_specialists.agents import AGENTS
from csf_specialists.scripts.export_excel import build_rows, fetch_scores, write_workbook
from csf_specialists.scripts.export_html import (
    _build_context,
    _category_radar_figure,
    _tier_radar_figure,
    render_html,
)
from csf_specialists.scripts.export_json import build_report

GATEWAY_URL = "http://localhost:8090"
WORKER_SCRIPT = REPO_ROOT / "csf_specialists" / "worker.py"
WORKER_LOG_DIR = Path(tempfile.gettempdir()) / "csf-ui-workers"

st.set_page_config(page_title="CSF Assessor Fleet", layout="wide")


# ---------------------------------------------------------------------------
# HTTP + background-work helpers
# ---------------------------------------------------------------------------


def _api(method: str, path: str, **kwargs) -> dict:
    """Call the gateway; surface connection/HTTP errors as a clean st.error + st.stop()
    instead of a raw traceback — this is a real system boundary (gateway may not be running)."""
    try:
        resp = httpx.request(method, f"{GATEWAY_URL}{path}", timeout=60.0, **kwargs)
    except httpx.ConnectError:
        st.error(
            f"Can't reach the gateway at {GATEWAY_URL}. Start it with:\n\n"
            "`poetry run uvicorn csf_gateway.app.main:app --port 8090`"
        )
        st.stop()
    if resp.status_code >= 400:
        st.error(f"{method} {path} → {resp.status_code}: {resp.text}")
        st.stop()
    return resp.json()


def _run_assessment_sync(session_id: str) -> None:
    """Spawn one worker subprocess per live Function agent, then run the real
    coordinator (Pub/Sub dispatch → collect → aggregate). Blocking — the caller
    wraps this in st.spinner. AggregateStep already writes run_id back onto the
    session doc, so the caller just needs to re-fetch the session afterward."""
    from csf_coordinator.coordinator import run_assessment

    functions = list(AGENTS.keys())
    WORKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

    procs = []
    for fn in functions:
        log_path = WORKER_LOG_DIR / f"{session_id[:8]}_{fn}.log"
        with open(log_path, "w") as lf:
            proc = subprocess.Popen(
                [sys.executable, str(WORKER_SCRIPT), "--function", fn, "--timeout", "60"],
                stdout=lf, stderr=subprocess.STDOUT, cwd=str(REPO_ROOT),
            )
        procs.append((fn, log_path, proc))

    asyncio.run(run_assessment(session_id, functions=functions))

    for fn, log_path, proc in procs:
        code = proc.wait(timeout=10)
        if code != 0:
            st.warning(f"worker/{fn} exited with code {code} — see {log_path}")


# ---------------------------------------------------------------------------
# Session state — deliberately thin. The active session_id and which view is
# showing are the only things that live only in Streamlit; everything about
# the session itself is re-fetched from Firestore (via the gateway) below.
# ---------------------------------------------------------------------------

st.session_state.setdefault("active_session_id", None)
st.session_state.setdefault("active_view", "Docs")


# ---------------------------------------------------------------------------
# Sidebar — session list, always visible
# ---------------------------------------------------------------------------


def _switch_session(new_sid: str | None) -> None:
    st.session_state.active_session_id = new_sid
    st.session_state.active_view = "Docs"


with st.sidebar:
    st.header("Sessions")
    if st.button("+ New session", type="primary", width="stretch"):
        data = _api("POST", "/sessions", json={})
        _switch_session(data["session_id"])
        st.rerun()

    st.divider()
    for s in _api("GET", "/sessions"):
        is_active = s["session_id"] == st.session_state.active_session_id
        badge = " 📊" if s.get("run_id") else ""
        created = s["created_at"][:16].replace("T", " ")
        label = f"{s['target_org']}{badge}\n{created}"
        if st.button(label, key=f"sess_{s['session_id']}", type="primary" if is_active else "secondary", width="stretch"):
            _switch_session(s["session_id"])
            st.rerun()

st.title("CSF Assessor Fleet")

if not st.session_state.active_session_id:
    st.info("Create a new session from the sidebar, or select an existing one, to get started.")
    st.stop()

sid = st.session_state.active_session_id
session = _api("GET", f"/sessions/{sid}")
st.caption(f"{session['target_org']}  ·  {sid}")

view = st.segmented_control("View", ["Docs", "Chat", "Reports"], key="active_view")

# ---------------------------------------------------------------------------
# Docs view
# ---------------------------------------------------------------------------

if view == "Docs":
    doc_type_values = [t.value for t in DocType]
    other_index = doc_type_values.index("Other")
    uploaded_files = st.file_uploader(
        "PDF / DOCX / XLSX", accept_multiple_files=True, type=["pdf", "docx", "doc", "xlsx"],
        key=f"docs_uploader_{sid}",
    )
    if uploaded_files:
        st.caption("Document type per file:")
        selected_doc_types = {}
        for f in uploaded_files:
            selected_doc_types[f.file_id] = st.selectbox(
                f.name, doc_type_values, index=other_index, key=f"doctype_{f.file_id}",
            )
        if st.button("Upload"):
            files_payload = [("files", (f.name, f.getvalue())) for f in uploaded_files]
            data_payload = {"doc_types": [selected_doc_types[f.file_id] for f in uploaded_files]}
            resp = _api("POST", f"/sessions/{sid}/documents", files=files_payload, data=data_payload)
            st.success(f"Uploaded {len(resp['files'])} file(s) — status: {resp['status']}")

    docs = _api("GET", f"/sessions/{sid}/documents")
    if docs:
        st.dataframe(
            [
                {
                    "filename": d["filename"],
                    "doc_type": d["doc_type"],
                    "status": d["ingest_status"],
                    "chunks": d["chunk_count"],
                }
                for d in docs
            ],
            hide_index=True,
            width="stretch",
        )
        st.button("Refresh status")
    else:
        st.caption("No documents uploaded yet.")

    st.divider()
    # Mutating a widget's session_state key after that widget has already been
    # instantiated in this run raises a StreamlitAPIException (segmented_control
    # above already ran) — an on_click callback runs before the script
    # re-executes, so it's the correct way to change the active view from a
    # button that renders below the switcher.
    st.button("Next → Chat", type="primary", on_click=lambda: st.session_state.update(active_view="Chat"))

# ---------------------------------------------------------------------------
# Chat view — fully server-state-driven: chat_state.pending/done and the
# answer history are re-read from Firestore every rerun, nothing cached only
# in Streamlit. The AI always picks which Function a question is about
# (POST /chat/next with no `function` param) — never the user.
# ---------------------------------------------------------------------------

elif view == "Chat":
    with st.expander("📎 Upload a completed Q&A questionnaire (optional)"):
        qna_file = st.file_uploader(
            "A filled-out questionnaire (PDF/DOCX/XLSX) — Q&A pairs are extracted and attached as evidence.",
            type=["pdf", "docx", "doc", "xlsx"], key=f"qna_uploader_{sid}",
        )
        if qna_file and st.button("Extract & attach"):
            with st.spinner("Reading document and extracting Q&A pairs..."):
                resp = _api(
                    "POST", f"/sessions/{sid}/qna",
                    files={"file": (qna_file.name, qna_file.getvalue())},
                )
            if resp["records_extracted"] == 0:
                st.warning("No Q&A pairs identified in this document.")
            else:
                by_fn = ", ".join(f"{FUNCTION_NAMES.get(fn, fn)}: {n}" for fn, n in resp["by_function"].items())
                st.success(f"Extracted {resp['records_extracted']} Q&A pair(s) — {by_fn}")
            st.rerun()

    history = _api("GET", f"/sessions/{sid}/chat/history")
    for turn in history:
        with st.chat_message("assistant"):
            st.write(turn["question"])
            st.caption(turn.get("category_hint", ""))
        with st.chat_message("user"):
            st.write(turn["answer"])

    chat_state = session["chat_state"]
    pending = chat_state.get("pending")
    done = chat_state.get("done", False)

    if pending:
        with st.chat_message("assistant"):
            st.write(pending["question"])
            st.caption(pending.get("category_hint", ""))
        answer = st.chat_input("Your answer...")
        if answer:
            _api(
                "POST", f"/sessions/{sid}/chat/answer",
                json={"question_id": pending["question_id"], "answer": answer},
            )
            with st.spinner("Thinking of the next question..."):
                _api("POST", f"/sessions/{sid}/chat/next")
            st.rerun()
    elif done:
        st.success("Interview complete for this session.")
    else:
        with st.spinner("Thinking of a question..."):
            _api("POST", f"/sessions/{sid}/chat/next")
        st.rerun()

# ---------------------------------------------------------------------------
# Reports view — Overview tab (both radars + Tier cards) + one tab per scored
# Function, built natively from the same data export_html.py's static report
# uses (build_report/_build_context/_tier_radar_figure/_category_radar_figure
# are pure-data/pure-plotly, no Jinja coupling — reused as-is).
# ---------------------------------------------------------------------------

elif view == "Reports":
    run_id = session.get("run_id")
    if not run_id:
        st.info("No assessment has been run for this session yet.")
        st.caption(f"Scores every Function with a live agent: {', '.join(FUNCTION_NAMES[f] for f in AGENTS)}.")
        if st.button("Run assessment", type="primary"):
            with st.spinner("Dispatching specialist agents — this can take several minutes..."):
                _run_assessment_sync(sid)
            st.rerun()
    else:
        report = asyncio.run(build_report(sid, run_id))
        ctx = _build_context(report, session["target_org"])

        col1, col2 = st.columns(2)
        with col1:
            html = render_html(report, session["target_org"])
            st.download_button(
                "⬇ Download report (.html)", data=html,
                file_name=f"csf_report_{sid[:8]}.html", mime="text/html",
            )
        with col2:
            scores = asyncio.run(fetch_scores(sid, run_id))
            buf = BytesIO()
            write_workbook(build_rows(scores), buf)
            st.download_button(
                "⬇ Download findings (.xlsx)", data=buf.getvalue(),
                file_name=f"csf_findings_{sid[:8]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        tabs = st.tabs(["Overview"] + [f["name"] for f in ctx["functions"]])

        with tabs[0]:
            cols = st.columns(len(ctx["functions"]))
            for col, f in zip(cols, ctx["functions"]):
                tier_label = f"Tier {f['tier']}" if f["tier"] else "—"
                delta = f"avg CMMI {f['avg_cmmi']:.2f}" if f["avg_cmmi"] is not None else None
                col.metric(f["name"], tier_label, delta)
            st.plotly_chart(_tier_radar_figure(report), width="stretch", config={"displayModeBar": False})
            st.plotly_chart(_category_radar_figure(report), width="stretch", config={"displayModeBar": False})

        for tab, f in zip(tabs[1:], ctx["functions"]):
            with tab:
                for c in f["categories"]:
                    header = f"{c['category_id']} — {c['name']}  ·  CMMI {c['cmmi_level']}  ·  conf {c['confidence'] * 100:.0f}%"
                    with st.expander(header):
                        if c["no_doc_evidence"]:
                            st.warning("No document evidence for this Category.")
                        st.write(c["reasoning"])
                        if c["subcategory_scores"]:
                            st.dataframe(
                                [
                                    {
                                        "Subcategory": f"{s['subcategory_id']} — {s['name']}" if s.get("name") else s["subcategory_id"],
                                        "CMMI": s["cmmi_level"],
                                        "Evidence": s["evidence_status"],
                                        "Observations": s["observations"],
                                        "Gap": s["gap"],
                                        "Recommendation": s["recommendation"],
                                    }
                                    for s in c["subcategory_scores"]
                                ],
                                hide_index=True, width="stretch",
                            )
                        if c["evidence_citations"]:
                            st.caption("Evidence citations")
                            for e in c["evidence_citations"]:
                                pages = f"p.{e['page_start']}" + (f"–{e['page_end']}" if e["page_end"] != e["page_start"] else "")
                                st.markdown(f"- **{e['doc_title']}** {e.get('section', '')} ({pages}): “{e['snippet']}”")
                        if c["interview_evidence"]:
                            st.caption(f"Interview evidence: {', '.join(c['interview_evidence'])}")
