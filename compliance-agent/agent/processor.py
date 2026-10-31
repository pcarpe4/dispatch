from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import audit, llm
from .config import agent_cfg, settings
from .formatter import get_formatter
from .loader import RawFile, load_dir


@dataclass
class RunResult:
    week_id: str
    output: dict[str, Any]
    output_path: Path
    run_id: str


def _build_user_prompt(week_id: str, files: list[RawFile]) -> str:
    sections = [f"Week ID: {week_id}", f"Total files: {len(files)}", ""]
    for rf in files:
        sections.append(f"--- FILE: {rf.path.name} (mime={rf.mime}) ---")
        sections.append(rf.text)
        sections.append("")
    sections.append(
        "Return ONLY a JSON object that matches the schema in the system prompt. "
        "No prose, no markdown fences."
    )
    return "\n".join(sections)


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # Strip ```json fences if the model added them despite instructions.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    return json.loads(raw)


def run(input_dir: Path | None = None, week_id: str | None = None) -> RunResult:
    s = settings()
    cfg = agent_cfg()
    in_dir = Path(input_dir or s.input_dir)
    week = week_id or _default_week_id()

    instructions = Path(s.instructions_path).read_text()
    instructions_hash = hashlib.sha256(instructions.encode()).hexdigest()

    files = load_dir(in_dir, max_chars=cfg.get("max_chars_per_file", 40000))
    raw_ids = audit.write_raw(week, files)

    user_prompt = _build_user_prompt(week, files)
    raw_completion = llm.chat(
        system=instructions,
        user=user_prompt,
        temperature=cfg.get("temperature", 0.1),
        max_tokens=cfg.get("max_output_tokens", 8000),
        response_format={"type": "json_object"},
    )
    output = _parse_json(raw_completion)
    output.setdefault("week_id", week)
    output.setdefault("rows", [])
    output.setdefault("warnings", [])

    fmt_name = cfg.get("output_format", "csv")
    fmt = get_formatter(fmt_name)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    template = cfg.get("output_filename_template", "compliance_{week_id}.{ext}")
    out_path = s.output_dir / template.format(week_id=week, ext=fmt.extension)
    fmt.write(output, out_path)

    run_id = audit.write_run(
        week_id=week,
        raw_ids=raw_ids,
        instructions_hash=instructions_hash,
        model=s.llm_model,
        output=output,
        output_file=str(out_path),
        output_format=fmt_name,
        warnings=output.get("warnings", []),
    )
    return RunResult(week_id=week, output=output, output_path=out_path, run_id=run_id)


def _default_week_id() -> str:
    from datetime import date

    iso = date.today().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
