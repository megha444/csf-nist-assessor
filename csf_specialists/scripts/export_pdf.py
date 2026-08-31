"""
Report generator v3 — the client-ready PDF for one run. Five sections:

  1. Executive Summary   — LLM narrative + a six-Function card grid
  2. Results Overview    — Tier radar (left) + every CMMI score (right)
  3. Areas of Improvement— LLM-synthesised themes, grounded in real gaps
  4. Detailed Findings   — the same 7-column Subcategory table the HTML report uses
  5. Appendix            — the documents provided for this session, by name

Sits on the same data path as v1/v2: `export_json.build_report` for the Firestore
read and `export_html._build_context` for the display names, low-confidence flags
and Memory Bank deltas. Prose comes from `csf_specialists.narrative`.

WHY REPORTLAB. The obvious move — print the existing Jinja report to PDF — was
rejected twice for the same reason: WeasyPrint needs pango/cairo apt packages in a
runtime image that installs zero system packages today, and neither it nor any
other HTML engine available here executes Plotly's JavaScript, so the radars come
out blank. Kaleido would fix the charts by bundling a Chromium binary into an image
shared by all three Cloud Run services. ReportLab is a pure-Python wheel needing no
Dockerfile change at all, and the radar below is drawn as native vector graphics
rather than exported from Plotly — which is why this path works where those didn't.

IMPORT BOUNDARY: this module is the only one that imports reportlab, and it is
imported by csf_ui/app.py and its own CLI ONLY. It must never enter the
csf_coordinator.steps / csf_specialists.agents import chain, because that chain is
also what coordinator_engine/requirements.txt has to satisfy for the Agent Engine
deployment, and reportlab is not in it. The LLM half lives in
csf_specialists/narrative.py precisely so the coordinator can call it without
pulling reportlab in.

Usage:
  poetry run python csf_specialists/scripts/export_pdf.py --session <sid> --run <rid>
  poetry run python csf_specialists/scripts/export_pdf.py --session <sid> --run <rid> --out report.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from csf_gateway.app.csf_catalog import FUNCTION_NAMES, categories_for_function
from csf_gateway.app.schema import ReportNarrative
from csf_specialists.aggregate import CONFIDENCE_THRESHOLD, overall_maturity
from csf_specialists.narrative import FUNCTION_DEFINITIONS
from csf_specialists.scripts.export_html import _CMMI_COLORS, _FUNCTION_COLORS, _build_context
from csf_specialists.scripts.export_json import build_report

# ---------------------------------------------------------------------------
# Page geometry + palette
# ---------------------------------------------------------------------------

PAGE_SIZE = landscape(A4)                    # 841.89 x 595.28 pt
MARGIN_X = 14 * mm
MARGIN_TOP = 14 * mm
MARGIN_BOTTOM = 16 * mm                      # the extra 2mm is the footer band
FRAME_W = PAGE_SIZE[0] - 2 * MARGIN_X        # ~762 pt

# Report chrome. Navy + gold matches the approved Executive Summary template;
# the greys are the same Tailwind-slate values report.html.j2 already uses, so
# the PDF and the HTML report read as one family.
NAVY = colors.HexColor("#1e2f5e")
GOLD = colors.HexColor("#c8a04f")
INK = colors.HexColor("#1e2530")
MUTED = colors.HexColor("#64748b")
BORDER = colors.HexColor("#e2e8f0")
BAND = colors.HexColor("#f1f5f9")
ZEBRA = colors.HexColor("#f5f7fa")           # alternating findings rows
RED = colors.HexColor("#b91c1c")
COVER_TINT = colors.HexColor("#c9d3ea")      # muted text on the navy cover
COVER_RULE = colors.HexColor("#3f5183")      # hairline on the navy cover

# Type1 base-14 fonts only — no font files to ship, no Dockerfile change. Times
# for headings and Helvetica for body approximates the template's serif/sans pairing.
SERIF_BOLD = "Times-Bold"
SANS = "Helvetica"
SANS_BOLD = "Helvetica-Bold"
SANS_ITALIC = "Helvetica-Oblique"


def _s(name: str, **kw) -> ParagraphStyle:
    """Body-text style with overridable defaults. Merged into a dict first rather
    than splatted alongside them — passing fontName= through **kw would otherwise
    collide with the default and raise."""
    base = dict(fontName=SANS, fontSize=9, leading=12.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


STYLES = {
    "title":      ParagraphStyle("title", fontName=SERIF_BOLD, fontSize=23, leading=27, textColor=NAVY),
    "section":    ParagraphStyle("section", fontName=SERIF_BOLD, fontSize=17, leading=21, textColor=NAVY),
    "subtitle":   _s("subtitle", fontName=SANS_ITALIC, fontSize=8.5, leading=11, textColor=MUTED),
    "lede":       _s("lede", fontSize=9.5, leading=14.5),
    "body":       _s("body"),
    "card_name":  ParagraphStyle("card_name", fontName=SERIF_BOLD, fontSize=11, leading=13, textColor=NAVY),
    "card_def":   _s("card_def", fontName=SANS_ITALIC, fontSize=7.5, leading=10, textColor=MUTED),
    "card_body":  _s("card_body", fontSize=8.5, leading=11.5),
    "theme_title": ParagraphStyle("theme_title", fontName=SERIF_BOLD, fontSize=11.5, leading=14, textColor=NAVY),
    "theme_body": _s("theme_body", fontSize=9, leading=13),
    "theme_refs": _s("theme_refs", fontSize=7, leading=9, textColor=MUTED),
    "fn_head":    ParagraphStyle("fn_head", fontName=SERIF_BOLD, fontSize=13, leading=16, textColor=NAVY),
    "cat_head":   ParagraphStyle("cat_head", fontName=SANS_BOLD, fontSize=9.5, leading=12, textColor=INK),
    "cat_reason": _s("cat_reason", fontName=SANS_ITALIC, fontSize=7.5, leading=10, textColor=MUTED),
    "th":         _s("th", fontName=SANS_BOLD, fontSize=7.5, leading=9.5),
    "td":         _s("td", fontSize=7.5, leading=9.5),
    "td_c":       _s("td_c", fontSize=7.5, leading=9.5, alignment=1),
    "scan":       _s("scan", fontSize=7, leading=9),
    "appendix":   _s("appendix", fontSize=9.5, leading=15),
    "badge":      _s("badge", fontName=SANS_BOLD, fontSize=8.5, leading=10,
                     alignment=1, textColor=colors.white),
    "theme_num":  ParagraphStyle("theme_num", fontName=SERIF_BOLD, fontSize=20, leading=22,
                                 textColor=colors.HexColor("#dbe0ea")),
}

# cp1252 is exactly what the base-14 Type1 fonts can encode (WinAnsi). Anything
# outside it renders as a black box or blows up at canvas time, and the scoring
# agents do occasionally emit an arrow or a warning glyph. Map the characters
# that have a sensible ASCII equivalent, then drop whatever is left — em dash,
# curly quotes and bullets all survive, since cp1252 covers them.
_UNICODE_FALLBACKS = str.maketrans({
    "→": "->", "←": "<-", "≥": ">=", "≤": "<=",
    " ": " ", " ": " ", "​": "", "⚠": "", "✓": "",
    "▲": "+", "▼": "-",
})


def _clean(text: object) -> str:
    """Make agent/LLM text safe for both WinAnsi encoding and Paragraph's XML parser."""
    if text is None:
        return ""
    s = str(text).translate(_UNICODE_FALLBACKS)
    s = s.encode("cp1252", "ignore").decode("cp1252")
    return escape(s)


