from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import llm
from agent.config import chatbot_cfg, settings

from .retriever import Hit, get_retriever

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Compliance Chatbot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str
    top_k: int | None = None


class Source(BaseModel):
    source: str
    title: str | None = None
    url: str | None = None
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]


def _format_context(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        title = h.meta.get("title") or h.source
        url = h.meta.get("url")
        header = f"[{i}] {title}" + (f" — {url}" if url else "")
        blocks.append(f"{header}\n{h.text}")
    return "\n\n".join(blocks)


@app.get("/")
def index() -> Any:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    cfg = chatbot_cfg()
    top_k = req.top_k or cfg.get("top_k", 6)
    hits = get_retriever().search(req.message, top_k=top_k)

    system = cfg.get("system_prompt", "Answer using only the provided context.")
    user = f"Context:\n{_format_context(hits)}\n\nQuestion: {req.message}"
    answer = llm.chat(system=system, user=user, temperature=0.2, max_tokens=1500)

    sources = [
        Source(
            source=h.source,
            title=h.meta.get("title"),
            url=h.meta.get("url"),
            score=h.score,
        )
        for h in hits
    ]
    return ChatResponse(answer=answer, sources=sources)


def run() -> None:
    import uvicorn

    s = settings()
    uvicorn.run("chatbot.app:app", host=s.chat_host, port=s.chat_port, reload=False)


if __name__ == "__main__":
    run()
