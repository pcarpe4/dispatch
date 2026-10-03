"""Loads exporter config and expands ${ENV_VAR} references (for secrets)."""
import os
import re

import yaml

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

DEFAULT_STRIP = ["metadata.managedFields"]


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load(path):
    with open(path) as fh:
        cfg = _expand(yaml.safe_load(fh) or {})
    cfg.setdefault("exports", [])
    cfg.setdefault("sinks", [{"name": "stdout", "type": "stdout"}])
    cfg.setdefault("defaults", {})
    cfg["defaults"].setdefault("strip", DEFAULT_STRIP)
    sink_names = {s["name"] for s in cfg["sinks"]}
    seen = set()
    for exp in cfg["exports"]:
        for key in ("name", "apiVersion", "kind"):
            if key not in exp:
                raise ValueError(f"export {exp!r} is missing required key '{key}'")
        if exp["name"] in seen:
            raise ValueError(f"duplicate export name '{exp['name']}'")
        seen.add(exp["name"])
        unknown = set(exp.get("sinks") or []) - sink_names
        if unknown:
            raise ValueError(f"export '{exp['name']}' references unknown sinks {sorted(unknown)}")
    return cfg