def _p(text: object, style: str = "body") -> Paragraph:
    return Paragraph(_clean(text), STYLES[style])


def _rule(color=GOLD, width: float = 46, thickness: float = 2.5, space_after: float = 7) -> HRFlowable:
    return HRFlowable(width=width, thickness=thickness, color=color,
                      spaceBefore=0, spaceAfter=space_after, hAlign="LEFT")


def _section_heading(title: str, subtitle: str | None = None) -> list:
    out: list = [_p(title, "section"), Spacer(1, 4)]
    if subtitle:
        out += [_p(subtitle, "subtitle"), Spacer(1, 5)]
    out.append(_rule(width=FRAME_W, thickness=1, color=BORDER, space_after=12))
    return out


# ---------------------------------------------------------------------------
# Radar — hand-drawn vector, one spoke per Function, r = Tier (1-4)
# ---------------------------------------------------------------------------


def _radar_drawing(ctx: dict, size: float = 310) -> Drawing:
    """Executive radar: 6 spokes, radius = that Function's Tier.

    Plots Tier rather than average CMMI to match `_tier_radar_figure` and the
    Streamlit Overview tab exactly — a judge comparing the screen to the PDF
    should see the same shape. The finer-grained avg CMMI sits in the summary
    table immediately below, so nothing is lost by it.

    A Function with no aggregated Tier plots at r=0 (collapsed to the centre)
    rather than being dropped, so the hexagon keeps its six spokes and an
    unassessed Function reads as a visible dent instead of a different shape.
    """
    tiers_by_fn = {f["function"]: f.get("tier") or 0 for f in ctx["functions"]}
    functions = list(FUNCTION_NAMES)
    n = len(functions)

    d = Drawing(size, size)
    cx = cy = size / 2
    radius = size / 2 - 46  # headroom for the outer labels
    # Start at 12 o'clock and run clockwise, so Govern sits at the top and the
    # order round the chart matches the canonical Govern->Recover reading order.
    angles = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]

    # Ring labels sit on the bisector between two spokes, not on the vertical
    # axis — on the axis they land on the Govern spoke and its data vertex, and
    # at low Tiers the "1" and "2" end up inside the filled polygon.
    label_angle = math.pi / 2 - math.pi / len(functions)
    for level in range(1, 5):
        rr = radius * level / 4
        pts: list[float] = []
        for a in angles:
            pts += [cx + rr * math.cos(a), cy + rr * math.sin(a)]
        d.add(Polygon(pts, strokeColor=BORDER, strokeWidth=0.6, fillColor=None))
        d.add(String(cx + rr * math.cos(label_angle) + 2, cy + rr * math.sin(label_angle) - 2,
                     str(level), fontName=SANS, fontSize=6, fillColor=MUTED))

    for a in angles:
        d.add(Line(cx, cy, cx + radius * math.cos(a), cy + radius * math.sin(a),
                   strokeColor=BORDER, strokeWidth=0.6))

    pts = []
    for fn, a in zip(functions, angles):
        rr = radius * tiers_by_fn.get(fn, 0) / 4
        pts += [cx + rr * math.cos(a), cy + rr * math.sin(a)]
    d.add(Polygon(pts, strokeColor=NAVY, strokeWidth=1.6,
                  fillColor=colors.Color(NAVY.red, NAVY.green, NAVY.blue, alpha=0.20)))

    for i, (fn, a) in enumerate(zip(functions, angles)):
        rr = radius * tiers_by_fn.get(fn, 0) / 4
        d.add(Circle(cx + rr * math.cos(a), cy + rr * math.sin(a), 2.6,
                     fillColor=colors.HexColor(_FUNCTION_COLORS[fn]), strokeColor=None))

        lx, ly = cx + (radius + 12) * math.cos(a), cy + (radius + 12) * math.sin(a)
        cosine = math.cos(a)
        anchor = "middle" if abs(cosine) < 0.25 else ("start" if cosine > 0 else "end")
        tier = tiers_by_fn.get(fn, 0)
        d.add(String(lx, ly + 1, FUNCTION_NAMES[fn], fontName=SANS_BOLD, fontSize=7.5,
                     fillColor=INK, textAnchor=anchor))
        d.add(String(lx, ly - 8, f"Tier {tier}" if tier else "not assessed",
                     fontName=SANS, fontSize=6.5, fillColor=MUTED, textAnchor=anchor))

    return d


