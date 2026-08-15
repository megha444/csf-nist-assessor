"""
Loaders for Sakina-authored (rubrics) and NIST-authored (implementation examples)
YAML content. Both live in-repo under `csf_specialists/`; regenerate rubrics via
`infra/build_govern_yaml.py` when Sakina updates the source spreadsheets.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

Function = Literal["govern", "identify", "protect", "detect", "respond", "recover"]

PACKAGE_ROOT = Path(__file__).resolve().parent
RUBRICS_DIR = PACKAGE_ROOT / "rubrics"
EXAMPLES_DIR = PACKAGE_ROOT / "implementation_examples"


# ---------------------------------------------------------------------------
# Dataclasses (immutable; safe to cache module-wide)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Category:
    """One CSF Category with its CMMI 1-5 rubric text (Sakina-authored)."""
    code: str                          # e.g. "GV.OC"
    name: str
    importance: int                    # 1-3 weight for roadmap ranking
    levels: dict[int, str]             # {1: "...", 2: "...", ..., 5: "..."}


@dataclass(frozen=True)
class FunctionRubric:
    """All Categories owned by a single CSF Function."""
    function: Function
    categories: dict[str, Category]    # keyed by Category code


@dataclass(frozen=True)
class SubcategoryExamples:
    """NIST's official implementation examples for one Subcategory."""
    subcategory_id: str                # e.g. "GV.OC-01"
    name: str                          # NIST-authored short description
    examples: tuple[str, ...]          # ordered "Ex1: ...", "Ex2: ...", etc.


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


@lru_cache
def load_rubric(function: Function) -> FunctionRubric:
    """Load `csf_specialists/rubrics/{function}.yaml`. Cached per Function."""
    path = RUBRICS_DIR / f"{function}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Rubric YAML missing for function={function!r} at {path}. "
            f"If this is a Sakina deliverable that hasn't landed yet, block on her."
        )
    raw = yaml.safe_load(path.read_text())
    if raw.get("function") != function:
        raise ValueError(f"{path}: file declares function={raw.get('function')!r}, expected {function!r}")

    cats: dict[str, Category] = {}
    for code, entry in raw.get("categories", {}).items():
        levels = {int(k): str(v) for k, v in entry.get("levels", {}).items()}
        if set(levels) != {1, 2, 3, 4, 5}:
            raise ValueError(f"{path}: Category {code} missing CMMI levels; got {sorted(levels)}")
        cats[code] = Category(
            code=code,
            name=str(entry["name"]),
            importance=int(entry.get("importance", 2)),
            levels=levels,
        )
    return FunctionRubric(function=function, categories=cats)


@lru_cache
def load_implementation_examples(function: Function) -> dict[str, SubcategoryExamples]:
    """
    Load `csf_specialists/implementation_examples/{function}.yaml`.
    Returns {subcategory_id: SubcategoryExamples}, ordered.
    """
    path = EXAMPLES_DIR / f"{function}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Implementation examples YAML missing at {path}")
    raw = yaml.safe_load(path.read_text())

    result: dict[str, SubcategoryExamples] = {}
    for sub_id, entry in raw.items():
        examples = tuple(str(e) for e in entry.get("examples", []))
        result[sub_id] = SubcategoryExamples(
            subcategory_id=sub_id,
            name=str(entry.get("name", "")),
            examples=examples,
        )
    return result


def examples_for_category(function: Function, category_code: str) -> list[SubcategoryExamples]:
    """All Subcategories whose id starts with `{category_code}-`. Ordered."""
    all_examples = load_implementation_examples(function)
    return [ex for sub_id, ex in all_examples.items() if sub_id.startswith(category_code + "-")]
