"""The three rules that decide whether a shopping list is true.

Units are free text, so two quantities add up only when their unit is the same
word — and when it is not, they are juxtaposed rather than converted. A missing
quantity is a missing quantity, not a zero. And the pantry comes out, because a
list that opens on salt, sugar and oil buries the four things worth buying.

The unit normalisation is deliberately shallow: "c. à soupe" and "cuillère à
soupe" stay apart. Deciding they are the same is a parsing problem, and I4
forbids solving it with string similarity — that is where `farine de riz` finds
`farine de blé`.

SQLite, like the other service suites: CI runs without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    FoodCategory,
    Household,
    Ingredient,
    IngredientFoodCategory,
    MealPlan,
    PlannedDish,
    Recipe,
    RecipeIngredient,
)
from app.domain.enums import DishSource, MealType, RecipeSourceType
from app.domain.food_categories import STORE_ORDER, rank_of
from app.services.shopping_list import build


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    FoodCategory.__table__,
    Ingredient.__table__,
    IngredientFoodCategory.__table__,
    Recipe.__table__,
    RecipeIngredient.__table__,
    MealPlan.__table__,
    PlannedDish.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    for table in TABLES:
        for column in table.columns:
            if column.server_default is not None and "::jsonb" in str(column.server_default.arg):
                column.server_default = None
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


class Kitchen:
    """A household, a week, and a way to add a meal made of ingredient lines."""

    def __init__(self, db: Session) -> None:
        self.db = db
        household = Household(name="Mon foyer")
        db.add(household)
        db.flush()
        self.household_id = household.id
        self.plan = MealPlan(household_id=household.id, week_start=date(2026, 9, 7))
        db.add(self.plan)
        db.flush()
        self.categories: dict[str, uuid.UUID] = {}
        self.ingredients: dict[str, uuid.UUID] = {}
        self.day = 0
        # A catalogue of a plausible size, because the pantry threshold is a
        # SHARE of it: with three recipes in the database, an ingredient used
        # twice is in 66 % of the catalogue and every test would find its
        # tomatoes filed under "check the cupboard".
        for _ in range(100):
            db.add(
                Recipe(
                    title="Remplissage",
                    source_type=RecipeSourceType.SCRAPED,
                    source_url=f"https://example.invalid/{uuid.uuid4()}",
                )
            )
        db.flush()

    def category(self, code: str) -> uuid.UUID:
        if code not in self.categories:
            row = FoodCategory(code=code, label=code.title(), label_en=code.title())
            self.db.add(row)
            self.db.flush()
            self.categories[code] = row.id
        return self.categories[code]

    def ingredient(self, name: str, *codes: str) -> uuid.UUID:
        if name not in self.ingredients:
            row = Ingredient(canonical_name=name, normalized_name=name.lower())
            self.db.add(row)
            self.db.flush()
            for code in codes:
                self.db.add(
                    IngredientFoodCategory(
                        ingredient_id=row.id, food_category_id=self.category(code)
                    )
                )
            self.ingredients[name] = row.id
        return self.ingredients[name]

    def meal(
        self,
        lines: list[tuple[str | None, str | None, str | None, str]],
        *,
        with_recipe: bool = True,
    ) -> tuple[int, str]:
        """`lines` are `(ingredient name or None, quantity, unit, raw text)`."""
        recipe_id = None
        if with_recipe:
            recipe = Recipe(
                title=f"Plat {self.day}",
                source_type=RecipeSourceType.SCRAPED,
                source_url=f"https://example.invalid/{uuid.uuid4()}",
            )
            self.db.add(recipe)
            self.db.flush()
            recipe_id = recipe.id
            for position, (name, quantity, unit, raw) in enumerate(lines):
                self.db.add(
                    RecipeIngredient(
                        recipe_id=recipe.id,
                        position=position,
                        raw_text=raw,
                        quantity=Decimal(quantity) if quantity is not None else None,
                        unit=unit,
                        ingredient_id=self.ingredient(name) if name else None,
                    )
                )
        self.db.add(
            PlannedDish(
                meal_plan_id=self.plan.id,
                day_of_week=self.day,
                meal_type=MealType.DINNER,
                recipe_id=recipe_id,
                # `ck_planned_dish_identity`: a dish is a recipe or a title,
                # never neither. A model suggestion is the second.
                free_text_label=None if recipe_id else "Restes de dimanche",
                source=DishSource.CATALOG if recipe_id else DishSource.LLM_SUGGESTION,
            )
        )
        self.db.commit()
        slot = (self.day, "dinner")
        # `ck_planned_dish_day` keeps the week to seven days, so a test that
        # wants more meals than that asks for the wrong thing.
        self.day += 1
        return slot

    def stock(self, name: str, count: int, *codes: str) -> None:
        """Put this ingredient in `count` more catalogue recipes.

        The pantry threshold is a SHARE of the catalogue, so "is this a
        cupboard staple" is a fact about the catalogue and not about the week.
        This is how a test says "salt is everywhere" without planning a meal.
        """
        ingredient_id = self.ingredient(name, *codes)
        for _ in range(count):
            recipe = Recipe(
                title="Remplissage",
                source_type=RecipeSourceType.SCRAPED,
                source_url=f"https://example.invalid/{uuid.uuid4()}",
            )
            self.db.add(recipe)
            self.db.flush()
            self.db.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    position=0,
                    raw_text=name,
                    ingredient_id=ingredient_id,
                )
            )
        self.db.commit()

    def list(self, *slots: tuple[int, str]):
        self.db.refresh(self.plan)
        return build(
            self.db,
            household_id=self.household_id,
            plan=self.plan,
            slots=set(slots) or {(0, "dinner")},
        )


def _lines(result, code: str) -> list[tuple[str, str | None]]:
    for section in result.sections:
        if section.code == code:
            return [(line.name, line.amount) for line in section.lines]
    return []


# -- Adding up, and refusing to ----------------------------------------------


def test_the_same_unit_adds_up(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Tomate", "200", "g", "200 g de tomates")])
    b = kitchen.meal([("Tomate", "150", "g", "150 g de tomates")])

    assert _lines(kitchen.list(a, b), "vegetable") == [("Tomate", "350 g")]


def test_the_unit_is_matched_loosely_enough_to_be_safe(db: Session) -> None:
    """Lowercased, whitespace collapsed, and no further: that is the whole
    normalisation, on purpose."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Tomate", "200", " G ", "200 G")])
    b = kitchen.meal([("Tomate", "100", "g", "100 g")])

    assert _lines(kitchen.list(a, b), "vegetable") == [("Tomate", "300 g")]