# ---------------------------------------------------------------------------
# 1. Executive Summary
# ---------------------------------------------------------------------------


def _function_card(function: str, summary: str | None) -> list:
    color = colors.HexColor(_FUNCTION_COLORS[function])
    return [
        _rule(color=color, width=32, thickness=2.5, space_after=5),
        _p(FUNCTION_NAMES[function].upper(), "card_name"),
        Spacer(1, 3),
        _p(FUNCTION_DEFINITIONS[function], "card_def"),
        Spacer(1, 5),
        _p(summary or "Not assessed in this run.", "card_body"),
    ]


def _exec_summary(ctx: dict, narrative: ReportNarrative | None) -> list:
    summaries = {fs.function: fs.summary for fs in (narrative.function_summaries if narrative else [])}
    assessed = {f["function"] for f in ctx["functions"]}

    # The cover and the running header already carry the org, framework and date —
    # this line reports the result instead of repeating them.
    overall = ctx["overall"]
    subtitle = (
        f"Overall maturity: Tier {overall[1]} (average CMMI {overall[0]:.2f}) across "
        f"{len(ctx['functions'])} of 6 Functions assessed"
        if overall else "No Function has been aggregated for this run yet"
    )
    story: list = [
        _p("Executive Summary", "title"),
        Spacer(1, 6),
        _p(subtitle, "subtitle"),
        Spacer(1, 8),
        _rule(width=FRAME_W, thickness=1, color=BORDER, space_after=12),
    ]

    if narrative and narrative.intro:
        story += [_p(narrative.intro, "lede"), Spacer(1, 6),
                  _rule(width=FRAME_W, thickness=0.6, color=BORDER, space_after=14)]

    # 3 x 2 grid, canonical Govern->Recover order reading left-to-right then down.
    # Every Function gets a card even when it wasn't assessed, so the grid never
    # reflows into a ragged shape between runs.
    order = list(FUNCTION_NAMES)
    rows = [
        [_function_card(fn, summaries.get(fn) if fn in assessed else None) for fn in order[i:i + 3]]
        for i in (0, 3)
    ]
    col_w = (FRAME_W - 2 * 18) / 3
    grid = Table(rows, colWidths=[col_w + 12, col_w + 12, col_w + 12], hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 22),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 22),
    ]))
    story.append(grid)
    return story


