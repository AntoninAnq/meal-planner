"""The parser, on lines taken from the real catalogue.

Every case here comes from a page that was actually fetched. They are not
illustrations: each one is a bug that inflated the referential work, or would
have.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.catalog.ingredient_lines import fold, normalise, parse_line, singularise


@pytest.mark.parametrize(
    ("raw", "quantity", "unit", "normalized"),
    [
        ("400 g de myrtilles fraîches", 400, "g", "myrtille fraiche"),
        ("250 g de farine", 250, "g", "farine"),
        ("1 œuf", 1, None, "oeuf"),
        ("50 cl de lait", 50, "cl", "lait"),
        ("1 cuillère à café de sucre vanillé", 1, "cuillere a cafe", "sucre vanille"),
        ("2 c. à soupe d'huile d'olive", 2, "c a soupe", "huile d'olive"),
        ("1,5 l de bouillon", Fraction(3, 2), "l", "bouillon"),
        ("½ citron", Fraction(1, 2), None, "citron"),
        ("Sel, poivre", None, None, "sel"),
        ("beurre (mou)", None, None, "beurre"),
        ("3 gousses d'ail", 3, "gousse", "ail"),
        ("une pincée de sel", 1, "pincee", "sel"),
    ],
)
def test_lines_from_the_real_catalogue(
    raw: str, quantity: object, unit: str | None, normalized: str
) -> None:
    parsed = parse_line(raw)
    assert parsed.quantity == (Fraction(quantity) if quantity is not None else None)
    assert parsed.unit == unit
    assert parsed.normalized == normalized
    assert parsed.raw == raw.strip()


def test_the_oe_ligature_survives() -> None:
    """`œufs` is the third most common ingredient in the catalogue.

    Passed through NFKD the ligature is kept, and the later `[a-z]` filter then
    drops it entirely, leaving `ufs`. A first draft of this parser produced
    `ufs` (310), `uf` (171) and `oeuf` (331) as three distinct strings for one
    word — three referential entries where one is needed.
    """
    assert normalise("œufs") == "oeuf"
    assert normalise("Œufs") == "oeuf"
    assert parse_line("3 œufs").normalized == parse_line("3 oeufs").normalized


def test_a_typographic_apostrophe_is_the_same_as_a_straight_one() -> None:
    """Blogs emit `d’ail`, and it split `ail` (343) from `d ail` (373)."""
    assert parse_line("3 gousses d’ail").normalized == parse_line("3 gousses d'ail").normalized
    assert parse_line("d’huile d’olive").normalized == "huile d'olive"


def test_de_lait_is_not_de_la_followed_by_it() -> None:
    """The bug that produced a mystery ingredient called `it`, 256 times.

    Stripping the article `de la` without a word boundary eats the start of the
    next word. A trigram matcher cannot recover from this; a word boundary
    prevents it.
    """
    assert parse_line("50 cl de lait").normalized == "lait"
    assert parse_line("de la crème").normalized == "creme"


def test_a_section_heading_is_not_mistaken_for_a_quantity() -> None:
    """`Pour la pâte sucrée :` is flagged upstream, but must survive intact."""
    assert parse_line("Pour la pâte sucrée :").normalized == "pour la pate sucree"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("carottes", "carotte"),
        ("oeufs", "oeuf"),
        ("choux", "choux"),        # not `chou`: -oux words keep their form here
        ("riz", "riz"),
        ("ail", "ail"),            # too short to touch
        ("chevaux", "cheval"),
    ],
)
def test_plurals_are_stripped_crudely_on_purpose(word: str, expected: str) -> None:
    """A real stemmer would conflate words that must stay apart.

    `pâte` and `pâtes` are different foods. Over-eager stemming is the
    fuzzy-matching mistake wearing another hat (I4).
    """
    assert singularise(word) == expected


def test_folding_is_idempotent() -> None:
    once = fold("Crème Fraîche d’Isigny — ½ pot")
    assert fold(once) == once


def test_an_unparsable_line_becomes_a_name_rather_than_an_error() -> None:
    """32 000 lines will contain things no grammar anticipated.

    Losing one is losing a whole recipe from the verified catalogue, so the
    parser never raises: it degrades to "all of it is the name", and the
    resolution pass then simply fails to match it — visibly, and counted.
    """
    parsed = parse_line("un peu de ce qu'il vous reste")
    assert parsed.normalized
    assert parsed.raw == "un peu de ce qu'il vous reste"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        # `-eaux` before `-aux`, or `poireaux` becomes `poireal`. Three bogus
        # entries in the real top 200 came from checking them the other way.
        ("poireaux", "poireau"),
        ("pruneaux", "pruneau"),
        ("cerneaux", "cerneau"),
        # Singulars that already end in `s`. Stripping it invents a word, and
        # the invented word becomes a referential entry someone has to notice.
        ("mais", "mais"),   # déjà replié : singularise() ne voit jamais d'accent
        ("radis", "radis"),
        ("ananas", "ananas"),
        ("pois", "pois"),
        ("anchois", "anchois"),
        ("frais", "frais"),
        ("gros", "gros"),
    ],
)
def test_plural_rules_that_the_real_catalogue_caught(word: str, expected: str) -> None:
    assert singularise(word) == expected


@pytest.mark.parametrize(
    "raw",
    ["Pour servir", "Pour la sauce :", "Pour décorer", "Garniture", "Pour le glaçage"],
)
def test_a_line_that_organises_the_list_is_not_an_ingredient(raw: str) -> None:
    """One `pour servir` keeps a whole recipe out of the verified catalogue.

    I3 requires EVERY line of a recipe to resolve. A line naming no food can
    never resolve, so leaving it in the count condemns its recipe permanently —
    which is why this is detected rather than left to the referential.
    """
    assert parse_line(raw).is_structural


@pytest.mark.parametrize("raw", ["250 g de farine", "sauce soja", "sauce tomate"])
def test_a_real_ingredient_is_not_taken_for_a_heading(raw: str) -> None:
    """`sauce` alone organises; `sauce soja` is a food, and carries soy."""
    assert not parse_line(raw).is_structural


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # `environ` hedges the quantity and these sources put it BEFORE the
        # name. Truncating there left nothing at all, and a line that
        # normalises to nothing can never resolve — so it blocked its whole
        # recipe (I3). Found by reading the resolution report, not by a test.
        ("150 g environ farine", "farine"),
        ("500 g environ voire un peu plus riz", "riz"),
        ("45 cl environ lait fermenté", "lait fermente"),
        # `noix` reads like a unit in `une noix de beurre`, but it is also the
        # nut — and one that carries an allergen. As a unit, `15 noix` became a
        # quantity with no ingredient, silently dropping `nuts`.
        ("15 noix", "noix"),
        ("une noix de beurre", "noix de beurre"),
    ],
)
def test_hedges_and_false_units_found_in_the_resolution_report(raw: str, expected: str) -> None:
    assert parse_line(raw).normalized == expected
