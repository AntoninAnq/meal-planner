"""The dish type: what it promises, and the one direction it must lean.

A quality signal, not a safety one — the allergen filter never reads it. What
these tests protect is the asymmetry: missing a dish costs one candidate out of
several hundred, putting a cake on a Tuesday dinner costs the trust someone
places in the tool.
"""

from __future__ import annotations

import pathlib

import pytest

from app.catalog.dish_types import DishTypeError, load_mapping
from app.domain.enums import DishType

SHIPPED = pathlib.Path(__file__).resolve().parents[2] / "db" / "dish_types.yaml"


def test_the_most_restrictive_rubric_wins() -> None:
    """A recipe tagged both `Plat` and `Dessert` is a dessert.

    The sources tag generously and one recipe often carries several rubrics.
    Reading the permissive one would put every ambiguous cake in the dinner
    candidates, which is the failure this column exists to prevent.
    """
    mapping = load_mapping(SHIPPED)

    assert mapping.classify(["Plat", "Dessert"]) is DishType.DESSERT
    assert mapping.classify(["Provence", "Dessert"]) is DishType.DESSERT
    assert mapping.classify(["Sauces", "Plat"]) is DishType.COMPONENT


def test_an_unclassified_recipe_is_null_and_not_a_member() -> None:
    """Absence of a rubric is a NULL column, never a magic value.

    961 catalogue recipes carry no rubric this file knows. They must read as
    unclassified everywhere; an `UNKNOWN` member would let them be selected by
    a query that filters on a type.
    """
    mapping = load_mapping(SHIPPED)

    assert mapping.classify([]) is None
    assert mapping.classify(["Rubrique que personne n'a écrite"]) is None
    # A geographic origin says nothing about the moment of the meal, and is
    # written down as examined rather than left out.
    assert mapping.classify(["Provence"]) is None
    assert "Provence" in mapping.examined


def test_a_component_is_not_a_dish() -> None:
    """A vinaigrette or a roux is a catalogue recipe and not a meal.

    Without this member they fall into "not labelled dessert", and from there
    into the dinner candidates — 221 recipes' worth.
    """
    mapping = load_mapping(SHIPPED)

    for rubric in ("Vinaigrettes", "Roux blancs", "Sauces", "Beurres parfumés"):
        assert mapping.classify([rubric]) is DishType.COMPONENT


def test_a_rubric_mapped_twice_is_refused(tmp_path) -> None:
    """Two types claiming one rubric would make the result depend on dict order."""
    document = """
types:
  - { code: main, label: x }
labels:
  main: [Soupes]
  dessert: [Soupes]
"""
    with pytest.raises(DishTypeError):
        load_mapping(_written(document, tmp_path))


def test_the_file_must_declare_exactly_the_enum(tmp_path) -> None:
    """A type in the file that the code does not know would silently do nothing."""
    document = """
types:
  - { code: main, label: Plat }
precedence: [main]
labels: {}
"""
    with pytest.raises(DishTypeError, match="types declared"):
        load_mapping(_written(document, tmp_path))


def test_the_shipped_mapping_is_loadable_and_complete() -> None:
    """Checked on every build: the real file, against the real enum."""
    mapping = load_mapping(SHIPPED)

    assert set(mapping.precedence) == set(DishType)
    # The most restrictive first. `component` before `main` is the whole point.
    assert mapping.precedence.index(DishType.COMPONENT) < mapping.precedence.index(DishType.MAIN)
    assert mapping.precedence.index(DishType.DESSERT) < mapping.precedence.index(DishType.MAIN)
    assert len(mapping.labels) > 150
    assert mapping.classify(["Tajines"]) is DishType.MAIN
    assert mapping.classify(["Goûter"]) is DishType.SNACK


def _written(document: str, tmp_path) -> pathlib.Path:
    path = pathlib.Path(tmp_path) / "dish_types.yaml"
    path.write_text(document, encoding="utf-8")
    return path
