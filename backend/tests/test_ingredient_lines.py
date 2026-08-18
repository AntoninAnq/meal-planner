"""The parser, on lines taken from the real catalogue.

Every case here comes from a page that was actually fetched. They are not
illustrations: each one is a bug that inflated the referential work, or would
have.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.catalog.ingredient_lines import (
    fold,
    normalise,
    parse_line,
    singularise,
    variants,
)


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A bare `cuillerée`, with no `à café` after it.
        ("1,5 cuillerée levure chimique", "levure chimique"),
        # An adjective describing the MEASURE, before or after the unit.
        ("1 cuiller à café bombée de levure chimique", "levure chimique"),
        ("2 grosses cuillerées de miel", "miel"),
        ("1 grosse pincée de sel", "sel"),
        # But the same adjective on a FOOD must survive: `petits pois` is not
        # `pois`, and conflating them would put the wrong thing in a plate.
        # The qualifier is consumed only when a unit follows it.
        ("petits pois", "petit pois"),
        ("2 petits oignons", "petit oignon"),
        ("une grosse tomate", "grosse tomate"),
    ],
)
def test_measure_qualifiers_are_stripped_only_before_a_unit(raw: str, expected: str) -> None:
    assert parse_line(raw).normalized == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A range is one ingredient. Consuming only the first number left the
        # rest in the name: three spellings, three unusable strings.
        ("2 à 3 œufs entiers", "oeuf entier"),
        ("1 à 2 gousses d’ail hachées", "ail hachee"),
        ("225 g+125 g de sucre", "sucre"),
        ("180-200 g de sucre", "sucre"),
        # A length is how ginger and leeks are measured.
        ("4 cm gingembre frais", "gingembre frais"),
        # This pattern is applied after `fold`, so an accented spelling in the
        # unit list could never match — `dl` carried the case alone.
        ("2 décilitres de lait", "lait"),
        # The elided article survived the digit strip and made `jus d' citron`
        # a string of its own.
        ("Jus d’1 citron frais", "jus citron frais"),
        ("1 belle pincée origan", "origan"),
        ("Quelques amandes effilées", "amande effilee"),
    ],
)
def test_quantity_bugs_found_by_reading_the_unresolved_tail(raw: str, expected: str) -> None:
    assert parse_line(raw).normalized == expected


def test_a_unit_is_not_lost_to_the_orphan_article_filter() -> None:
    """`l` is the litre, and the unit goes through `normalise` too."""
    assert parse_line("50 cl de lait").unit == "cl"
    assert parse_line("1 l de bouillon").unit == "l"


def test_a_qualifier_after_a_unit_cannot_eat_a_food() -> None:
    """`1 sachet petits pois` must not become `pois`.

    The post-unit list is deliberately shorter than the pre-unit one: there no
    following unit can act as a guard, and `petit` / `gros` can open a food
    name where `bombée` or `généreuse` cannot.
    """
    assert parse_line("1 sachet petits pois").normalized == "petit pois"
    assert parse_line("2 cuillerées bombées de sucre").normalized == "sucre"


# ---------------------------------------------------------------------------
# Relaxation — the four things it must never do
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "creme de soja",       # `crème` would swap `soybeans` for `milk`
        "lait de coco",        # `lait` would invent `milk` where there is none
        "farine de riz",       # `farine de blé` is the gluten-free one's neighbour
        "sel de celeri",       # `sel` would drop `celery`
        "noix de beurre",      # and `noix de coco` would become a tree nut
    ],
)
def test_a_complement_in_de_is_never_removed(name: str) -> None:
    """The rule that makes relaxation safe rather than clever.

    Every one of these has a head that resolves to a DIFFERENT allergen set
    from the whole. There is no version of this feature where they are touched.
    """
    head = name.split(" de ")[0]
    assert head not in list(variants(name))


@pytest.mark.parametrize(
    "name",
    [
        "radis noir",
        "betterave rouge",
        "mais doux",
        "farine de ble noir",   # buckwheat: not wheat, and no gluten
        "chocolat noir",        # carries `milk`, where a bare `chocolat` need not
    ],
)
def test_a_variety_or_a_colour_is_never_removed(name: str) -> None:
    """A colour can cross an allergen boundary, so it is never a rule.

    These become referential entries, written and confirmed one at a time.
    """
    assert list(variants(name)) == []


@pytest.mark.parametrize("name", ["raisin sec", "abricot sec", "figue seche", "tomate sechee"])
def test_dried_is_never_removed(name: str) -> None:
    """Dried fruit is sulphited and fresh fruit is not.

    `Raisin sec` carries `sulphites` in the shipped referential and `Raisin`
    does not — removing the word would remove the allergen.
    """
    assert list(variants(name)) == []


def test_petit_beurre_can_never_reach_beurre() -> None:
    """The one case measured where a relaxation would REMOVE an allergen.

    The petit-beurre is a biscuit — gluten, eggs, milk. `Beurre` carries milk
    alone, so reading one as the other hides gluten from a coeliac household.
    Checked from the qualified form too, because the leading-calibre rule fires
    before the others and would otherwise offer `beurre écrasé` first.
    """
    assert "beurre" not in list(variants("petit beurre"))
    assert "beurre" not in list(variants("petit beurre ecrase"))
    assert "beurre ecrase" not in list(variants("petit beurre ecrase"))
    assert "lait" not in list(variants("petit lait froid"))


def test_a_protected_compound_is_still_a_valid_destination() -> None:
    """Protection forbids relaxing it further, not reaching it.

    `petits pois surgelés` must find `petits pois` — an entry — and must never
    reach `pois`, which is a different vegetable.
    """
    reachable = list(variants("petit pois surgele"))
    assert "petit pois" in reachable
    assert "pois" not in reachable


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("courgette moyenne", "courgette"),
        ("grosse carotte", "carotte"),
        ("betterave cuite", "betterave"),
        ("graine de sesame torrefiee", "graine de sesame"),
        ("beurre en des", "beurre"),
        ("thon au naturel", "thon"),
        ("oignon finement hache", "oignon"),
        ("lentille verte du puy", "lentille verte"),
        ("creme liquide entiere froide", "creme liquide"),
    ],
)
def test_what_relaxation_is_actually_for(name: str, expected: str) -> None:
    """Measured: 423 savoury recipes were one line of this kind short of I3."""
    assert expected in list(variants(name))
