from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent import audit, llm
from agent.config import indexer_cfg


@dataclass
class Hit:
    text: str
    score: float
    source: str
    meta: dict[str, Any]


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 6) -> list[Hit]: ...


class MongoVectorRetriever:
    """Mongo Atlas Vector Search backed retriever.

    Requires a vector index named per indexer.vector_index in settings.yaml,
    defined over `embedding` with the same dimensionality as the embed model.
    """

    def __init__(self, index_name: str | None = None) -> None:
        self.index_name = index_name or indexer_cfg().get("vector_index", "compliance_vector_idx")

    def search(self, query: str, top_k: int = 6) -> list[Hit]:
        vector = llm.embed([query])[0]
        coll = audit._db()["vector_chunks"]
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.index_name,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": max(top_k * 10, 50),
                    "limit": top_k,
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "text": 1,
                    "source": 1,
                    "meta": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        return [
            Hit(text=d["text"], score=d.get("score", 0.0), source=d["source"], meta=d.get("meta", {}))
            for d in coll.aggregate(pipeline)
        ]


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = MongoVectorRetriever()
    return _retriever


def set_retriever(r: Retriever) -> None:
    """Swap the retriever, e.g. in tests or to add a hybrid implementation."""
    global _retriever
    _retriever = r