# ---------------------------------------------------------------------------
# 2. Results Overview — radar left, every CMMI score right
# ---------------------------------------------------------------------------


def _tier_summary_table(ctx: dict, half_w: float) -> Table:
    overall = ctx["overall"]
    rows = [[_p("Overall maturity", "th"),
             _p(f"Tier {overall[1]}" if overall else "—", "th"),
             _p(f"CMMI {overall[0]:.2f}" if overall else "—", "th")]]
    for f in ctx["functions"]:
        rows.append([
            _p(f["name"], "scan"),
            _p(f"Tier {f['tier']}" if f["tier"] else "—", "scan"),
            _p(f"CMMI {f['avg_cmmi']:.2f}" if f["avg_cmmi"] is not None else "—", "scan"),
        ])
    t = Table(rows, colWidths=[half_w * 0.5, half_w * 0.25, half_w * 0.25], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# Four narrow columns rather than three wider ones. With three, the ~134 entries
# came to 47 rows per column and overflowed the frame by ~30pt; four brings it to
# ~34 and leaves real headroom. Labels are bare CSF codes for the same reason —
# a Category *name* wraps to two or three lines in a column this narrow, which is
# what actually blew the height budget. Names live in Detailed Findings; this
# page is the scan-the-numbers view.
_SCORE_COLUMNS = 4
_LABEL_W = 48   # fits "GV.SC-10" at 6.8pt with the Subcategory indent
_CMMI_W = 13


def _score_rows(ctx: dict) -> list[tuple[str, str, str, int | None]]:
    """The full Function -> Category -> Subcategory CMMI listing, flattened to
    (kind, label, function, cmmi) so it can be split across columns."""
    rows: list[tuple[str, str, str, int | None]] = []
    for f in ctx["functions"]:
        rows.append(("fn", f["name"].upper(), f["function"], None))
        for c in f["categories"]:
            rows.append(("cat", c["category_id"], f["function"], c["cmmi_level"]))
            for s in c["subcategory_scores"]:
                rows.append(("sub", s["subcategory_id"], f["function"], s["cmmi_level"]))
    return rows


def _split_columns(rows: list, n: int = _SCORE_COLUMNS) -> list[list]:
    """Balance the listing across n columns, breaking on a heading wherever one is
    close to the ideal cut, so a Function or Category heading never ends up at the
    foot of one column with the entries it heads at the top of the next.

    A Function break is worth reaching further for than a Category break, hence
    the wider window on the first pass."""
    target = math.ceil(len(rows) / n)
    cuts: list[int] = []
    start = 0
    for _ in range(n - 1):
        ideal = min(start + target, len(rows))
        best = ideal
        for kind, window in (("fn", 6), ("cat", 4)):
            found = next(
                (cand for offset in range(window)
                 for cand in (ideal - offset, ideal + offset)
                 if start < cand < len(rows) and rows[cand][0] == kind),
                None,
            )
            if found is not None:
                best = found
                break
        cuts.append(best)
        start = best
    bounds = [0, *cuts, len(rows)]
    return [rows[bounds[i]: bounds[i + 1]] for i in range(n)]


def _score_column(rows: list, width: float):
    # A Table with zero rows raises. Balancing across four columns leaves the last
    # one empty whenever the listing is short (ceil(9/4)=3 fills three columns and
    # strands the fourth) — which is exactly what a single-Category smoke run looks
    # like. Hand back a spacer so the four-column grid keeps its shape.
    if not rows:
        return Spacer(width, 0)

    data, styles = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]
    for i, (kind, label, function, cmmi) in enumerate(rows):
        if kind == "fn":
            color = colors.HexColor(_FUNCTION_COLORS[function])
            style = ParagraphStyle(f"fnrow{i}", fontName=SANS_BOLD, fontSize=7,
                                   leading=11, textColor=color, spaceBefore=2)
            data.append([Paragraph(_clean(label), style), ""])
            styles.append(("LINEBELOW", (0, i), (-1, i), 0.5, color))
        else:
            indent, size, font = (0, 7, SANS_BOLD) if kind == "cat" else (7, 6.8, SANS)
            text_color = INK if kind == "cat" else MUTED
            data.append([
                Paragraph(_clean(label), ParagraphStyle(
                    f"r{i}", fontName=font, fontSize=size, leading=8.8,
                    textColor=text_color, leftIndent=indent)),
                Paragraph(str(cmmi), ParagraphStyle(
                    f"c{i}", fontName=SANS_BOLD, fontSize=size, leading=8.8,
                    alignment=2, textColor=colors.HexColor(_CMMI_COLORS[cmmi]))),
            ])
    # Fixed narrow widths, NOT the full column slot: the score has to sit right
    # beside its own label. Stretching the label cell to fill the slot pushes the
    # number to the far right of the column, ~30pt from the label it belongs to
    # and a few pt from the NEXT column's labels — which reads, wrongly and
    # convincingly, as if the number scores the neighbouring Subcategory. The
    # slack becomes the inter-column gutter instead.
    t = Table(data, colWidths=[_LABEL_W, _CMMI_W], hAlign="LEFT")
    t.setStyle(TableStyle(styles))
    return t


