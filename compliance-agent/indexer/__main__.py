from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from typing import Iterable

from agent import audit, llm
from agent.config import indexer_cfg, settings

from . import confluence

log = logging.getLogger("indexer")

VECTOR_COLLECTION = "vector_chunks"


def _chunk(text: str, chunk_chars: int, overlap: int) -> list[str]:
    if not text:
        return []
    out, i = [], 0
    while i < len(text):
        end = min(i + chunk_chars, len(text))
        out.append(text[i:end])
        if end == len(text):
            break
        i = end - overlap
    return out


def _embed_batched(texts: list[str], batch_size: int) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(llm.embed(texts[i : i + batch_size]))
    return out


def _vector_collection():
    return audit._db()[VECTOR_COLLECTION]


def _upsert(source: str, source_id: str, chunks: list[str], meta: dict) -> int:
    cfg = indexer_cfg()
    vectors = _embed_batched(chunks, cfg.get("batch_size", 32))
    coll = _vector_collection()
    # Replace prior chunks for this source_id atomically.
    coll.delete_many({"source": source, "source_id": source_id})
    docs = [
        {
            "source": source,
            "source_id": source_id,
            "chunk_index": i,
            "text": chunk,
            "embedding": vec,
            "meta": meta,
            "indexed_at": datetime.now(UTC),
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    if docs:
        coll.insert_many(docs)
    return len(docs)


def index_confluence(spaces: Iterable[str]) -> int:
    cfg = indexer_cfg()
    chunk_chars = cfg.get("chunk_chars", 1500)
    overlap = cfg.get("chunk_overlap", 200)
    total = 0
    for space in spaces:
        log.info("indexing confluence space=%s", space)
        for page in confluence.iter_space_pages(space):
            chunks = _chunk(page.text, chunk_chars, overlap)
            if not chunks:
                continue
            n = _upsert(
                source="confluence",
                source_id=page.page_id,
                chunks=chunks,
                meta={
                    "title": page.title,
                    "url": page.url,
                    "space": page.space,
                    "version": page.version,
                },
            )
            total += n
    return total


def index_audit() -> int:
    cfg = indexer_cfg()
    chunk_chars = cfg.get("chunk_chars", 1500)
    overlap = cfg.get("chunk_overlap", 200)
    total = 0
    for run in audit.run_collection().find({}):
        text_parts = [run.get("output", {}).get("summary", "")]
        for row in run.get("output", {}).get("rows", []):
            text_parts.append(
                f"[{row.get('id')}] cat={row.get('category')} owner={row.get('owner')} "
                f"status={row.get('status')} notes={row.get('notes')}"
            )
        text = "\n".join(p for p in text_parts if p)
        chunks = _chunk(text, chunk_chars, overlap)
        if not chunks:
            continue
        total += _upsert(
            source="audit_run",
            source_id=str(run["_id"]),
            chunks=chunks,
            meta={
                "week_id": run.get("week_id"),
                "title": f"Compliance run {run.get('week_id')}",
                "url": None,
            },
        )
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compliance-indexer")
    parser.add_argument(
        "--source",
        choices=["all", "confluence", "audit"],
        default="all",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    s = settings()
    n = 0
    if args.source in ("all", "confluence"):
        spaces = [x.strip() for x in s.confluence_spaces.split(",") if x.strip()]
        if spaces:
            n += index_confluence(spaces)
        else:
            log.info("no confluence spaces configured, skipping")
    if args.source in ("all", "audit"):
        n += index_audit()
    log.info("indexed %d chunks", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
