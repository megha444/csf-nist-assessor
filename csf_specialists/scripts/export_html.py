"""
Report generator v2 — HTML output for one run: exec-style header, two Plotly
radars, and full per-Category detail (Subcategory table, evidence citations,
interview evidence). Renders `csf_specialists/templates/report.html.j2` via
Jinja2.

Two radars, matching the plan's two-layer scoring model (`docs/
csf_assessor_hackathon_plan.md` §2/§3/§10 — "radar chart (Tier) + heatmap
(CMMI)"): the Tier radar is the board-level view (one spoke per Function, r =
Tier 1-4); the Category radar is the practitioner drill-down (one spoke per
Category grouped by Function, r = CMMI 1-5). Kept as two separate charts
deliberately — collapsing them into one Category-only radar was a v2.0 bug,
since it dropped the executive-layer view the plan calls for.

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
    )
    return fig


def _category_radar_figure(report: dict) -> go.Figure:
    """Practitioner view: one polar trace per scored Function, one spoke per its Categories, r = CMMI level (1-5)."""
    fig = go.Figure()
    for function, data in report["functions"].items():
        cat_by_id = {c["category_id"]: c for c in data["categories"]}
        ordered_ids = [c.code for c in categories_for_function(function) if c.code in cat_by_id]
        if not ordered_ids:
            continue
        theta = ordered_ids + ordered_ids[:1]  # close the loop
        r = [cat_by_id[cid]["cmmi_level"] for cid in ordered_ids]
        r = r + r[:1]
        fig.add_trace(go.Scatterpolar(
            r=r, theta=theta, name=FUNCTION_NAMES.get(function, function),
            fill="toself", line=dict(color=_FUNCTION_COLORS.get(function, "#64748b")),
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 5], dtick=1)),
        showlegend=len(report["functions"]) > 1,
        margin=dict(l=40, r=40, t=30, b=30),
        height=460,
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

        categories_ctx = []
        for cat in categories_for_function(function):
            c = cat_by_id.get(cat.code)
            if not c:
                continue
            subs = []
            for ss in sorted(c["subcategory_scores"], key=lambda s: s["subcategory_id"]):
                meta = examples.get(ss["subcategory_id"])
                subs.append({**ss, "name": meta.name if meta else ""})
            categories_ctx.append({**c, "name": cat.name, "subcategory_scores": subs})

        tier_data = data["tier"] or {}
        functions_ctx.append({
            "function": function,
            "name": FUNCTION_NAMES[function],
            "color": _FUNCTION_COLORS.get(function, "#64748b"),
            "tier": tier_data.get("tier"),
            "avg_cmmi": tier_data.get("avg_cmmi"),
            "categories": categories_ctx,
        })

    return {
        "target_org": target_org,
        "session_id": report["session_id"],
        "run_id": report["run_id"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "functions": functions_ctx,
        "cmmi_colors": _CMMI_COLORS,
    }


def render_html(report: dict, target_org: str) -> str:
    tier_fig = _tier_radar_figure(report)
    category_fig = _category_radar_figure(report)
    # Load plotly.js once (first chart only) — the second reuses the same page-level script.
    tier_radar_html = tier_fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})
    category_radar_html = category_fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html.j2")
    ctx = _build_context(report, target_org)
    ctx["tier_radar_html"] = tier_radar_html
    ctx["category_radar_html"] = category_radar_html
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
