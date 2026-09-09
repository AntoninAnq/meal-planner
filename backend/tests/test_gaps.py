"""Which referential entry is worth writing next, and why that is not obvious.

Two rules carry this whole tool, and both are counter-intuitive enough to be
worth pinning:

* **Rank by recipes completed, never by frequency.** A name appearing two
  hundred times in recipes that each have three other unknowns unlocks nothing.
  One appearing twice, as the last missing line, unlocks two recipes.
* **A dessert is not worth an entry.** Measured before the filter existed: of
  417 recipes one line short of verification, 237 were a dessert, a snack, a
  side, a drink, a breakfast or a component. More than half of the work bought
  a week nothing.

No database: `rank` is the half with an opinion in it, and it is pure.
"""

from __future__ import annotations

from app.catalog.gaps import NEEDS_A_HUMAN, Gap, as_yaml, rank


def line(recipe: str, name: str, *, resolved: bool = True, title: str = "Un plat") -> object:
    from app.catalog.gaps import Line

    return Line(recipe=recipe, title=title, name=name, resolved=resolved, raw=f"1 {name}")


def test_the_last_missing_line_of_a_recipe_ranks_first() -> None:
    found = rank(
        [
            # `safran` blocks one recipe on its own.
            line("r1", "riz"),
            line("r1", "safran", resolved=False),
            # `curcuma` appears three times, but never alone: those recipes
            # stay unverified whatever anyone writes about it.
            line("r2", "curcuma", resolved=False),
            line("r2", "galanga", resolved=False),
            line("r3", "curcuma", resolved=False),
            line("r3", "galanga", resolved=False),
            line("r4", "curcuma", resolved=False),
            line("r4", "galanga", resolved=False),
        ]
    )

    assert [gap.name for gap in found][0] == "safran"
    assert found[0].completes == 1
    # Frequency alone would have put curcuma first, three to one.
    assert found[0].occurrences < next(g.occurrences for g in found if g.name == "curcuma")


def test_a_name_completing_two_recipes_beats_one_completing_one() -> None:
    found = rank(
        [
            line("r1", "chorizo", resolved=False),
            line("r2", "chorizo", resolved=False),
            line("r3", "mirabelle", resolved=False),
        ]
    )

    assert [gap.name for gap in found] == ["chorizo", "mirabelle"]
    assert found[0].completes == 2


def test_a_fully_resolved_recipe_contributes_nothing() -> None:
    assert rank([line("r1", "riz"), line("r1", "safran")]) == []


def test_the_raw_lines_travel_with_the_name() -> None:
    """What the source wrote is what makes the judgement possible.

    Without it a reviewer has `coque de macaron` and no way to tell a food from
    a component of another recipe, short of opening a query.
    """
    from app.catalog.gaps import Line

    found = rank(
        [
            Line(recipe="r1", title="Macarons", name="coque de macaron", resolved=False,
                 raw="20 coques de macarons"),
            Line(recipe="r2", title="Autre", name="coque de macaron", resolved=False,
                 raw="20 coques de macarons (colorées)"),
        ]
    )

    assert found[0].raw == ["20 coques de macarons", "20 coques de macarons (colorées)"]
    assert found[0].example in {"Macarons", "Autre"}


# -- What the stubs may and may not claim -----------------------------------


def test_a_stub_never_fills_in_an_allergen() -> None:
    """I1, at the one place a tool would be tempted to help.

    A category left wrong costs a rotation signal; an allergen left wrong costs
    an emergency. Neither is guessed, and the marker says a person is expected.
    """
    yaml = as_yaml([Gap(name="chorizo en baton", completes=2, occurrences=2)])

    assert "allergens: []" in yaml
    assert yaml.count(NEEDS_A_HUMAN) == 2  # allergens and categories both
    assert "name: chorizo en baton" in yaml


def test_the_stub_carries_what_the_reviewer_needs_to_decide() -> None:
    yaml = as_yaml(
        [
            Gap(
                name="stabilisateur a glace",
                completes=2,
                occurrences=4,
                raw=["3 g stabilisateur à glace"],
                example="Crème Glacée Vanille",
            )
        ]
    )

    assert "Crème Glacée Vanille" in yaml
    assert "3 g stabilisateur à glace" in yaml


def test_nothing_to_do_says_so_rather_than_printing_an_empty_list() -> None:
    assert "Rien à combler" in as_yaml([])
