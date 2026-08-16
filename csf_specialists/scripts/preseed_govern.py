"""
Phase E3 — load sample Govern Q&A into a session's `answers/` subcollection.

Reads `csf_specialists/sample_data/northwind_preseed_govern.json` (or any file
matching the same `PreseedRecord` shape), validates every record, and writes
each one to `sessions/{session_id}/answers/{id}` so `SpecialistAgent._fetch_answers`
picks it up on the next `score_category` call. Also flips `preseed_loaded=True`
on the session document.

Idempotent — record ids are stable, so re-running overwrites the same docs
rather than duplicating them.

Usage:
  poetry run python csf_specialists/scripts/preseed_govern.py --session <session_id>
  poetry run python csf_specialists/scripts/preseed_govern.py --session <session_id> --dry-run
  poetry run python csf_specialists/scripts/preseed_govern.py --session <session_id> \\
      --file csf_specialists/sample_data/govern_questions.json  # any PreseedRecord-shaped file
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    # Lets this script run as `python csf_specialists/scripts/preseed_govern.py`
    # (script dir on sys.path[0], not repo root) as well as `python -m ...`.
    sys.path.insert(0, str(REPO_ROOT))

from google.cloud.firestore import AsyncClient
from pydantic import ValidationError

from csf_gateway.app.config import get_settings
from csf_gateway.app.schema import PreseedRecord

DEFAULT_FILE = REPO_ROOT / "csf_specialists" / "sample_data" / "northwind_preseed_govern.json"


def load_records(path: Path) -> list[PreseedRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records: list[PreseedRecord] = []
    for i, entry in enumerate(raw):
        try:
            records.append(PreseedRecord.model_validate(entry))
        except ValidationError as e:
            print(f"[error] {path.name}[{i}] (id={entry.get('id', '?')!r}) failed validation:\n{e}", file=sys.stderr)
            raise SystemExit(1)
    return records


async def preseed(session_id: str, records: list[PreseedRecord]) -> None:
    s = get_settings()
    client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)

    session_ref = client.collection("sessions").document(session_id)
    snap = await session_ref.get()
    if not snap.exists:
        raise SystemExit(
            f"[error] session {session_id!r} not found. Create it first via "
            f"POST /sessions before preseeding answers."
        )

    answers_ref = session_ref.collection("answers")
    batch = client.batch()
    now = datetime.now(timezone.utc)
    for record in records:
        payload = record.model_dump()
        payload["asked_at"] = now
        batch.set(answers_ref.document(record.id), payload)
    await batch.commit()

    await session_ref.update({"preseed_loaded": True})
    print(f"wrote {len(records)} answers → sessions/{session_id}/answers/*")
    print(f"sessions/{session_id}.preseed_loaded = True")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="session_id to preseed (must already exist)")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="PreseedRecord-shaped JSON file")
    parser.add_argument("--dry-run", action="store_true", help="validate + summarize, skip the Firestore write")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"[error] {args.file} not found", file=sys.stderr)
        return 1

    records = load_records(args.file)
    by_function = Counter(r.function for r in records)
    by_category = Counter(r.category_hint.split("-")[0] for r in records)
    print(f"loaded {len(records)} valid records from {args.file}")
    print(f"  by function: {dict(by_function)}")
    print(f"  by category: {dict(sorted(by_category.items()))}")

    if args.dry_run:
        print("[dry-run] skipping Firestore write")
        return 0

    asyncio.run(preseed(args.session, records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
