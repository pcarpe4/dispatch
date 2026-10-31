from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from .config import settings
from .loader import RawFile

RAW_COLLECTION = "raw_files"
RUN_COLLECTION = "processed_runs"


@lru_cache(maxsize=1)
def _client() -> MongoClient:
    return MongoClient(settings().mongo_uri)


def _db():
    return _client()[settings().mongo_db]


def raw_collection() -> Collection:
    return _db()[RAW_COLLECTION]


def run_collection() -> Collection:
    return _db()[RUN_COLLECTION]


def write_raw(week_id: str, files: list[RawFile]) -> list[str]:
    coll = raw_collection()
    ids: list[str] = []
    for rf in files:
        digest = hashlib.sha256(rf.raw_bytes).hexdigest()
        doc = {
            "_id": f"{week_id}:{rf.path.name}:{digest[:12]}",
            "week_id": week_id,
            "filename": rf.path.name,
            "mime": rf.mime,
            "sha256": digest,
            "bytes_len": len(rf.raw_bytes),
            "text_preview": rf.text[:2000],
            "ingested_at": datetime.now(UTC),
        }
        coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        ids.append(doc["_id"])
    return ids


def write_run(
    *,
    week_id: str,
    raw_ids: list[str],
    instructions_hash: str,
    model: str,
    output: dict[str, Any],
    output_file: str,
    output_format: str,
    warnings: list[str],
) -> str:
    coll = run_collection()
    doc = {
        "_id": f"{week_id}:{datetime.now(UTC).isoformat()}",
        "week_id": week_id,
        "raw_ids": raw_ids,
        "instructions_hash": instructions_hash,
        "model": model,
        "output": output,
        "output_file": output_file,
        "output_format": output_format,
        "warnings": warnings,
        "completed_at": datetime.now(UTC),
    }
    coll.insert_one(doc)
    return doc["_id"]
