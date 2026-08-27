"""
Deterministically preseed a session's `answers/` from the Northwind questionnaire.

The questionnaire (`Ref Docs/Northwind Questionnaire.xlsx`) is already structured —
6 sheets (one per CSF Function), columns Category / Sub-category / Questions / Answer,
with the Sub-category cell filled once per group and blank on continuation rows. This
reads it directly and writes one PreseedRecord per Q&A row (234 total), tagged with the
subcategory ID the questionnaire itself assigns — NO LLM extraction, so it's exact,
free, correctly categorized from the source, and immune to the UI's 60s upload timeout.

Reuses `preseed_govern.preseed()` (writes `sessions/{sid}/answers/{id}`, sets
`preseed_loaded=True`). Stable ids → idempotent (re-running overwrites, never duplicates).

Usage:
  poetry run python csf_specialists/scripts/preseed_questionnaire.py --session <sid> --dry-run
  poetry run python csf_specialists/scripts/preseed_questionnaire.py --session <sid>
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from csf_gateway.app.schema import PreseedRecord  # noqa: E402
from csf_specialists.scripts.preseed_govern import preseed  # noqa: E402

DEFAULT_FILE = REPO_ROOT / "Ref Docs" / "Northwind Questionnaire.xlsx"
SHEET_TO_FUNCTION = {
    "govern": "govern", "identify": "identify", "protect": "protect",
    "detect": "detect", "respond": "respond", "recover": "recover",
}
_SUBCAT_RE = re.compile(r"[A-Z]{2}\.[A-Z]{2}-\d{2}")  # e.g. GV.OC-01


def _hdr_index(header: list) -> dict[str, int]:
    """Map normalized header name -> column index (handles trailing spaces)."""
    idx = {}
    for i, h in enumerate(header):
        key = str(h or "").strip().lower()
        if key:
            idx[key] = i
    return idx


def _subcat_id(cell) -> str | None:
    if cell is None:
        return None
    m = _SUBCAT_RE.search(str(cell))
    return m.group(0) if m else None


def build_records(path: Path) -> list[PreseedRecord]:
    wb = openpyxl.load_workbook(path, data_only=True)
    records: list[PreseedRecord] = []
    for ws in wb.worksheets:
        fn = SHEET_TO_FUNCTION.get(ws.title.strip().lower())
        if fn is None:
            print(f"[warn] sheet {ws.title!r} is not a known Function — skipping", file=sys.stderr)
            continue
        rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None and str(c).strip() for c in r)]
        if not rows:
            continue
        h = _hdr_index(list(rows[0]))
        q_col, a_col, sc_col = h.get("questions"), h.get("answer"), h.get("sub-category")
        if q_col is None or a_col is None or sc_col is None:
            print(f"[warn] sheet {ws.title!r} missing expected columns {list(h)} — skipping", file=sys.stderr)
            continue

        current_subcat = None
        n = 0
        for row in rows[1:]:
            # forward-fill the subcategory (blank on continuation rows)
            sc = _subcat_id(row[sc_col]) if sc_col < len(row) else None
            if sc:
                current_subcat = sc
            question = str(row[q_col]).strip() if q_col < len(row) and row[q_col] else ""
            answer = str(row[a_col]).strip() if a_col < len(row) and row[a_col] else ""
            if not question or not answer:
                continue
            if not current_subcat:
                print(f"[warn] {ws.title}: Q&A row before any subcategory — skipped: {question[:50]!r}", file=sys.stderr)
                continue
            n += 1
            records.append(PreseedRecord(
                id=f"qn-{fn}-{n:03d}",
                question=question,
                answer=answer,
                function=fn,
                category_hint=current_subcat,
                provenance="pre_seeded",
                importance=2,
            ))
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, help="session_id to preseed (must already exist)")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true", help="validate + summarize, skip the Firestore write")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"[error] {args.file} not found", file=sys.stderr)
        return 1

    records = build_records(args.file)
    by_fn = Counter(r.function for r in records)
    by_cat = Counter(r.category_hint.rsplit("-", 1)[0] for r in records)
    print(f"parsed {len(records)} Q&A records from {args.file.name}")
    print(f"  by function: {dict(by_fn)}")
    print(f"  by category: {dict(sorted(by_cat.items()))}")

    if args.dry_run:
        print("[dry-run] skipping Firestore write. Sample:")
        for r in records[:2]:
            print(f"    {r.id} [{r.category_hint}] Q={r.question[:45]!r} A={r.answer[:45]!r}")
        return 0

    asyncio.run(preseed(args.session, records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
