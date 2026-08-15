"""
Idempotent Qdrant collection setup for CSF Assessor Fleet.

Creates the `csf_chunks` collection (or whatever QDRANT_COLLECTION is set to)
with vector config matching text-embedding-004 (768-dim, cosine), plus
payload indexes for the fields we filter/search by.

Safe to re-run: if the collection already exists, it is left alone unless
`--recreate` is passed. Payload indexes are created only if missing.

Usage:
    poetry run python infra/qdrant_setup.py
    poetry run python infra/qdrant_setup.py --recreate   # DANGER: drops existing collection
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None  # empty string → None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "csf_chunks")

EMBEDDING_DIM = 768  # text-embedding-004 output dimension

PAYLOAD_INDEXES: list[tuple[str, qmodels.PayloadSchemaType]] = [
    ("org_id", qmodels.PayloadSchemaType.KEYWORD),
    ("session_id", qmodels.PayloadSchemaType.KEYWORD),
    ("doc_id", qmodels.PayloadSchemaType.KEYWORD),
    ("chunk_id", qmodels.PayloadSchemaType.KEYWORD),
    ("doc_type", qmodels.PayloadSchemaType.KEYWORD),
    ("candidate_categories", qmodels.PayloadSchemaType.KEYWORD),
    ("page_start", qmodels.PayloadSchemaType.INTEGER),
]


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, check_compatibility=False)


def collection_exists(client: QdrantClient, name: str) -> bool:
    try:
        client.get_collection(name)
        return True
    except (UnexpectedResponse, ValueError):
        return False


def create_collection(client: QdrantClient, name: str) -> None:
    client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(
            size=EMBEDDING_DIM,
            distance=qmodels.Distance.COSINE,
        ),
    )
    print(f"[create] collection '{name}' created ({EMBEDDING_DIM}-dim, cosine)")


def ensure_payload_indexes(client: QdrantClient, name: str) -> None:
    info = client.get_collection(name)
    existing = set(info.payload_schema.keys()) if info.payload_schema else set()
    for field_name, schema_type in PAYLOAD_INDEXES:
        if field_name in existing:
            print(f"[skip]   payload index '{field_name}' already present")
            continue
        client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=schema_type,
        )
        print(f"[create] payload index '{field_name}' ({schema_type.value})")


def smoke_test(client: QdrantClient, name: str) -> None:
    """Upsert one fake point, query for it, delete it."""
    from qdrant_client.http.models import PointStruct

    test_id = str(uuid.uuid4())
    test_vec = [0.01] * EMBEDDING_DIM

    client.upsert(
        collection_name=name,
        points=[
            PointStruct(
                id=test_id,
                vector=test_vec,
                payload={
                    "session_id": "smoke",
                    "doc_id": "smoke",
                    "chunk_id": test_id,
                    "doc_type": "Other",
                    "candidate_categories": ["GV.OC"],
                    "page_start": 1,
                    "page_end": 1,
                    "section_title": "smoke test",
                    "text": "smoke test chunk",
                },
            )
        ],
    )

    hits = client.query_points(
        collection_name=name,
        query=test_vec,
        query_filter=qmodels.Filter(
            must=[qmodels.FieldCondition(key="session_id", match=qmodels.MatchValue(value="smoke"))]
        ),
        limit=1,
    ).points

    assert hits and hits[0].id == test_id, f"smoke test query failed: {hits}"
    print(f"[test]   upsert + filtered query round-trip OK (id={test_id[:8]}...)")

    client.delete(collection_name=name, points_selector=qmodels.PointIdsList(points=[test_id]))
    print(f"[test]   cleanup point deleted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true", help="Drop existing collection before creating")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip the upsert/query round-trip test")
    args = parser.parse_args()

    print(f"[env]    QDRANT_URL={QDRANT_URL}")
    print(f"[env]    QDRANT_COLLECTION={COLLECTION}")
    print(f"[env]    QDRANT_API_KEY={'<set>' if QDRANT_API_KEY else '<empty>'}")

    client = get_client()

    if args.recreate and collection_exists(client, COLLECTION):
        print(f"[recreate] dropping existing '{COLLECTION}'")
        client.delete_collection(COLLECTION)

    if collection_exists(client, COLLECTION):
        print(f"[skip]   collection '{COLLECTION}' already exists")
    else:
        create_collection(client, COLLECTION)

    ensure_payload_indexes(client, COLLECTION)

    if not args.skip_smoke:
        smoke_test(client, COLLECTION)

    print("[done]   Qdrant is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
