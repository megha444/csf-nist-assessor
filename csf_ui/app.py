"""
Streamlit app v2 — multi-session dashboard with a chat-native interview and
tabbed reports. See docs/HANDOFF.md / task_list.md for the v1 -> v2 rationale.

Session/document/chat/qna go over HTTP to the running csf-gateway (those own
real async background work — ingest's fire-and-forget task, Firestore writes —
that has to run inside the gateway's own event loop, not Streamlit's).

As of Aug 23, run-assessment does too — POST /sessions/{sid}/run (Agent
Runtime, see csf_gateway/app/runs.py) starts the coordinator as a real
backgrounded task inside the gateway and returns a run_id immediately; the
Reports view polls GET .../runs/{run_id}/status the same way Docs already
polls per-document ingest status, instead of blocking the whole Streamlit
script for however long the assessment takes. This replaced a real bug: the
previous synchronous call blocked Streamlit's own connection long enough
(minutes, worse now with 6 Functions + Judge) that the browser's live
connection could go stale before the automatic rerun fired, leaving the
spinner stuck even after the backend had actually finished — confirmed live
Aug 21. Report generation still calls csf_specialists directly as a library
function — that's a cheap read once a run is done, no reason for HTTP there.

Nothing about a session lives only in Streamlit state: switching sessions
re-fetches everything (docs, chat history, chat_state.pending/done, run_id)
fresh from Firestore via the gateway, so reopening an old session can't show
stale data left over from a different one.

Usage:
  poetry run streamlit run csf_ui/app.py
"""
from __future__ import annotations

import asyncio
import sys
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
import pandas as pd
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


