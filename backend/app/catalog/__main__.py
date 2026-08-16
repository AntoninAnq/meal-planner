"""Entry point of the catalogue pipeline.

Three commands, and the split between them is not cosmetic:

* `ingest`  — fetch and extract. Talks to third-party sites (§11.4).
* `resolve` — match ingredient lines against the referential. Talks to nobody,
  and is **replayable**: a recipe ingested when the referential held 50 entries
  must gain its resolutions when it holds 350, without re-fetching anything.
* `review`  — put approximate matches in front of a human. I4: a trigram match
  is never applied on its own.

Keeping them separate is what makes the middle one replayable at all. Folding
resolution into ingestion would tie the quality of the catalogue to the moment a
page happened to be downloaded.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog",
        description="Catalogue collection pipeline (docs/ARCHITECTURE.md §7.5, §11.4, §11.5)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="fetch and extract one whitelisted source")
    ingest.add_argument("--source", required=True, help="key of a descriptor in the whitelist")
    ingest.add_argument(
        "--limit",
        type=int,
        help="stop after N pages. A ceiling also lives in the descriptor: a runaway "
        "loop must not be able to become an incident on someone else's site.",
    )
    ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="extract and report, write nothing",
    )

    resolve = sub.add_parser("resolve", help="match unresolved ingredient lines (idempotent)")
    resolve.add_argument(
        "--report",
        action="store_true",
        help="only print the distribution of unresolved raw_text, most frequent first — "
        "this is what says which referential entries to write next",
    )

    sub.add_parser("review", help="decide the approximate matches waiting (I4)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"`{args.command}` is not implemented yet.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