def _results_overview(ctx: dict) -> list:
    half = FRAME_W / 2
    left = [_radar_drawing(ctx, size=272), Spacer(1, 12), _tier_summary_table(ctx, half - 30)]

    col_w = (half - 14) / _SCORE_COLUMNS
    columns = [_score_column(chunk, col_w) for chunk in _split_columns(_score_rows(ctx))]
    right_inner = Table([columns], colWidths=[col_w] * _SCORE_COLUMNS, hAlign="LEFT")
    right_inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    right = [_p("Assessment scoring — CMMI by Function, Category and Subcategory", "th"),
             Spacer(1, 6), right_inner]

    split = Table([[left, right]], colWidths=[half, half], hAlign="LEFT")
    split.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))

    return _section_heading(
        "Results Overview",
        "Maturity by Function on the NIST CSF Tier scale (1-4), with the underlying CMMI score (1-5) for every "
        "Category and Subcategory assessed.",
    ) + [split]


# ---------------------------------------------------------------------------
# 3. Areas of Improvement
# ---------------------------------------------------------------------------


def _areas_of_improvement(narrative: ReportNarrative | None) -> list:
    story = _section_heading(
        "Areas of Improvement",
        "The themes running through this assessment's findings, most material first.",
    )
    themes = narrative.improvement_themes if narrative else []
    if not themes:
        story.append(_p("No improvement themes were generated for this run.", "body"))
        return story

    for i, theme in enumerate(themes, start=1):
        body: list = [_p(theme.body, "theme_body")]
        if theme.refs:
            body += [Spacer(1, 4), _p("Grounded in: " + ", ".join(theme.refs), "theme_refs")]
        # Numbered, because these are ordered by materiality and the ranking is
        # part of the message — an unnumbered list reads as a set of equals.
        row = Table(
            [[_p(f"{i:02d}", "theme_num"),
              [_rule(width=42, thickness=2.5, space_after=6), _p(theme.title, "theme_title")],
              body]],
            colWidths=[38, FRAME_W * 0.28, FRAME_W * 0.72 - 38], hAlign="LEFT",
        )
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (2, 0), (2, 0), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
        ]))
        story.append(KeepTogether(row))
    return story


# ---------------------------------------------------------------------------
# 4. Detailed Findings — the same 7 columns as report.html.j2
# ---------------------------------------------------------------------------

# Mirrors report.html.j2's explicit column widths so the PDF and HTML tables read
# identically: the three free-text columns get the room, the numeric ones don't.
_FINDINGS_WIDTHS = [0.15, 0.05, 0.07, 0.07, 0.22, 0.22, 0.22]
_FINDINGS_HEADERS = ["Subcategory", "CMMI", "Evidence", "Confidence", "Observations", "Gap", "Recommendation"]


