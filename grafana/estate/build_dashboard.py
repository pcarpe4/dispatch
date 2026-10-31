#!/usr/bin/env python3
"""
Assemble the Estate Explorer dashboard JSON.

The HTML Graphics panel keeps its HTML, CSS and JavaScript as real files under
panel/ (readable, diffable, syntax-checked by CI). dashboard.src.json refers to
them with {"$file": "panel/estate-graph.js"} placeholders; this script inlines
them and writes the importable dashboard to grafana/dashboards/estate/.

    python3 grafana/estate/build_dashboard.py          # (re)build
    python3 grafana/estate/build_dashboard.py --check  # fail if the committed JSON is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "dashboard.src.json"
OUT = HERE.parent / "dashboards" / "estate" / "estate-explorer.json"


def inline(value, base: Path):
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            return (base / value["$file"]).read_text()
        return {k: inline(v, base) for k, v in value.items()}
    if isinstance(value, list):
        return [inline(v, base) for v in value]
    return value


def build() -> str:
    dashboard = inline(json.loads(SRC.read_text()), HERE)
    return json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify the output file is up to date instead of writing it")
    args = ap.parse_args()
    text = build()
    rel = OUT.relative_to(HERE.parent.parent)
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"error: {rel} is stale; run python3 grafana/estate/build_dashboard.py", file=sys.stderr)
            return 1
        print(f"{rel} is up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {rel} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
