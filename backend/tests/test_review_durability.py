"""The confirmations file is the durable record; the database is derived.

An hour of human judgement is the one part of this pipeline no machine can
reproduce. Everything here protects the moment it gets written.
"""

from __future__ import annotations

import pathlib

import pytest

from app.catalog.review import ReadOnlyConfirmations, _refuse_if_unwritable


def test_an_unwritable_file_stops_the_review_before_it_starts(tmp_path) -> None:
    """Found in use, and it left the two records disagreeing.

    The `api` service mounts `db/` read-only and only `catalog` mounts it
    writable. Running the review on the wrong one committed twenty-two
    confirmations to the database and then failed on the file — entries
    confirmed in one place and absent from the other, which is precisely the
    drift the file exists to prevent.

    Refusing up front is what makes the partial state impossible; the message
    names the right command, because a `Read-only file system` traceback sends
    someone looking at permissions instead of at their compose service.
    """
    blocked = pathlib.Path(tmp_path) / "a-file" / "confirmations.yaml"
    blocked.parent.write_text("I am a file, not a directory", encoding="utf-8")

    with pytest.raises(ReadOnlyConfirmations, match="catalog review"):
        _refuse_if_unwritable(blocked)


def test_a_writable_file_is_left_alone(tmp_path) -> None:
    """The check must not create or truncate anything it touches."""
    path = pathlib.Path(tmp_path) / "confirmations.yaml"
    path.write_text("confirmations: []\n", encoding="utf-8")

    _refuse_if_unwritable(path)

    assert path.read_text(encoding="utf-8") == "confirmations: []\n"


class _Ingredient:
    def __init__(self, name: str) -> None:
        self.canonical_name = name
        self.confirmed_at = None


class _Session:
    """Just enough session to see whether anything was committed."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_nothing_is_committed_when_the_file_cannot_be_written(monkeypatch, tmp_path) -> None:
    """Order matters, and it is not a style preference.

    The file is the durable record and the database is derived from it, so
    committing first claims a confirmation that nothing outside a Docker volume
    remembers. This is the failure that actually happened — twenty-two entries
    confirmed in the database, absent from the file — reproduced here with the
    write failing for a different reason.
    """
    from app.catalog import review

    path = pathlib.Path(tmp_path) / "confirmations.yaml"
    monkeypatch.setattr(review, "confirmations_file", lambda: path)
    monkeypatch.setattr(review, "load_confirmations", lambda: {})
    monkeypatch.setattr(
        review, "pending", lambda db: [(_Ingredient("Veau"), [], ["red_meat"], 3)]
    )

    def refuse(records, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise OSError("disk full")

    monkeypatch.setattr(review, "save_confirmations", refuse)

    db = _Session()
    with pytest.raises(OSError, match="disk full"):
        review.run_review(db, say=lambda _: None, bulk_safe=True)

    assert db.commits == 0