def _cmmi_badge(level: int, width: float = 52) -> Table:
    """The score as a filled pill rather than a bare numeral — it is the headline
    of a Category and should read as one at a glance."""
    t = Table([[_p(f"CMMI {level}", "badge")]], colWidths=[width], rowHeights=[16])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_CMMI_COLORS[level])),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _function_band(f: dict) -> Table:
    """Repeated at the top of every one of that Function's Category pages, so a
    page pulled out of the middle of the report still says where it belongs."""
    color = colors.HexColor(f["color"])
    label = f["name"].upper() + (f"   ·   TIER {f['tier']}" if f["tier"] else "")
    style = ParagraphStyle("fn_band", fontName=SANS_BOLD, fontSize=9, leading=11, textColor=color)
    t = Table([[Paragraph(_clean(label), style)]], colWidths=[FRAME_W])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 2, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _subcategory_table(category: dict) -> LongTable:
    """The Category's Subcategory findings.

    The Category's own title and score are the table's FIRST row, not a flowable
    above it, so `repeatRows=2` carries them onto a continuation page. A Category
    with ten Subcategories (GV.SC, ID.RA, DE.CM) cannot fit one page at this row
    height whatever the layout does; without this, the overflow page arrived as a
    bare grid with nothing saying which Category it belonged to.
    """
    meta = [f"confidence {category['confidence'] * 100:.0f}%"]
    if category["low_confidence"]:
        meta.append("insufficient evidence")
    if category["no_doc_evidence"]:
        meta.append("no document evidence")
    heading = (
        f"<b>{_clean(category['category_id'])} — {_clean(category['name'])}</b><br/>"
        f'<font size="7" color="#64748b">{_clean("  ·  ".join(meta))}</font>'
    )

    # Row 0 title, row 1 the Category's own reasoning, row 2 column headers — all
    # three repeated. The reasoning belongs UNDER the title it explains; as a
    # flowable above the table it printed before the Category was named and read
    # as commentary on the Function band instead.
    data = [
        [Paragraph(heading, STYLES["cat_head"]), "", "", "", "", "", _cmmi_badge(category["cmmi_level"])],
        [_p(category["reasoning"], "cat_reason"), "", "", "", "", "", ""],
        [_p(h, "th") for h in _FINDINGS_HEADERS],
    ]
    styles = [
        ("SPAN", (0, 0), (5, 0)),
        ("SPAN", (0, 1), (-1, 1)),
        ("VALIGN", (6, 0), (6, 0), "MIDDLE"),
        ("ALIGN", (6, 0), (6, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
        ("LINEBELOW", (0, 1), (-1, 1), 1, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 2), (-1, 2), BAND),
        ("GRID", (0, 2), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 2), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 2), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 2), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, 1), 0),
        ("RIGHTPADDING", (6, 0), (6, 0), 0),
        # Zebra striping: these rows carry three columns of prose each, and a flat
        # grid makes it easy to read across into the wrong row.
        ("ROWBACKGROUNDS", (0, 3), (-1, -1), [colors.white, ZEBRA]),
    ]
    for i, s in enumerate(category["subcategory_scores"], start=3):
        label = f"{s['subcategory_id']} — {s['name']}" if s.get("name") else s["subcategory_id"]
        # "low" spelled out rather than a warning glyph: the base-14 Type1 fonts
        # have no glyph for one, and it is the flag's meaning that matters here.
        confidence = f"{s['confidence'] * 100:.0f}%" + (" low" if s["low_confidence"] else "")
        data.append([
            _p(label, "td"),
            _p(s["cmmi_level"], "td_c"),
            _p(s["evidence_status"], "td_c"),
            _p(confidence, "td_c"),
            _p(s["observations"], "td"),
            _p(s["gap"], "td"),
            _p(s["recommendation"], "td"),
        ])
        styles.append(("TEXTCOLOR", (1, i), (1, i), colors.HexColor(_CMMI_COLORS[s["cmmi_level"]])))
        styles.append(("FONTNAME", (1, i), (1, i), SANS_BOLD))
        if s["low_confidence"]:
            styles.append(("TEXTCOLOR", (3, i), (3, i), RED))

    t = LongTable(data, colWidths=[FRAME_W * w for w in _FINDINGS_WIDTHS], repeatRows=3)
    t.setStyle(TableStyle(styles))
    return t


def _detailed_findings(ctx: dict) -> list:
    story = _section_heading(
        "Detailed Findings",
        f"Every Subcategory assessed, by Function and Category. Confidence below "
        f"{ctx['confidence_threshold_pct']}% means the evidence provided was too thin to score reliably.",
    )
    # One Category per page. Each page repeats its Function's band so it stands
    # alone, which is what makes the section usable in a meeting — a reader can
    # turn straight to PR.AA and have the whole Category in front of them instead
    # of hunting for where it started. A Category with enough Subcategories to
    # overrun (GV.SC's ten) still splits, repeating the table header; the next
    # Category always begins on a fresh page regardless.
    first = True
    for f in ctx["functions"]:
        for c in f["categories"]:
            if not first:
                story.append(PageBreak())
            first = False
            story += [_function_band(f), Spacer(1, 11), _subcategory_table(c)]
    return story


