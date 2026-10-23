#!/usr/bin/env python3
"""Build the feed page.

    python build.py                      # uses config.toml, writes site/index.html
    python build.py --config my.toml --out public

Pipeline: fetch sources -> rule ranking -> optional AI -> tiers -> page.
"""
from __future__ import annotations

import argparse
import logging
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from feed import ai, rank, render, sources

ROOT = Path(__file__).parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--config", default=ROOT / "config.toml", type=Path)
    parser.add_argument("--template", default=ROOT / "template.html", type=Path)
    parser.add_argument("--out", default=ROOT / "site", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    now = datetime.now(UTC)

    items, errors = sources.fetch_all(cfg.get("sources", []))
    if not items:
        logging.error("No items fetched; keeping the previous page live.")
        return 1

    items = rank.rank(items, cfg, now)
    ai_used = ai.rerank(items, cfg)
    rank.assign_tiers(items, cfg)

    out = render.render(items, errors, now, ai_used, args.template, args.out)
    logging.info("Wrote %s (%d items)", out, len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
