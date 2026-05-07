from __future__ import annotations

import csv
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
from pypdf import PdfReader


@dataclass
class RawFile:
    path: Path
    mime: str
    text: str
    raw_bytes: bytes


# Pluggable parser registry. Map file suffix (lowercase, with dot) to parser.
Parser = Callable[[Path], str]
_PARSERS: dict[str, Parser] = {}


def register(suffix: str) -> Callable[[Parser], Parser]:
    def deco(fn: Parser) -> Parser:
        _PARSERS[suffix.lower()] = fn
        return fn
    return deco


@register(".txt")
@register(".md")
@register(".log")
def _parse_text(p: Path) -> str:
    return p.read_text(errors="replace")


@register(".csv")
def _parse_csv(p: Path) -> str:
    with p.open(newline="") as f:
        rows = list(csv.reader(f))
    return "\n".join([",".join(r) for r in rows])


@register(".json")
def _parse_json(p: Path) -> str:
    return json.dumps(json.loads(p.read_text()), indent=2)


@register(".xlsx")
@register(".xls")
def _parse_excel(p: Path) -> str:
    sheets = pd.read_excel(p, sheet_name=None, dtype=str).items()
    return "\n\n".join(f"# Sheet: {name}\n{df.to_csv(index=False)}" for name, df in sheets)


@register(".pdf")
def _parse_pdf(p: Path) -> str:
    reader = PdfReader(str(p))
    return "\n\n".join(
        f"[page {i + 1}]\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages)
    )


def load_file(path: Path, max_chars: int | None = None) -> RawFile:
    parser = _PARSERS.get(path.suffix.lower())
    text = parser(path) if parser else path.read_text(errors="replace")
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[TRUNCATED at {max_chars} chars]"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return RawFile(path=path, mime=mime, text=text, raw_bytes=path.read_bytes())


def load_dir(directory: Path, max_chars: int | None = None) -> list[RawFile]:
    if not directory.exists():
        raise FileNotFoundError(f"Input directory not found: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file())
    return [load_file(p, max_chars=max_chars) for p in files]