# ---------------------------------------------------------------------------
# 5. Appendix
# ---------------------------------------------------------------------------


def _appendix(ctx: dict, document_names: list[str]) -> list:
    story = _section_heading(
        "Appendix — Documents Provided",
        "The evidence this assessment was based on. Only documents present when the assessment was "
        "dispatched are listed.",
    )
    if not document_names:
        story.append(_p("No documents were recorded for this session.", "body"))
        return story
    for i, name in enumerate(document_names, start=1):
        # Built directly rather than through _p(): the &nbsp; entities are markup
        # we want the Paragraph parser to see, and _clean has already escaped the
        # filename itself, so a second pass would render the escapes literally.
        story.append(Paragraph(f"{i}.&nbsp;&nbsp;&nbsp;{_clean(name)}", STYLES["appendix"]))
    story += [
        Spacer(1, 16),
        _p(f"Session {ctx['session_id']}  ·  Run {ctx['run_id']}  ·  Generated {ctx['generated_at']}", "theme_refs"),
    ]
    return story


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _clean_plain(text: object) -> str:
    """_clean without the XML escaping — canvas.drawString is not markup-parsed."""
    return str(text).translate(_UNICODE_FALLBACKS).encode("cp1252", "ignore").decode("cp1252")


def _fit_font(text: str, font: str, ideal: float, max_width: float, floor: float = 14) -> float:
    """Largest size at or below `ideal` that keeps `text` on one line. Org names
    are free text from the session — 'Northwind Financial' sets at 34pt with room
    to spare, but a long legal entity name would otherwise run off the cover."""
    size = ideal
    while size > floor and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _cover_page(target_org: str, ctx: dict):
    """The title page, painted straight onto the canvas rather than assembled from
    flowables — a full-bleed panel has to escape the frame's margins, and at this
    scale absolute placement is more legible than a stack of spacers."""
    org = _clean_plain(target_org)
    overall = ctx["overall"]

    def draw(canvas, doc):
        w, h = PAGE_SIZE
        canvas.saveState()

        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, w, h, stroke=0, fill=1)

        canvas.setFillColor(GOLD)
        canvas.rect(MARGIN_X, h * 0.62, 64, 3, stroke=0, fill=1)

        size = _fit_font(org, SERIF_BOLD, 36, FRAME_W * 0.8)
        canvas.setFillColor(colors.white)
        canvas.setFont(SERIF_BOLD, size)
        canvas.drawString(MARGIN_X, h * 0.62 - 20 - size, org)

        canvas.setFillColor(COVER_TINT)
        canvas.setFont(SANS, 14)
        canvas.drawString(MARGIN_X, h * 0.62 - 52 - size, "NIST Cybersecurity Framework 2.0")
        canvas.setFont(SANS, 14)
        canvas.drawString(MARGIN_X, h * 0.62 - 72 - size, "Cybersecurity Maturity Assessment")

        rule_y = h * 0.32
        canvas.setStrokeColor(COVER_RULE)
        canvas.setLineWidth(0.7)
        canvas.line(MARGIN_X, rule_y, w - MARGIN_X, rule_y)

        # Headline result on the cover: the one number a Board member is looking
        # for. Omitted rather than faked when no Function has aggregated yet.
        facts = [("Assessment date", ctx["generated_at_human"])]
        if overall:
            facts.append(("Overall maturity", f"Tier {overall[1]}  ·  CMMI {overall[0]:.2f}"))
        facts.append(("Functions assessed", f"{len(ctx['functions'])} of 6"))

        x = MARGIN_X
        for label, value in facts:
            canvas.setFillColor(COVER_RULE)
            canvas.setFont(SANS_BOLD, 7.5)
            canvas.drawString(x, rule_y - 22, _clean_plain(label).upper())
            canvas.setFillColor(colors.white)
            canvas.setFont(SANS, 12)
            canvas.drawString(x, rule_y - 40, _clean_plain(value))
            x += 210

        canvas.setFillColor(COVER_RULE)
        canvas.setFont(SANS, 7.5)
        canvas.drawString(MARGIN_X, MARGIN_BOTTOM - 9 * mm, "INTERNAL — CONFIDENTIAL")
        canvas.drawRightString(
            w - MARGIN_X, MARGIN_BOTTOM - 9 * mm,
            _clean_plain(f"Session {ctx['session_id'][:8]}  ·  Run {ctx['run_id'][:8]}"),
        )
        canvas.restoreState()

    return draw


