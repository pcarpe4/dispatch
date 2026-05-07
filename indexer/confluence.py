from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

import httpx

from agent.config import settings


@dataclass
class ConfluencePage:
    page_id: str
    title: str
    space: str
    url: str
    text: str
    version: int


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


def iter_space_pages(space: str, page_size: int = 50) -> Iterator[ConfluencePage]:
    s = settings()
    if not (s.confluence_base_url and s.confluence_user and s.confluence_api_token):
        raise RuntimeError("Confluence credentials not configured")

    auth = (s.confluence_user, s.confluence_api_token)
    base = s.confluence_base_url.rstrip("/")
    start = 0
    with httpx.Client(auth=auth, timeout=30.0) as client:
        while True:
            resp = client.get(
                f"{base}/rest/api/content",
                params={
                    "spaceKey": space,
                    "type": "page",
                    "expand": "body.storage,version",
                    "limit": page_size,
                    "start": start,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return
            for r in results:
                body = r.get("body", {}).get("storage", {}).get("value", "")
                yield ConfluencePage(
                    page_id=r["id"],
                    title=r.get("title", ""),
                    space=space,
                    url=f"{base}{r.get('_links', {}).get('webui', '')}",
                    text=_strip_html(body),
                    version=r.get("version", {}).get("number", 0),
                )
            if data.get("size", 0) < page_size:
                return
            start += page_size
