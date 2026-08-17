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

    ingest.add_argument(
        "--purge-cache",
        action="store_true",
        help="empty the campaign cache first, validators included",
    )
    ingest.add_argument(
        "--keep-cache",
        action="store_true",
        help="keep the fetched pages after the campaign. For working on the "
        "extractor, and for that only: the cache is a campaign artefact, not an "
        "archive of anyone's pages (I9).",
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


def _ingest(args) -> int:
    from app.catalog.descriptors import DescriptorError, load_sources
    from app.catalog.fetching import HttpxTransport, PoliteFetcher, ResponseCache
    from app.catalog.ingest import cache_directory, run_campaign
    from app.config import get_settings
    from app.db.session import get_session_factory

    settings = get_settings()
    try:
        sources = load_sources()
    except DescriptorError as exc:
        print(exc, file=sys.stderr)
        return 2

    source = sources.get(args.source)
    if source is None:
        print(
            f"unknown source {args.source!r}. Known: {', '.join(sorted(sources))}",
            file=sys.stderr,
        )
        return 2
    if not source.enabled:
        print(f"source {source.code!r} is disabled in the whitelist", file=sys.stderr)
        return 2

    cache = ResponseCache(
        cache_directory(settings.catalog_cache_dir), settings.catalog_cache_ttl_seconds
    )
    if args.purge_cache:
        print(f"cache purgé : {cache.purge()} entrées")

    transport = HttpxTransport()
    fetcher = PoliteFetcher(
        source=source,
        transport=transport,
        cache=cache,
        timeout=settings.catalog_request_timeout_seconds,
    )

    # Announced before the first request, because the pace is the thing someone
    # reading this output wants to be able to object to.
    print(
        f"campagne {source.code} · {source.request_interval_seconds}s entre requêtes, "
        f"une à la fois, plafond {source.max_pages_per_campaign} pages"
        + (" · DRY RUN, rien ne sera écrit" if args.dry_run else "")
    )

    try:
        with get_session_factory()() as db:
            report = run_campaign(
                db, source=source, fetcher=fetcher, limit=args.limit, dry_run=args.dry_run
            )
    finally:
        transport.close()

    print(report.render())

    # End of campaign: the pages go, the validators stay. Nothing of anyone's
    # content survives, and the next campaign still costs them almost nothing
    # because their own ETags answer it with a 304 (I9, §11.4).
    if not args.keep_cache:
        entries, freed = cache.shed_bodies()
        print(f"cache             {entries} pages effacées, {freed / 1e9:.2f} Go libérés, "
              "validateurs conservés")

    return 1 if report.abandoned else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ingest":
        return _ingest(args)
    print(f"`{args.command}` is not implemented yet.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