def _start_run(session_id: str) -> str:
    """POST /sessions/{sid}/run — starts the assessment as a real backgrounded
    task inside the gateway, returns immediately with a run_id to poll."""
    resp = _api("POST", f"/sessions/{session_id}/run")
    return resp["run_id"]


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
    with st.form("new_session_form", clear_on_submit=True, border=False):
        new_org_name = st.text_input(
            "Company name", placeholder="e.g. Acme Corp — leave blank for the demo default",
            label_visibility="collapsed",
        )
        if st.form_submit_button("+ New session", type="primary", width="stretch"):
            body = {"target_org": new_org_name.strip()} if new_org_name.strip() else {}
            data = _api("POST", "/sessions", json=body)
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

    # Cheap pre-check, outside the fragment, purely to decide whether the
    # fragment's own timer should be armed for this render. st.rerun() cannot
    # bootstrap a fragment-scoped rerun loop on a fragment's first/full-script
    # run — Streamlit raises StreamlitAPIException if you try (confirmed live
    # Aug 20) — run_every is the only sanctioned way to auto-poll a fragment.
    # Gating it here means polling actually stops once nothing's in flight,
    # instead of run_every="2s" firing forever for the rest of the session.
    _docs_preview = _api("GET", f"/sessions/{sid}/documents")
    _any_in_flight = any(d["ingest_status"] not in ("ready", "failed") for d in _docs_preview)

    @st.fragment(run_every="2s" if _any_in_flight else None)
    def _render_docs_status(session_id: str) -> None:
        docs = _api("GET", f"/sessions/{session_id}/documents")
        if not docs:
            st.caption("No documents uploaded yet.")
            return

        in_flight = [d for d in docs if d["ingest_status"] not in ("ready", "failed")]
        for d in in_flight:
            status = _api("GET", f"/sessions/{session_id}/documents/{d['doc_id']}/status")
            st.progress(status["progress_pct"] / 100, text=f"{d['filename']} — {status['ingest_status']}")

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

    _render_docs_status(sid)

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
    def _go_to_reports_and_run() -> None:
        # Navigate first, run second: this only flips two session_state flags
        # (fast, no blocking work) so the user actually lands on the Reports
        # page before the slow part starts, instead of watching a spinner on
        # the Chat page and getting teleported to Reports only once it's
        # done. The Reports view (below) checks pending_run_assessment and
        # does the actual _run_assessment_sync call there, with its own
        # spinner, natively on the page the user is now looking at. Same
        # StreamlitAPIException trap as the Docs "Next -> Chat" button applies
        # to active_view — must be set from an on_click callback, not the
        # normal post-click body, since segmented_control(key="active_view")
        # has already rendered this run.
        st.session_state.active_view = "Reports"
        st.session_state.pending_run_assessment = True

    header_col, button_col = st.columns([3, 1])
    with header_col:
        st.caption("Answer as many questions as you'd like — or run the assessment now with what's already covered.")
    with button_col:
        st.button("Run assessment now", width="stretch", on_click=_go_to_reports_and_run)

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
    pending_key = f"pending_run_id_{sid}"

    if st.session_state.pop("pending_run_assessment", False):
        # Set by the Chat view's "Run assessment now" button — navigation
        # already happened (we're on Reports now). Starts the run and begins
        # polling natively on this page, instead of blocking the whole
        # Streamlit script for the run's duration — see module docstring for
        # the real hang this replaced (confirmed live Aug 21).
        st.session_state[pending_key] = _start_run(sid)

    run_id = session.get("run_id")
    pending_run_id = st.session_state.get(pending_key)

    if pending_run_id:
        # Same cheap-pre-check-outside-the-fragment pattern as Docs status
        # (_render_docs_status above) — decides whether run_every should be
        # armed for this render, so polling actually stops once done instead
        # of firing forever.
        _status = _api("GET", f"/sessions/{sid}/runs/{pending_run_id}/status")
        _run_done = _status["status"] == "ready_for_report"

        @st.fragment(run_every=None if _run_done else "3s")
        def _render_run_status() -> None:
            status = _api("GET", f"/sessions/{sid}/runs/{pending_run_id}/status")
            label = {
                "pending": "Starting…",
                "dispatched": "Dispatching specialist agents…",
                "partial": f"Scoring — {status.get('completed_agents', 0)}/{status.get('expected_agents', '?')} Functions complete…",
            }.get(status["status"], status["status"])
            if status["status"] == "ready_for_report":
                st.session_state.pop(pending_key, None)
                st.rerun()
            else:
                st.info(f"Running assessment — {label}")

        _render_run_status()

    elif not run_id:
        st.info("No assessment has been run for this session yet.")
        st.caption(f"Scores every Function with a live agent: {', '.join(FUNCTION_NAMES[f] for f in AGENTS)}.")
        if st.button("Run assessment", type="primary"):
            st.session_state[pending_key] = _start_run(sid)
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
                n_insufficient = f["insufficient_evidence_count"]
                help_text = (
                    f"{n_insufficient} Categor{'y' if n_insufficient == 1 else 'ies'} below confidence threshold"
                    if n_insufficient else None
                )
                # Memory Bank: real change vs. the org's most recent prior assessment,
                # using Streamlit's own delta arrow/color rather than reinventing one.
                # None (not 0) suppresses the indicator entirely -- shown only when
                # there's an actual prior run to compare against.
                tier_delta = f.get("tier_delta")
                col.metric(f["name"], tier_label, delta=tier_delta if tier_delta else None, help=help_text)
                captions = []
                if f["avg_cmmi"] is not None:
                    captions.append(f"avg CMMI {f['avg_cmmi']:.2f}")
                if tier_delta == 0:
                    captions.append("unchanged since last assessment")
                if captions:
                    col.caption(" · ".join(captions))
            st.plotly_chart(_tier_radar_figure(report), width="stretch", config={"displayModeBar": False})

        for tab, f in zip(tabs[1:], ctx["functions"]):
            with tab:
                cat_fig = _category_radar_figure(report, f["function"])
                if cat_fig is not None:
                    st.plotly_chart(cat_fig, width="stretch", config={"displayModeBar": False})
                for c in f["categories"]:
                    header = f"{c['category_id']} — {c['name']}  ·  CMMI {c['cmmi_level']}"
                    if c.get("cmmi_delta"):
                        arrow = "↑" if c["cmmi_delta"] > 0 else "↓"
                        header += f"  ({arrow} was {c['prior_cmmi']})"
                    header += f"  ·  conf {c['confidence'] * 100:.0f}%"
                    if c["low_confidence"]:
                        header += "  ·  ⚠ insufficient evidence"
                    with st.expander(header):
                        if c["low_confidence"]:
                            st.warning("Confidence below threshold — treat this Category's score as provisional.")
                        if c["no_doc_evidence"]:
                            st.warning("No document evidence for this Category.")
                        st.write(c["reasoning"])
                        if c.get("prior_top_gap"):
                            st.caption(f"Previously flagged: {c['prior_top_gap']}")
                        if c["subcategory_scores"]:
                            # st.dataframe is a virtualized grid that truncates overflowing
                            # cell text with no wrap option — st.table renders a plain static
                            # HTML table instead, which wraps naturally like any other table.
                            # Subcategory becomes the index so no extra numeric index column
                            # shows up next to it.
                            sub_df = pd.DataFrame(
                                [
                                    {
                                        "CMMI": s["cmmi_level"],
                                        "Evidence": s["evidence_status"],
                                        "Confidence": f"{s['confidence'] * 100:.0f}%" + (" ⚠" if s["low_confidence"] else ""),
                                        "Observations": s["observations"],
                                        "Gap": s["gap"],
                                        "Recommendation": s["recommendation"],
                                    }
                                    for s in c["subcategory_scores"]
                                ],
                                index=[
                                    f"{s['subcategory_id']} — {s['name']}" if s.get("name") else s["subcategory_id"]
                                    for s in c["subcategory_scores"]
                                ],
                            )
                            sub_df.index.name = "Subcategory"
                            st.table(sub_df)
                        if c["evidence_citations"]:
                            st.caption("Evidence citations")
                            for e in c["evidence_citations"]:
                                pages = f"p.{e['page_start']}" + (f"–{e['page_end']}" if e["page_end"] != e["page_start"] else "")
                                st.markdown(f"- **{e['doc_title']}** {e.get('section', '')} ({pages}): “{e['snippet']}”")
                        if c["interview_evidence"]:
                            st.caption(f"Interview evidence: {', '.join(c['interview_evidence'])}")
