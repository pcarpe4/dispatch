from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class Formatter(Protocol):
    extension: str

    def write(self, output: dict[str, Any], dest: Path) -> Path: ...


class CSVFormatter:
    extension = "csv"

    def write(self, output: dict[str, Any], dest: Path) -> Path:
        rows = output.get("rows", [])
        df = pd.DataFrame(rows)
        df.to_csv(dest, index=False)
        return dest


class XLSXFormatter:
    extension = "xlsx"

    def write(self, output: dict[str, Any], dest: Path) -> Path:
        with pd.ExcelWriter(dest, engine="openpyxl") as writer:
            pd.DataFrame(output.get("rows", [])).to_excel(writer, sheet_name="rows", index=False)
            meta = {
                "week_id": output.get("week_id"),
                "summary": output.get("summary"),
                "warnings": "\n".join(output.get("warnings", [])),
            }
            pd.DataFrame([meta]).to_excel(writer, sheet_name="meta", index=False)
        return dest


class JSONFormatter:
    extension = "json"

    def write(self, output: dict[str, Any], dest: Path) -> Path:
        dest.write_text(json.dumps(output, indent=2, default=str))
        return dest


_REGISTRY: dict[str, Formatter] = {
    "csv": CSVFormatter(),
    "xlsx": XLSXFormatter(),
    "json": JSONFormatter(),
}


def get_formatter(name: str) -> Formatter:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown formatter '{name}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def register_formatter(name: str, fmt: Formatter) -> None:
    _REGISTRY[name] = fmt