def _running_header(target_org: str):
    """Thin masthead on every page after the cover. Static text — with one
    Category per page and a coloured Function band on each, the reader already
    knows which section they are in; this just carries the report's identity."""
    text = _clean_plain(f"NIST CSF 2.0 Cybersecurity Maturity Assessment  ·  {target_org}")

    def draw(canvas, doc):
        w, h = PAGE_SIZE
        y = h - MARGIN_TOP + 16
        canvas.saveState()
        canvas.setFont(SANS, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X, y, text)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, y - 5, w - MARGIN_X, y - 5)
        canvas.restoreState()

    return draw


def _make_canvas_class(target_org: str):
    """Canvas that defers footer painting until every page exists, so it can print
    'Page N of M'. The page count isn't knowable during layout — the standard
    reportlab answer is to stash each page's state and replay it at save() time.

    The cover is skipped: it paints its own confidentiality line and a page number
    on a title page would be wrong."""
    footer_left = _clean_plain(f"{target_org}  |  Internal — Confidential")

    class _ReportCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_states = []

        def showPage(self):
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            states = self._saved_states
            total = len(states)
            for number, state in enumerate(states, start=1):
                self.__dict__.update(state)
                if number > 1:
                    self._draw_footer(number, total)
                pdfcanvas.Canvas.showPage(self)
            pdfcanvas.Canvas.save(self)

        def _draw_footer(self, number: int, total: int) -> None:
            y = MARGIN_BOTTOM - 9 * mm
            self.saveState()
            self.setFont(SANS, 7.5)
            self.setFillColor(MUTED)
            self.drawString(MARGIN_X, y, footer_left)
            self.drawRightString(PAGE_SIZE[0] - MARGIN_X, y, f"Page {number} of {total}")
            self.restoreState()

    return _ReportCanvas


def render_pdf(
    report: dict,
    narrative: ReportNarrative | None,
    target_org: str,
    document_names: list[str],
) -> bytes:
    """Render the five-section PDF. Pure function of already-fetched data — no
    Firestore, no LLM — so it is cheap enough to call on every Streamlit rerun."""
    ctx = _build_context(report, target_org)
    now = datetime.now(timezone.utc)
    ctx["generated_at_human"] = now.strftime("%B %Y")
    ctx["overall"] = overall_maturity(report)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"NIST CSF 2.0 Assessment — {_clean_plain(target_org)}",
        author="CSF Assessor Fleet",
        subject="NIST CSF 2.0 Cybersecurity Maturity Assessment",
    )

    # The cover is painted entirely by the onFirstPage callback, so page 1's story
    # is just enough to claim a page.
    story: list = [Spacer(1, 1)]
    for section in (
        _exec_summary(ctx, narrative),
        _results_overview(ctx),
        _areas_of_improvement(narrative),
        _detailed_findings(ctx),
        _appendix(ctx, document_names),
    ):
        story.append(PageBreak())
        story += section

    doc.build(
        story,
        onFirstPage=_cover_page(target_org, ctx),
        onLaterPages=_running_header(target_org),
        canvasmaker=_make_canvas_class(target_org),
    )
    return buf.getvalue()


async def build_pdf_bytes(session_id: str, run_id: str, *, generate_missing_narrative: bool = True) -> bytes:
    """Fetch everything one run's PDF needs, then render it.

    Generates the narrative on demand when the run has none. That is the normal
    path for any run completed before NarrativeStep shipped, and the fallback for
    a run whose NarrativeStep failed — in both cases the result is persisted, so
    only the first download pays for the Gemini call.
    """
    from csf_specialists.narrative import (
        generate_narrative,
        load_narrative,
        run_document_names,
        session_target_org,
    )

    report = await build_report(session_id, run_id)
    target_org = await session_target_org(session_id)
    document_names = await run_document_names(session_id, run_id)

    narrative = await load_narrative(session_id, run_id)
    if narrative is None and generate_missing_narrative:
        narrative = await generate_narrative(session_id, run_id)

    return render_pdf(report, narrative, target_org, document_names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="session_id")
    parser.add_argument("--run", required=True, dest="run_id", help="run_id (must have persisted scores)")
    parser.add_argument("--out", type=Path, default=Path("csf_report.pdf"))
    parser.add_argument(
        "--no-narrative", action="store_true",
        help="skip the Gemini call when this run has no persisted narrative (renders the scoring sections only)",
    )
    args = parser.parse_args()

    try:
        pdf = asyncio.run(build_pdf_bytes(
            args.session, args.run_id, generate_missing_narrative=not args.no_narrative,
        ))
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    args.out.write_bytes(pdf)
    print(f"wrote {len(pdf):,} bytes -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