def test_units_that_disagree_are_juxtaposed_never_converted(db: Session) -> None:
    """"250 g + 2 verres". A conversion table would be wrong on "pincée",
    "verre" and "bouquet", which is most of what it would be asked."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Farine", "cereal")
    a = kitchen.meal([("Farine", "250", "g", "250 g de farine")])
    b = kitchen.meal([("Farine", "2", "verres", "2 verres de farine")])

    assert _lines(kitchen.list(a, b), "cereal") == [("Farine", "250 g + 2 verres")]


def test_a_bare_number_keeps_no_unit(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Courgette", "green_vegetable")
    a = kitchen.meal([("Courgette", "3", None, "3 courgettes")])

    assert _lines(kitchen.list(a), "green_vegetable") == [("Courgette", "3")]


def test_a_quantity_nobody_read_is_not_a_zero(db: Session) -> None:
    """The source wrote "du sel". Null is what the interface turns into
    "quantité non lue", and it must not become 0."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Piment", "herb_spice")
    a = kitchen.meal([("Piment", None, None, "du piment")])

    assert _lines(kitchen.list(a), "herb_spice") == [("Piment", None)]


def test_a_line_with_no_quantity_does_not_erase_one_that_has(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Piment", "herb_spice")
    a = kitchen.meal([("Piment", None, None, "du piment")])
    b = kitchen.meal([("Piment", "2", None, "2 piments")])

    assert _lines(kitchen.list(a, b), "herb_spice") == [("Piment", "2")]


def test_a_whole_quantity_is_not_printed_in_scientific_notation(db: Session) -> None:
    """`Decimal("200.000").normalize()` is `2E+2`, and "2E+2 g de tomates" is
    not a shopping list."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Tomate", "200.000", "g", "200 g")])

    assert _lines(kitchen.list(a), "vegetable") == [("Tomate", "200 g")]


def test_a_fraction_keeps_its_decimals(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Crème", "dairy")
    a = kitchen.meal([("Crème", "1.500", "l", "1,5 l de crème")])

    assert _lines(kitchen.list(a), "dairy") == [("Crème", "1.5 l")]


# -- One dish, one set of ingredients ----------------------------------------


def test_the_same_recipe_on_two_meals_counts_twice(db: Session) -> None:
    """Two dinners of the same dish is twice the shopping."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Tomate", "200", "g", "200 g")])
    b = kitchen.meal([("Tomate", "200", "g", "200 g")])

    assert _lines(kitchen.list(a, b), "vegetable") == [("Tomate", "400 g")]


