"""
Export a session's persisted Category/Subcategory scores to a client-facing
Excel workbook — one row per Subcategory.

Columns: Function | Category | Subcategory | Notes/Observations | GapsFindings
| Recommendations | Scores. Reads `sessions/{sid}/runs/{rid}/scores/*`
(persisted ScoreOutput docs, so `score_category` must have been called with a
real `run_id` first).

Usage:
  poetry run python csf_specialists/scripts/export_excel.py --session <sid> --run <rid>
  poetry run python csf_specialists/scripts/export_excel.py --session <sid> --run <rid> --out findings.xlsx
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.cloud.firestore import AsyncClient
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from csf_gateway.app.config import get_settings
from csf_gateway.app.csf_catalog import CATEGORIES, FUNCTION_NAMES
from csf_specialists.aggregate import CONFIDENCE_THRESHOLD
from csf_specialists.firestore_util import aclose_firestore
from csf_specialists.loaders import load_implementation_examples

COLUMNS = [
    "Function", "Category", "Subcategory",
    "Notes/Observations", "GapsFindings", "Recommendations", "CMMI", "Confidence",
]
COLUMN_WIDTHS = [12, 34, 48, 50, 50, 50, 10, 14]

# CMMI is the headline score — fill the CMMI cell by level (red->green ramp,
# matching the HTML report's _CMMI_COLORS) so it stands out from the wide
# free-text columns instead of getting lost as a plain number.
_CMMI_FILL = {1: "dc2626", 2: "ea580c", 3: "ca8a04", 4: "65a30d", 5: "059669"}

# wrap_text=True alone doesn't resize row height for wrapped content — openpyxl
# has no rendering engine to compute that, so a row shows single-line height
# until someone manually double-clicks the row border, cutting off exactly the
# free-text columns this report exists to show. Estimate wrapped line count per
# row instead. Columns 1-5 (Category/Subcategory/Notes/GapsFindings/Recommendations,
# 0-indexed) are the ones long enough to actually wrap.
_WRAP_COL_INDICES = (1, 2, 3, 4, 5)
_POINTS_PER_LINE = 15  # ~ Excel's own default single-line row height at 11pt


async def fetch_scores(session_id: str, run_id: str) -> list[dict]:
    s = get_settings()
    client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    try:
        coll = (
            client.collection("sessions").document(session_id)
            .collection("runs").document(run_id)
            .collection("scores")
        )
        return [snap.to_dict() async for snap in coll.stream()]
    finally:
        await aclose_firestore(client)


def build_rows(scores: list[dict]) -> list[list]:
    rows: list[list] = []
    for score in sorted(scores, key=lambda s: s["category_id"]):
        function = score["function"]
        category_id = score["category_id"]
        function_name = FUNCTION_NAMES.get(function, function)
        category = CATEGORIES.get(category_id)
        category_label = f"{category_id} — {category.name}" if category else category_id
        examples = load_implementation_examples(function)

        for ss in sorted(score.get("subcategory_scores", []), key=lambda s: s["subcategory_id"]):
            sub_id = ss["subcategory_id"]
            sub_meta = examples.get(sub_id)
            subcategory_label = f"{sub_id} — {sub_meta.name}" if sub_meta else sub_id
            confidence = ss["confidence"]
            confidence_label = f"{confidence * 100:.0f}%"
            if confidence < CONFIDENCE_THRESHOLD:
                confidence_label += " ⚠ insufficient evidence"
            rows.append([
                function_name,
                category_label,
                subcategory_label,
                ss.get("observations", ""),
                ss.get("gap", ""),
                ss.get("recommendation", ""),
                ss["cmmi_level"],
                confidence_label,
            ])
    return rows


def _estimate_wrapped_height(row: list, col_widths: list[int]) -> float:
    """Rough estimate (in points) of the row height needed for its longest
    wrapped cell — good enough to avoid the default single-line cutoff, not a
    pixel-exact replacement for Excel's own layout engine."""
    max_lines = 1
    for idx in _WRAP_COL_INDICES:
        if idx >= len(row):
            continue
        text = str(row[idx])
        chars_per_line = max(int(col_widths[idx]), 10)
        wrapped_lines = -(-len(text) // chars_per_line)  # ceil division
        explicit_lines = text.count("\n") + 1
        max_lines = max(max_lines, wrapped_lines, explicit_lines)
    return max_lines * _POINTS_PER_LINE


def write_workbook(rows: list[list], out_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "CSF Findings"

    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    for row in rows:
        ws.append(row)

    for i, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row_idx].height = _estimate_wrapped_height(rows[row_idx - 2], COLUMN_WIDTHS)

    # Highlight the CMMI column — colored fill by level, bold, centered. Applied
    # AFTER the wrap-alignment loop above so it isn't overwritten.
    cmmi_col = COLUMNS.index("CMMI") + 1
    for row_idx in range(2, ws.max_row + 1):
        cell = ws.cell(row=row_idx, column=cmmi_col)
        lvl = cell.value
        if isinstance(lvl, int) and lvl in _CMMI_FILL:
            cell.fill = PatternFill("solid", fgColor=_CMMI_FILL[lvl])
            cell.font = Font(bold=True, size=13, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.freeze_panes = "A2"
    wb.save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="session_id")
    parser.add_argument("--run", required=True, dest="run_id", help="run_id (must have persisted scores)")
    parser.add_argument("--out", type=Path, default=Path("csf_findings.xlsx"))
    args = parser.parse_args()

    scores = asyncio.run(fetch_scores(args.session, args.run_id))
    if not scores:
        print(f"[error] no scores at sessions/{args.session}/runs/{args.run_id}/scores", file=sys.stderr)
        return 1

    rows = build_rows(scores)
    write_workbook(rows, args.out)
    print(f"wrote {len(rows)} Subcategory rows ({len(scores)} Categories) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# Cosmetic / polish backlog (not implemented — deferred)
# ---------------------------------------------------------------------------
# - One sheet per Function instead of a single flat "CSF Findings" sheet:
#   group rows by Function, create/name a workbook sheet per group. Matters
#   once more than one Function is being scored in the same run.
# - Excel formatting: header fill color, cell borders, alternating row bands,
#   auto-filter on the header row, conditional formatting / color scale on
#   the Scores column (e.g. red-to-green by CMMI level 1-5), center-aligned
#   Scores column.
