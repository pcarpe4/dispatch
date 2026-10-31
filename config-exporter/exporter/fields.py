"""Field-path extraction for Kubernetes objects.

Path syntax (dot-separated, JSONPath-lite):
  metadata.name                               plain keys
  spec.template.spec.containers[*].image      [*] fans out over a list
  spec.containers[0].image                    [N] picks one list item
  metadata.labels["app.kubernetes.io/name"]   ["..."] for keys containing dots
"""
import re

_TOKEN = re.compile(r'\["([^"]+)"\]|\[(\*|\d+)\]|([^.\[\]]+)')
_MISSING = object()


def parse_path(path):
    tokens = []
    for quoted, index, key in _TOKEN.findall(path):
        if quoted:
            tokens.append(("key", quoted))
        elif index == "*":
            tokens.append(("all", None))
        elif index:
            tokens.append(("idx", int(index)))
        else:
            tokens.append(("key", key))
    return tokens


def _walk(node, tokens):
    if not tokens:
        return node
    kind, arg = tokens[0]
    rest = tokens[1:]
    if kind == "key":
        if not isinstance(node, dict) or arg not in node:
            return _MISSING
        return _walk(node[arg], rest)
    if not isinstance(node, list):
        return _MISSING
    if kind == "idx":
        return _walk(node[arg], rest) if -len(node) <= arg < len(node) else _MISSING
    # "all": fan out, dropping items where the rest of the path is missing
    out = [_walk(item, rest) for item in node]
    return [v for v in out if v is not _MISSING]


def extract(obj, path, default=None):
    value = _walk(obj, parse_path(path))
    return default if value is _MISSING else value


def project(obj, fields):
    """Return {alias: value} for each field spec.

    A field spec is either a path string (alias = the path) or
    {"path": "...", "as": "alias"}.
    """
    result = {}
    for f in fields:
        if isinstance(f, str):
            result[f] = extract(obj, f)
        else:
            result[f.get("as", f["path"])] = extract(obj, f["path"])
    return result


def strip(obj, paths):
    """Remove noisy paths (e.g. metadata.managedFields) in place."""
    for path in paths:
        tokens = parse_path(path)
        parent = _walk(obj, tokens[:-1])
        kind, key = tokens[-1]
        if kind == "key" and isinstance(parent, dict):
            parent.pop(key, None)
    return obj