def test_a_meal_left_unchecked_contributes_nothing(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Tomate", "200", "g", "200 g")])
    kitchen.meal([("Tomate", "999", "g", "999 g")])

    assert _lines(kitchen.list(a), "vegetable") == [("Tomate", "200 g")]


def test_a_dish_with_no_recipe_is_declared_not_hidden(db: Session) -> None:
    """Silently omitting it is the worst case: a list somebody believes is
    complete."""
    kitchen = Kitchen(db)
    a = kitchen.meal([], with_recipe=False)
    kitchen.ingredient("Tomate", "vegetable")
    b = kitchen.meal([("Tomate", "200", "g", "200 g")])

    assert kitchen.list(a, b).missing_recipe is True
    assert kitchen.list(b).missing_recipe is False


# -- What does not belong on the list ----------------------------------------


def test_an_unresolved_line_is_copied_verbatim(db: Session) -> None:
    kitchen = Kitchen(db)
    a = kitchen.meal([(None, None, None, "1 pincée de ras el-hanout maison")])

    result = kitchen.list(a)
    assert result.unparsed == ["1 pincée de ras el-hanout maison"]
    assert result.sections == []


def test_the_same_unresolved_line_twice_is_one_line(db: Session) -> None:
    kitchen = Kitchen(db)
    a = kitchen.meal([(None, None, None, "quelques feuilles de coriandre")])
    b = kitchen.meal([(None, None, None, "quelques feuilles de coriandre")])

    assert kitchen.list(a, b).unparsed == ["quelques feuilles de coriandre"]


def test_a_section_header_is_neither_an_ingredient_nor_an_unread_line(db: Session) -> None:
    """"Pour la pâte sucrée :" arrives marked up as an ingredient and is not
    one. It belongs in neither list."""
    kitchen = Kitchen(db)
    recipe = Recipe(
        title="Tarte",
        source_type=RecipeSourceType.SCRAPED,
        source_url="https://example.invalid/tarte",
    )
    db.add(recipe)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            position=0,
            raw_text="Pour la pâte sucrée :",
            is_section=True,
        )
    )
    db.add(
        PlannedDish(
            meal_plan_id=kitchen.plan.id,
            day_of_week=0,
            meal_type=MealType.DINNER,
            recipe_id=recipe.id,
            source=DishSource.CATALOG,
        )
    )
    db.commit()

    result = kitchen.list((0, "dinner"))
    assert result.unparsed == []
    assert result.sections == []


# -- Order, and where a thing appears ----------------------------------------


def test_sections_follow_the_walk_not_the_alphabet(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Porto", "alcohol")
    kitchen.ingredient("Courgette", "green_vegetable")
    kitchen.ingredient("Bœuf", "red_meat")
    a = kitchen.meal(
        [
            ("Porto", "20", "cl", "20 cl"),
            ("Courgette", "2", None, "2 courgettes"),
            ("Bœuf", "350", "g", "350 g"),
        ]
    )

    assert [section.code for section in kitchen.list(a).sections] == [
        "green_vegetable",
        "red_meat",
        "alcohol",
    ]


def test_an_ingredient_of_two_categories_appears_once(db: Session) -> None:
    """`crème` is dairy AND fat_oil. Asking somebody to buy it twice is worse
    than putting it in the wrong aisle."""
    kitchen = Kitchen(db)
    kitchen.ingredient("Crème", "fat_oil", "dairy")
    a = kitchen.meal([("Crème", "20", "cl", "20 cl")])

    result = kitchen.list(a)
    assert [section.code for section in result.sections] == ["dairy"]
    assert _lines(result, "dairy") == [("Crème", "20 cl")]


def test_an_uncategorised_ingredient_lands_in_other(db: Session) -> None:
    kitchen = Kitchen(db)
    kitchen.ingredient("Lait d'amande")
    a = kitchen.meal([("Lait d'amande", "20", "cl", "20 cl")])

    assert _lines(kitchen.list(a), "other") == [("Lait d'amande", "20 cl")]


def test_no_category_and_an_unknown_one_land_in_the_same_place(db: Session) -> None:
    """Neither names a place in a shop, so both sort last rather than raising:
    a category added to the referential and not to the walk is a heading in an
    odd place, not a list that fails to render."""
    assert STORE_ORDER[-1] == "other"
    assert rank_of(None) == rank_of("other")
    assert rank_of("a_category_nobody_declared") == rank_of("other")


def test_a_cupboard_staple_leaves_the_list_for_the_pantry(db: Session) -> None:
    """Salt is in 49 % of the catalogue. A list that opens on salt, sugar and
    oil buries the four things actually worth buying."""
    kitchen = Kitchen(db)
    kitchen.stock("Sel", 30, "condiment")
    kitchen.ingredient("Tomate", "vegetable")
    a = kitchen.meal([("Sel", "1", "pincée", "1 pincée de sel"), ("Tomate", "2", None, "2")])

    result = kitchen.list(a)
    assert result.pantry == ["Sel"]
    assert _lines(result, "vegetable") == [("Tomate", "2")]
    # Not on the list twice, and not with a quantity: nobody checks whether
    # they have 200 g of salt, they check whether there is salt.
    assert _lines(result, "condiment") == []
