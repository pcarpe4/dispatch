from __future__ import annotations

from functools import lru_cache

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings


@lru_cache(maxsize=1)
def llm_client() -> OpenAI:
    s = settings()
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)


@lru_cache(maxsize=1)
def embed_client() -> OpenAI:
    s = settings()
    base = s.embed_base_url or s.llm_base_url
    key = s.embed_api_key or s.llm_api_key
    return OpenAI(base_url=base, api_key=key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def chat(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 8000,
    response_format: dict | None = None,
) -> str:
    s = settings()
    kwargs: dict = {
        "model": model or s.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    resp = llm_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    s = settings()
    name = model or s.embed_model or s.llm_model
    resp = embed_client().embeddings.create(model=name, input=texts)
    return [d.embedding for d in resp.data]
