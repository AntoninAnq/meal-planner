"""Entry point of the operator commands: `python -m app.admin ...`.

Run on the host, against the database, with no HTTP surface — see the package
docstring for why that is the point rather than a limitation.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence

from app.admin.actions import (
    UnknownHousehold,
    UnknownSubject,
    find,
    grant_operator,
    operators,
    restore,
    revoke,
    revoke_operator,
    set_limit,
    survey,
)
from app.config import get_settings
from app.db.session import get_session_factory
from app.domain.enums import OperatorLevel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admin",
        description="Operator commands: who may act on this instance, and how much they may spend.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="every household, ordered by recent model calls")

    locate = sub.add_parser(
        "find",
        help="the household behind a support code, as printed in its Réglages screen",
    )
    locate.add_argument("code", help="eight hex characters, e.g. 335C-58F8; dashes optional")

    for name, help_text in (
        ("revoke", "cut an identity off; it stays recognised and cannot re-register"),
        ("restore", "let a revoked identity back onto its household"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument(
            "subject",
            help="auth subject, prefixed by its mechanism — e.g. google:1178… . "
            "`list` prints them; there is no email stored to search by.",
        )

    limit = sub.add_parser(
        "limit",
        help="set a household's own ceiling on model calls, or clear it",
    )
    limit.add_argument("household_id")
    ops = sub.add_parser("operators", help="who may use the back office")
    ops.add_argument(
        "--grant",
        metavar="SUBJECT",
        help="give this identity the back office. The FIRST owner can only be "
        "created here: the interface that grants operators is itself behind the "
        "gate.",
    )
    ops.add_argument("--level", choices=["owner", "contributor"], default="owner")
    ops.add_argument("--revoke", metavar="SUBJECT", help="take the back office away")

    limit.add_argument(
        "value",
        help="a number of calls per window, or `default` to go back to the rate "
        "card. 0 stops generation while leaving existing weeks readable.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    with get_session_factory()() as db:
        try:
            if args.command in {"list", "find"}:
                if args.command == "find":
                    rows = find(db, args.code)
                    if not rows:
                        print(f"No household with support code {args.code}.", file=sys.stderr)
                        return 1
                else:
                    rows = survey(db, window_hours=settings.generation_window_hours)
                if not rows:
                    print("No household on this instance.")
                    return 0
                print(
                    f"{'code':10} {'household':38} {'name':22} {'mbr':>3} "
                    f"{'calls':>5} {'limit':>6}  identities"
                )
                for row in rows:
                    ceiling = (
                        "default" if row.limit_override is None else str(row.limit_override)
                    )
                    identities = ", ".join(row.subjects) or "—"
                    if row.revoked:
                        identities += f"  [revoked: {', '.join(row.revoked)}]"
                    print(
                        f"{row.code:10} {row.household_id!s:38} {row.name[:22]:22} "
                        f"{row.members:>3} {row.calls_in_window:>5} {ceiling:>6}  {identities}"
                    )
                print(
                    f"\nCalls counted over the last {settings.generation_window_hours} h. "
                    f"Rate card: {settings.generation_daily_limit}."
                )
                return 0

            if args.command == "operators":
                if args.grant:
                    grant_operator(db, args.grant, OperatorLevel(args.level))
                    print(f"{args.grant} is now {args.level}.")
                    return 0
                if args.revoke:
                    revoke_operator(db, args.revoke)
                    print(f"{args.revoke} no longer operates this instance.")
                    return 0
                rows = operators(db)
                if not rows:
                    print(
                        "Nobody operates this instance. Grant the first owner:\n"
                        "  python -m app.admin operators --grant google:… --level owner"
                    )
                    return 0
                for row in rows:
                    by = row.granted_by or "— (amorçage)"
                    print(f"{row.level.value:<12} {row.auth_subject:<40} par {by}")
                return 0

            if args.command == "revoke":
                revoke(db, args.subject)
                print(f"Revoked {args.subject}. It stays known, so it cannot re-register.")
                return 0

            if args.command == "restore":
                restore(db, args.subject)
                print(f"Restored {args.subject}.")
                return 0

            if args.command == "limit":
                value = None if args.value == "default" else int(args.value)
                set_limit(db, uuid.UUID(args.household_id), value)
                print(
                    f"{args.household_id} is now on "
                    + ("the rate card." if value is None else f"a ceiling of {value}.")
                )
                return 0

        except (UnknownSubject, UnknownHousehold) as unknown:
            print(f"Not found: {unknown}", file=sys.stderr)
            return 1
        except ValueError as bad:
            print(f"{bad}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
