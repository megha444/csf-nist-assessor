"""
Report generator v2 — HTML output for one run: exec-style header, Plotly
radars, and full per-Category detail (Subcategory table, evidence citations,
interview evidence). Renders `csf_specialists/templates/report.html.j2` via
Jinja2.

Two radar SCOPES, matching the plan's two-layer scoring model (`docs/
csf_assessor_hackathon_plan.md` §2/§3/§10 — "radar chart (Tier) + heatmap
(CMMI)"): one Tier radar, board-level (one spoke per Function, r = Tier 1-4),
shown once near the top; and one Category radar PER FUNCTION, practitioner
drill-down (one spoke per that Function's own Categories, r = CMMI 1-5), shown
inside that Function's own section. Originally the Category radar was a
single chart overlaying every Function's Categories together — redesigned Aug
20 (found via live testing) since that read as one confusing merged shape
instead of a clean per-Function drill-down; `_category_radar_figure` is now
scoped to one Function per call, matching how the Streamlit Reports view
already splits Overview vs. per-Function tabs.

Reuses `export_json.build_report` for the Firestore-sourced structure v1
already produces — v2 is a rendering layer on top, not a second query path.

Usage:
  poetry run python csf_specialists/scripts/export_html.py --session <sid> --run <rid>
  poetry run python csf_specialists/scripts/export_html.py --session <sid> --run <rid> --out report.html
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape

from csf_gateway.app.csf_catalog import FUNCTION_NAMES, categories_for_function
from csf_gateway.app.sessions import get_session
from csf_specialists.aggregate import CONFIDENCE_THRESHOLD
from csf_specialists.loaders import load_implementation_examples
from csf_specialists.scripts.export_json import build_report

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

# Same 6 hues across the radar legend and the per-Function section headers,
# so a reader can visually match a radar trace to its detail section below.
_FUNCTION_COLORS: dict[str, str] = {
    "govern":   "#6366f1",
    "identify": "#0891b2",
    "protect":  "#059669",
    "detect":   "#d97706",
    "respond":  "#dc2626",
    "recover":  "#7c3aed",
}

# CMMI level (1-5) is a different scale from Tier (1-4) — its own red->green ramp.
_CMMI_COLORS: dict[int, str] = {
    1: "#dc2626",
    2: "#ea580c",
    3: "#ca8a04",
    4: "#65a30d",
    5: "#059669",
}


def _tier_radar_figure(report: dict) -> go.Figure:
    """Executive view: one spoke per scored Function, r = Tier (1-4). Blank spokes
    (r=0) mark Functions with Category scores but no aggregated Tier yet."""
    functions = [fn for fn in FUNCTION_NAMES if fn in report["functions"]]
    labels = [FUNCTION_NAMES[fn] for fn in functions]
    tiers = [(report["functions"][fn]["tier"] or {}).get("tier") or 0 for fn in functions]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=tiers + tiers[:1], theta=labels + labels[:1],
        fill="toself", line=dict(color="#1e2530"), name="Tier",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 4], dtick=1)),
        showlegend=False,
        margin=dict(l=40, r=40, t=30, b=30),
        height=380,
        autosize=True,
    )
    return fig


def _category_radar_figure(report: dict, function: str) -> go.Figure | None:
    """Practitioner view for ONE Function: one spoke per its scored Categories,
    r = CMMI level (1-5). Returns None if that Function has no scored
    Categories in this report — caller should skip rendering entirely rather
    than show an empty chart.

    A single scored Category can't form a polygon (theta would repeat the
    same angle twice, closing a zero-area loop that Plotly renders as an
    invisible/empty-looking circle — the exact bug reported live Aug 19).
    Rendered as a single marker instead in that case; 2+ Categories still use
    the normal filled polygon."""
    data = report["functions"].get(function)
    if not data:
        return None
    cat_by_id = {c["category_id"]: c for c in data["categories"]}
    ordered_ids = [c.code for c in categories_for_function(function) if c.code in cat_by_id]
    if not ordered_ids:
        return None

    color = _FUNCTION_COLORS.get(function, "#64748b")
    fig = go.Figure()
    if len(ordered_ids) == 1:
        fig.add_trace(go.Scatterpolar(
            r=[cat_by_id[ordered_ids[0]]["cmmi_level"]], theta=ordered_ids,
            mode="markers", marker=dict(size=14, color=color), name=FUNCTION_NAMES.get(function, function),
        ))
    else:
        theta = ordered_ids + ordered_ids[:1]  # close the loop
        r = [cat_by_id[cid]["cmmi_level"] for cid in ordered_ids]
        r = r + r[:1]
        fig.add_trace(go.Scatterpolar(
            r=r, theta=theta, name=FUNCTION_NAMES.get(function, function),
            fill="toself", line=dict(color=color),
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 5], dtick=1)),
        showlegend=False,
        margin=dict(l=40, r=40, t=30, b=30),
        height=380,
        autosize=True,
    )
    return fig


def _build_context(report: dict, target_org: str) -> dict:
    functions_ctx = []
    for function in FUNCTION_NAMES:  # canonical Govern->Recover order
        data = report["functions"].get(function)
        if not data:
            continue
        examples = load_implementation_examples(function)
        cat_by_id = {c["category_id"]: c for c in data["categories"]}

        # Memory Bank: prior assessment of this same org, if one exists —
        # None on a first-ever assessment. Deltas computed once here so
        # neither the HTML template nor Streamlit has to re-derive them.
        prior = data.get("prior_assessment")
        prior_categories = (prior or {}).get("categories", {})

        categories_ctx = []
        for cat in categories_for_function(function):
            c = cat_by_id.get(cat.code)
            if not c:
                continue
            subs = []
            for ss in sorted(c["subcategory_scores"], key=lambda s: s["subcategory_id"]):
                meta = examples.get(ss["subcategory_id"])
                subs.append({
                    **ss,
                    "name": meta.name if meta else "",
                    "low_confidence": ss["confidence"] < CONFIDENCE_THRESHOLD,
                })
            prior_cat = prior_categories.get(cat.code)
            categories_ctx.append({
                **c,
                "name": cat.name,
                "subcategory_scores": subs,
                "low_confidence": c["confidence"] < CONFIDENCE_THRESHOLD,
                "prior_cmmi": prior_cat["cmmi_level"] if prior_cat else None,
                "cmmi_delta": (c["cmmi_level"] - prior_cat["cmmi_level"]) if prior_cat else None,
                "prior_top_gap": prior_cat["top_gap"] if prior_cat else None,
            })

        tier_data = data["tier"] or {}
        current_tier = tier_data.get("tier")
        prior_tier = prior.get("tier") if prior else None
        functions_ctx.append({
            "function": function,
            "name": FUNCTION_NAMES[function],
            "color": _FUNCTION_COLORS.get(function, "#64748b"),
            "tier": current_tier,
            "avg_cmmi": tier_data.get("avg_cmmi"),
            "insufficient_evidence_count": tier_data.get("insufficient_evidence_count") or 0,
            "categories": categories_ctx,
            "prior_tier": prior_tier,
            "tier_delta": (current_tier - prior_tier) if (prior_tier is not None and current_tier is not None) else None,
        })

    return {
        "target_org": target_org,
        "session_id": report["session_id"],
        "run_id": report["run_id"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "functions": functions_ctx,
        "cmmi_colors": _CMMI_COLORS,
        "confidence_threshold_pct": round(CONFIDENCE_THRESHOLD * 100),
    }


def render_html(report: dict, target_org: str) -> str:
    # responsive=True is what actually makes an embedded Plotly div respect its
    # container width — without it, each chart renders at Plotly's own fixed
    # default (~700px) regardless of the .radar-block flex column it sits in,
    # which is what caused the layout to bleed into the sibling column (bug
    # reported live Aug 19).
    _PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

    tier_fig = _tier_radar_figure(report)
    # Load plotly.js once (first chart only) — every other chart on the page
    # reuses that same page-level script via include_plotlyjs=False.
    tier_radar_html = tier_fig.to_html(full_html=False, include_plotlyjs="cdn", config=_PLOTLY_CONFIG)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html.j2")
    ctx = _build_context(report, target_org)
    ctx["tier_radar_html"] = tier_radar_html

    for f in ctx["functions"]:
        cat_fig = _category_radar_figure(report, f["function"])
        f["category_radar_html"] = (
            cat_fig.to_html(full_html=False, include_plotlyjs=False, config=_PLOTLY_CONFIG) if cat_fig else None
        )

    return template.render(**ctx)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="session_id")
    parser.add_argument("--run", required=True, dest="run_id", help="run_id (must have persisted scores)")
    parser.add_argument("--out", type=Path, default=Path("csf_report.html"))
    args = parser.parse_args()

    async def _fetch() -> tuple[dict, str]:
        report = await build_report(args.session, args.run_id)
        session = await get_session(args.session)
        target_org = session.target_org if session else args.session
        return report, target_org

    try:
        report, target_org = asyncio.run(_fetch())
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    html = render_html(report, target_org)
    args.out.write_text(html, encoding="utf-8")

    total_categories = sum(len(f["categories"]) for f in report["functions"].values())
    summary = ", ".join(f"{fn}={len(f['categories'])}" for fn, f in report["functions"].items())
    print(f"wrote {total_categories} Categories across {len(report['functions'])} Function(s) ({summary}) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
