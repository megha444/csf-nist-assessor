"""
Golden-set eval — diff our agents' scores against the expert golden set.

Compares a completed assessment run (Firestore `sessions/{sid}/runs/{rid}`) against
Sakina's expert golden set (`Ref Docs/Golden Set.xlsx`) at all three levels our
pipeline produces, and reports real accuracy numbers for the 40% Innovation/Utility
bucket:

  1. Subcategory CMMI — exact-match %, within-±1 %, mean-abs-error (our per-subcategory
     `cmmi_level` vs the golden per-subcategory CMMI). The tightest, fairest comparison.
  2. Category CMMI — our category `cmmi_level` vs the golden Category Avg CMMI (MAE,
     within-0.5).
  3. Function / Tier — our rolled-up Tier vs the golden Rolled-Up Tier (match %).
  4. Evidence-doc precision (bonus) — did our `evidence_citations` cite the golden
     "Primary Evidence Document" for each category? (fuzzy title match).

Only compares what the run actually scored (partial runs are fine — coverage is
reported). Read-only: never writes anything.

Usage:
  poetry run python -m csf_specialists.scripts.eval_golden --session <sid> --run <rid>
  # optional: --golden "Ref Docs/Golden Set.xlsx"  --top 15  --project csf-assessor-hackathon
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import openpyxl
from google.cloud import firestore

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = REPO_ROOT / "Ref Docs" / "Golden Set.xlsx"


# ---------- golden set ----------
def _sheet_rows(wb, name):
    ws = wb[name]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None and str(c).strip() for c in r)]
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    def col(row, key):
        i = idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    return rows[1:], col


def _tier_num(text) -> int | None:
    if text is None:
        return None
    m = re.search(r"(\d+)", str(text))
    return int(m.group(1)) if m else None


def load_golden(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    sub, cat, fn = {}, {}, {}

    rows, col = _sheet_rows(wb, "Subcategory Scores")
    for row in rows:
        sid = col(row, "Subcategory ID")
        cmmi = col(row, "CMMI Score (1-5)")
        if not sid or cmmi is None:
            continue
        sub[str(sid).strip().upper()] = {
            "cmmi": float(cmmi),
            "evidence": (col(row, "Primary Evidence Document") or ""),
            "category": str(col(row, "Category ID") or "").strip().upper(),
            "function": str(col(row, "Function") or "").strip().lower(),
        }

    rows, col = _sheet_rows(wb, "Category Rollup")
    for row in rows:
        cid = col(row, "Category ID")
        avg = col(row, "Category Avg CMMI (formula)")
        if cid and avg is not None:
            cat[str(cid).strip().upper()] = float(avg)

    rows, col = _sheet_rows(wb, "Function Summary (Tier Rollup)")
    for row in rows:
        f = col(row, "CSF Function")
        tier = _tier_num(col(row, "Rolled-Up CSF Tier (formula)"))
        if f and tier is not None:
            fn[str(f).strip().lower()] = tier
    return sub, cat, fn


# ---------- our run ----------
def load_run(db, sid: str, rid: str):
    runref = db.collection("sessions").document(sid).collection("runs").document(rid)
    our_sub, our_cat, our_cites = {}, {}, defaultdict(list)
    for s in runref.collection("scores").stream():
        d = s.to_dict() or {}
        cid = str(d.get("category_id") or s.id).strip().upper()
        if d.get("cmmi_level") is not None:
            our_cat[cid] = float(d["cmmi_level"])
        for sub in d.get("subcategory_scores") or []:
            ssid = str(sub.get("subcategory_id") or "").strip().upper()
            if ssid and sub.get("cmmi_level") is not None:
                our_sub[ssid] = float(sub["cmmi_level"])
        for c in d.get("evidence_citations") or []:
            if c.get("doc_title"):
                our_cites[cid].append(str(c["doc_title"]))
    our_tier = {}
    for t in runref.collection("tiers").stream():
        d = t.to_dict() or {}
        f = str(d.get("function") or t.id).strip().lower()
        if d.get("tier") is not None:
            our_tier[f] = int(d["tier"])
    return our_sub, our_cat, our_cites, our_tier


# ---------- helpers ----------
def _norm(s: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split() if len(w) > 2}


def _title_matches(golden_doc: str, cited_titles: list[str]) -> bool:
    """Fuzzy: golden evidence doc considered 'cited' if a citation shares a
    substantial token overlap (Jaccard>=0.5) or is a normalized substring."""
    g = _norm(golden_doc)
    if not g:
        return False
    for t in cited_titles:
        c = _norm(t)
        if not c:
            continue
        inter = len(g & c)
        if inter and (inter / min(len(g), len(c)) >= 0.5):
            return True
    return False


def pct(n, d):
    return f"{100*n/d:.1f}%" if d else "n/a"


# ---------- eval ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    ap.add_argument("--project", default="csf-assessor-hackathon")
    ap.add_argument("--top", type=int, default=15, help="how many biggest disagreements to list")
    args = ap.parse_args()

    g_sub, g_cat, g_fn = load_golden(Path(args.golden))
    db = firestore.Client(project=args.project)
    o_sub, o_cat, o_cites, o_tier = load_run(db, args.session, args.run)

    print("=" * 72)
    print(f"GOLDEN-SET EVAL   session={args.session[:12]}  run={args.run[:12]}")
    print(f"golden={args.golden}")
    print("=" * 72)
    print(f"coverage: golden has {len(g_sub)} subcats / {len(g_cat)} cats / {len(g_fn)} functions; "
          f"our run scored {len(o_sub)} subcats / {len(o_cat)} cats / {len(o_tier)} functions")

    # 1. Subcategory
    matched = sorted(set(g_sub) & set(o_sub))
    exact = sum(1 for s in matched if round(g_sub[s]["cmmi"]) == round(o_sub[s]))
    within1 = sum(1 for s in matched if abs(g_sub[s]["cmmi"] - o_sub[s]) <= 1.0)
    mae = sum(abs(g_sub[s]["cmmi"] - o_sub[s]) for s in matched) / len(matched) if matched else 0
    print("\n── 1. SUBCATEGORY CMMI (our per-subcat vs golden) ──")
    print(f"   compared: {len(matched)}   exact: {pct(exact,len(matched))}   "
          f"within ±1: {pct(within1,len(matched))}   MAE: {mae:.2f}")

    # 2. Category
    cmatched = sorted(set(g_cat) & set(o_cat))
    cmae = sum(abs(g_cat[c] - o_cat[c]) for c in cmatched) / len(cmatched) if cmatched else 0
    chalf = sum(1 for c in cmatched if abs(g_cat[c] - o_cat[c]) <= 0.5)
    print("\n── 2. CATEGORY CMMI (our category cmmi vs golden avg) ──")
    print(f"   compared: {len(cmatched)}   within 0.5: {pct(chalf,len(cmatched))}   MAE: {cmae:.2f}")

    # 3. Tier
    tmatched = sorted(set(g_fn) & set(o_tier))
    tier_ok = sum(1 for f in tmatched if g_fn[f] == o_tier[f])
    print("\n── 3. FUNCTION / TIER (our tier vs golden tier) ──")
    print(f"   compared: {len(tmatched)}   tier match: {pct(tier_ok,len(tmatched))}")
    for f in tmatched:
        mark = "✓" if g_fn[f] == o_tier[f] else "✗"
        print(f"     {mark} {f:9} ours=Tier {o_tier[f]}  golden=Tier {g_fn[f]}")

    # 4. Evidence-doc precision
    ev_total = ev_hit = 0
    for cid in set(g_cat) & set(o_cat):
        golden_docs = {g_sub[s]["evidence"] for s in g_sub if g_sub[s]["category"] == cid and g_sub[s]["evidence"]}
        cited = o_cites.get(cid, [])
        for gd in golden_docs:
            ev_total += 1
            if _title_matches(gd, cited):
                ev_hit += 1
    print("\n── 4. EVIDENCE-DOC PRECISION (did we cite the golden primary evidence?) ──")
    print(f"   golden evidence docs (in scored cats): {ev_total}   cited by us: {pct(ev_hit,ev_total)}")

    # Per-function breakdown
    print("\n── PER-FUNCTION (subcategory agreement) ──")
    by_fn = defaultdict(list)
    for s in matched:
        by_fn[g_sub[s]["function"]].append(s)
    print(f"   {'function':10} {'n':>3} {'exact':>7} {'±1':>7} {'tier':>12}")
    for f in sorted(by_fn):
        ss = by_fn[f]
        ex = sum(1 for s in ss if round(g_sub[s]["cmmi"]) == round(o_sub[s]))
        w1 = sum(1 for s in ss if abs(g_sub[s]["cmmi"] - o_sub[s]) <= 1.0)
        tinfo = f"{o_tier.get(f,'-')}/{g_fn.get(f,'-')}" if f in o_tier else "-"
        print(f"   {f:10} {len(ss):>3} {pct(ex,len(ss)):>7} {pct(w1,len(ss)):>7} {tinfo:>12}")

    # Biggest disagreements (spot-check these)
    diffs = sorted(matched, key=lambda s: abs(g_sub[s]["cmmi"] - o_sub[s]), reverse=True)
    diffs = [s for s in diffs if abs(g_sub[s]["cmmi"] - o_sub[s]) > 0][: args.top]
    print(f"\n── TOP {len(diffs)} DISAGREEMENTS (spot-check: are we or the expert right?) ──")
    print(f"   {'subcategory':14} {'ours':>5} {'golden':>7} {'Δ':>5}")
    for s in diffs:
        delta = o_sub[s] - g_sub[s]["cmmi"]
        print(f"   {s:14} {o_sub[s]:>5.0f} {g_sub[s]['cmmi']:>7.0f} {delta:>+5.0f}")


if __name__ == "__main__":
    main()
