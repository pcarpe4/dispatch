import json
import os

from . import register


@register("stdout")
class StdoutSink:
    """Writes one JSON record per line. Handy for debugging and log shipping."""

    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, records):
        for r in records:
            print(json.dumps(r, default=str), flush=True)


@register("file")
class FileSink:
    """Writes <dir>/<export>.json per run (mount a PVC to keep them)."""

    def __init__(self, cfg):
        self.dir = cfg.get("path", "/data")
        os.makedirs(self.dir, exist_ok=True)

    def send(self, records):
        by_export = {}
        for r in records:
            by_export.setdefault(r["export"], []).append(r)
        for name, recs in by_export.items():
            with open(os.path.join(self.dir, f"{name}.json"), "w") as fh:
                json.dump(recs, fh, indent=2, default=str)
