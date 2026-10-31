from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import processor

log = logging.getLogger("agent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compliance-agent")
    parser.add_argument("--input-dir", type=Path, default=None, help="Folder of raw weekly files")
    parser.add_argument("--week", default=None, help="Week id, e.g. 2026-W19. Defaults to ISO week")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    result = processor.run(input_dir=args.input_dir, week_id=args.week)
    log.info("week=%s rows=%d output=%s run_id=%s",
             result.week_id, len(result.output.get("rows", [])), result.output_path, result.run_id)
    if result.output.get("warnings"):
        for w in result.output["warnings"]:
            log.warning("warning: %s", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
