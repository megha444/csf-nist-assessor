"""
Extract `Ref Docs/Document Checklist.xlsx` into a versioned evidence
taxonomy: which real documents should cover which CSF Category, at the
granularity her checklist actually gives (per-Subcategory, rolled up to
Category since that's the level specialist agents retrieve at).

Reads:
  Ref Docs/Document Checklist.xlsx, sheet "Document Checklist"
    columns: Document / Evidence Source | # Subcategories Covered |
             Functions Touched | Drafting Priority | Subcategory IDs Covered
    plus a trailing "Subcategories with NO identified document" block.

Writes:
  csf_specialists/evidence_taxonomy.yaml
    categories: {category_id: [normalized document titles...]}
    questionnaire_only_subcategories: [subcategory_id...].

Document titles are normalized (lowercase, punctuation stripped, whitespace
collapsed) so they can be matched against real uploaded filenames at retrieval
time without needing an exact string match — "Logging & Monitoring Standard"
and "17. Logging_Monitoring_Standard.docx" both normalize to the same key.

Usage:
  poetry run python infra/build_evidence_taxonomy.py

Idempotent — safe to re-run
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_XLSX = ROOT / "Ref Docs" / "Document Checklist.xlsx"
OUT_PATH = ROOT / "csf_specialists" / "evidence_taxonomy.yaml"

TITLE_ALIASES: dict[str, str] = {
    "info sec policy": "information security policy",
    "board risk committee papers minutes": "board risk committee minutes extract",
}


def normalize_title(title: str) -> str:
    """Normalize both checklist titles ("Post-Incident Review") and real
    filenames ("4. Post_Incident_Review.docx") to the same matching key.
    Word-separator punctuation (-, _, /, &) becomes a space, not nothing —
    stripping it outright would collapse "Post-Incident" into "PostIncident"
    with no space, which then fails to match "Post_Incident" (same bug, same
    fix needed for both)."""
    t = title.lower()
    t = re.sub(r"[-_/&]", " ", t)
    t = re.sub(r"[^a-z0-9\s]", "", t)  # drop remaining punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return TITLE_ALIASES.get(t, t)


def main() -> int:
    if not CHECKLIST_XLSX.exists():
        print(f"[error] {CHECKLIST_XLSX} not found", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(CHECKLIST_XLSX, data_only=True)
    ws = wb["Document Checklist"]
    rows = [r for r in ws.iter_rows(
        values_only=True) if any(c is not None for c in r)]

    categories: dict[str, set[str]] = {}
    questionnaire_only: list[str] = []
    n_documents = 0
    mode = "documents"

    for row in rows[1:]:  # skip header
        first_cell = row[0]
        if first_cell is None:
            continue
        if isinstance(first_cell, str) and first_cell.startswith("Subcategories with NO identified document"):
            mode = "gaps"
            continue
        if isinstance(first_cell, str) and first_cell == "Subcategory ID":
            continue  # the gaps block's own sub-header row

        if mode == "documents":
            title, _n_subs, _functions, _priority, sub_ids_cell = row[:5]
            if not sub_ids_cell:
                continue
            n_documents += 1
            normalized = normalize_title(str(title))
            for sub_id in str(sub_ids_cell).split(","):
                sub_id = sub_id.strip()
                if not sub_id:
                    continue
                cat_id = sub_id.split("-")[0]
                categories.setdefault(cat_id, set()).add(normalized)
        elif mode == "gaps":
            sub_id = row[0]
            if isinstance(sub_id, str) and re.match(r"^[A-Z]{2}\.[A-Z]{2}-\d+$", sub_id):
                questionnaire_only.append(sub_id)

    if not categories:
        print(
            "[error] no document rows parsed — checklist format may have changed", file=sys.stderr)
        return 1

    data = {
        "categories": {cat: sorted(titles) for cat, titles in sorted(categories.items())},
        "questionnaire_only_subcategories": sorted(questionnaire_only),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True,
                       width=100, default_flow_style=False)

    print(f"parsed {n_documents} documents across {len(categories)} Categories")
    print(f"questionnaire-only Subcategories: {questionnaire_only}")
    print(
        f"wrote {OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
