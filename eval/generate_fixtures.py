"""Build the frozen fixture catalogue — from our referential, never from a source.

`ARCHITECTURE.md` §14.1 wants a frozen, committed dataset, and I9 forbids
republishing anyone's content. Copying three hundred scraped titles and
ingredient lists into a public repository would satisfy the first by breaking
the second.

So the catalogue is **composed** rather than copied: every ingredient comes from
`db/ingredients.yaml`, which is our own hand-written file, and every title is
assembled from templates. Nothing here was scraped and no model was involved —
the recipes are combinatorial, so I7 is not in play either.

**What the harness actually needs is a realistic STRUCTURE, not authentic
content**: the distribution of allergens, of dish types, of ingredient counts
and of effort. Those emerge here the same way they do in production — the
allergens are DERIVED from the ingredients drawn, exactly as `resolve` derives
them — so a fixture household hits the same walls a real one does.

Sized at 80 recipes, and the number is not arbitrary. Measured on the real
catalogue, milk is carried by 62 % of eligible recipes and gluten by 46 %, so a
severe milk-and-gluten allergy leaves about 28 % standing. Eighty recipes put
that worst case at roughly twenty candidates for eighteen dishes — the edge
where the pre-filter has to be right, which is where a harness earns its keep.
Three hundred would bury that case; eighty keeps the file readable, and a
fixture nobody can read explains no failure.

Deterministic for a GIVEN referential: same seed and same `ingredients.yaml`
produce the same file. But `db/ingredients.yaml` grows — sixty entries and
ninety aliases were added in one afternoon — and the draw is taken from it, so
regenerating after a referential change yields a DIFFERENT catalogue.

**That is why regenerating is a deliberate act, not a reflex.** §14.1 wants the
dataset frozen precisely so October's score can be compared with December's; a
fixture rebuilt whenever the referential moves would mean believing the model
changed when the data did. Every score recorded before a regeneration becomes
incomparable with every score after it.

So: regenerate when you intend to reset the baseline, and say so in the commit.
Not because the referential grew.

    docker compose run --rm --no-deps -v "$PWD/eval:/eval" -v "$PWD/db:/db:ro" \\
        -w / api python /eval/generate_fixtures.py
"""

from __future__ import annotations

import pathlib
import random
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
REFERENTIAL = ROOT.parent / "db" / "ingredients.yaml"
FIXTURES = ROOT / "fixtures"

#: Same seed forever. A fixture that moved between runs would defeat the one
#: property §14.1 asks for: comparability over time.
SEED = 20260818
RECIPES = 80

#: Measured on the real catalogue (non-section ingredient lines):
#: p25 = 6, p50 = 8, p75 = 10, p90 = 14.
INGREDIENT_COUNTS = [5, 6, 6, 7, 7, 8, 8, 8, 9, 9, 10, 10, 11, 12, 14]

#: Measured: prep+cook p10 = 15, p25 = 25, p50 = 40, p75 = 65, p90 = 110.
MINUTES = [15, 20, 25, 30, 30, 35, 40, 40, 45, 50, 60, 65, 80, 110, 130]
#: Measured: p25 = 4, p50 = 6, p75 = 10, p90 = 16.
STEPS = [3, 3, 4, 4, 5, 6, 6, 7, 8, 10, 10, 12, 16]

#: The share of the real catalogue that declares nothing. Reproduced, because a
#: harness that never meets a NULL would not exercise the code that handles it.
MISSING_MINUTES_SHARE = 0.22
MISSING_STEPS_SHARE = 0.52

#: Dish types in the proportions measured on the real catalogue: a majority of
#: the verified set is sweet, and the fixture must reproduce that or the
#: pre-filter looks better here than it is.
DISH_TYPES = (
    ["main"] * 30 + ["dessert"] * 22 + ["starter"] * 8 + ["side"] * 6
    + ["component"] * 6 + ["snack"] * 3 + ["breakfast"] * 3 + ["drink"] * 2
)

# --- What a form is willing to be made of -----------------------------------

VEG = ["green_vegetable", "root_vegetable", "vegetable"]
MEAT = ["white_meat", "red_meat", "charcuterie"]
SEA = ["fish", "seafood"]
PULSE = ["legumes_secs"]
STARCH = ["cereal"]
CHEESE = ["cheese"]
DAIRY = ["dairy"]
FRUIT = ["fruit"]
NUT = ["nuts_seeds"]
HERB = ["herb_spice"]

#: (template, dish type, categories for {a}, categories for {b}).
#:
#: Narrow on purpose. A first draft drew both slots from one broad list and
#: produced `Ragoût de biscuit au bœuf` and `Bouillon de huile d'arachide` — a
#: fixture whose titles are absurd measures the model's reaction to absurdity,
#: not its planning.
FORMS: list[tuple[str, str, list[str], list[str]]] = [
    ("Gratin {de_a}{a} {au_b}{b}", "main", VEG + STARCH, CHEESE + DAIRY),
    ("Poêlée {de_a}{a} {au_b}{b}", "main", VEG, MEAT + HERB),
    ("Soupe {de_a}{a} {au_b}{b}", "main", VEG, HERB + DAIRY),
    ("Curry {de_a}{a} {au_b}{b}", "main", VEG + PULSE + MEAT, HERB),
    ("Ragoût {de_a}{a} {au_b}{b}", "main", MEAT + PULSE, VEG),
    ("Tarte salée {au_a}{a}", "main", VEG + CHEESE, VEG),
    ("Filet {de_a}{a} {au_b}{b}", "main", SEA, HERB),
    ("Salade tiède {de_a}{a} {au_b}{b}", "starter", VEG, CHEESE + NUT),
    ("Velouté {de_a}{a}", "starter", VEG, VEG),
    ("Purée {de_a}{a} {au_b}{b}", "side", VEG, DAIRY + HERB),
    ("{A} au four {au_b}{b}", "side", VEG, HERB),
    ("Gâteau {au_a}{a}", "dessert", FRUIT + NUT, FRUIT),
    ("Crème {au_a}{a}", "dessert", FRUIT + NUT, FRUIT),
    ("Tarte {au_a}{a}", "dessert", FRUIT, FRUIT),
    ("Sablés {au_a}{a}", "snack", NUT + FRUIT, NUT),
    ("Porridge {au_a}{a}", "breakfast", FRUIT + NUT, FRUIT),
    ("Smoothie {a} et {b}", "drink", FRUIT, FRUIT),
    ("Sauce {au_a}{a}", "component", HERB + VEG, HERB),
    ("Bouillon {de_a}{a}", "component", VEG, VEG),
]

#: Where the rest of an ingredient list comes from. It is what makes overlap
#: between fixture recipes look the way it does in production — and what the
#: pantry filter of the overlap signal then has to see through.
PANTRY = ["herb_spice", "condiment", "fat_oil", "dairy", "egg", "cereal", "sweetener"]


def _load_referential() -> dict[str, list[dict]]:
    document = yaml.safe_load(REFERENTIAL.read_text(encoding="utf-8"))
    by_category: dict[str, list[dict]] = {}
    for entry in document["ingredients"]:
        for code in entry.get("categories") or []:
            by_category.setdefault(code, []).append(entry)
    return by_category


_VOWELS = "aeiouyéèêàâîôû"

#: Nouns ending in `-e` that are nonetheless masculine. French gender is not
#: derivable from spelling, and the `-e` rule is right often enough to be worth
#: keeping — but wrong on exactly the words a recipe title uses. Enumerated
#: rather than guessed, and short enough to read.
MASCULINE_IN_E = frozenset(
    {
        "beurre", "fromage", "gingembre", "vinaigre", "sucre", "poivre",
        "concombre", "pamplemousse", "gruyère", "chèvre", "camembert",
        "cidre", "curry", "sirop", "arome", "arôme", "champagne", "colorant",
    }
)


def _head(name: str) -> str:
    """The FIRST word — it is the one that carries number and gender.

    `Pépites de chocolat` is plural even though the string ends in `t`, and
    `Fromage frais` is singular even though it ends in `s`. Reading the tail
    produced `au pépites de chocolat` and `aux fromage frais`.
    """
    return name.lower().split()[0] if name.split() else name.lower()


def _connectors(name: str) -> tuple[str, str]:
    """(the `de` form, the `à` form) agreed with the name.

    Returns them ready to concatenate: an elided form carries no trailing
    space, every other one does.
    """
    head = _head(name)
    # `-x` is a plural too: noix, choux.
    if head.endswith(("s", "x")):
        return "de ", "aux "
    if head[:1] in _VOWELS or head.startswith("h"):
        return "d'", "à l'"
    if head.endswith("e") and head not in MASCULINE_IN_E:
        return "de ", "à la "
    return "de ", "au "


def fill(template: str, first: str, second: str) -> str:
    de_a, au_a = _connectors(first)
    _, au_b = _connectors(second)
    return " ".join(
        template.replace("{A}", first)
        .replace("{de_a}", de_a)
        .replace("{au_a}", au_a)
        .replace("{au_b}", au_b)
        .replace("{a}", first.lower())
        .replace("{b}", second.lower())
        .split()
    )


def build_catalogue() -> list[dict[str, Any]]:
    by_category = _load_referential()
    rng = random.Random(SEED)

    dish_types = list(DISH_TYPES)
    rng.shuffle(dish_types)

    recipes: list[dict[str, Any]] = []
    seen: set[str] = set()

    while len(recipes) < RECIPES:
        dish_type = dish_types[len(recipes) % len(dish_types)]
        template, _, cats_a, cats_b = rng.choice(
            [entry for entry in FORMS if entry[1] == dish_type]
        )

        pool_a = [entry for code in cats_a for entry in by_category.get(code, [])]
        pool_b = [entry for code in cats_b for entry in by_category.get(code, [])]
        if not pool_a or not pool_b:
            continue

        first, second = rng.choice(pool_a), rng.choice(pool_b)
        if first["name"] == second["name"]:
            continue

        title = fill(template, first["name"], second["name"])
        if title in seen:
            continue
        seen.add(title)

        names = [first["name"], second["name"]]
        target = rng.choice(INGREDIENT_COUNTS)
        guard = 0
        while len(names) < target and guard < 100:
            guard += 1
            pool = by_category.get(rng.choice(PANTRY)) or []
            if not pool:
                continue
            candidate = rng.choice(pool)["name"]
            if candidate not in names:
                names.append(candidate)

        minutes = None if rng.random() < MISSING_MINUTES_SHARE else rng.choice(MINUTES)
        steps = None if rng.random() < MISSING_STEPS_SHARE else rng.choice(STEPS)

        recipes.append(
            {
                "id": f"r_{len(recipes):03d}",
                "title": title,
                "dish_type": dish_type,
                "ingredients": names,
                "prep_minutes": None if minutes is None else max(5, minutes // 3),
                "cook_minutes": None if minutes is None else minutes - max(5, minutes // 3),
                "step_count": steps,
                "servings": rng.choice([2, 4, 4, 4, 6]),
            }
        )
    return recipes


HOUSEHOLDS: list[dict[str, Any]] = [
    {
        "key": "baby_only",
        "why": "No catalogue recipe carries `baby` — zero of 3 439 — so every "
               "assignment here must ride on a serving variant (§4.9). The "
               "degraded case: with no adult at the table there is no dish to "
               "take a portion from, so the system adapts a catalogue recipe "
               "outright. It used to expect an EMPTY plan; the stage no longer "
               "leaves the grid.",
        "members": [{"alias": "m1", "life_stage": "baby"}],
        "constraints": [],
    },
    {
        "key": "severe_milk_allergy",
        "why": "The hard filter at its narrowest: milk is the most common "
               "allergen in the catalogue, and the pool collapses.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "young_child"},
        ],
        "constraints": [
            {"member": "m2", "allergen_code": "milk", "severity": "severe_allergy"}
        ],
    },
    {
        "key": "member_intolerance",
        "why": "The common case: one member has an intolerance and the catalogue "
               "holds enough safe dishes that ONE preparation still feeds "
               "everyone. Named after what it is — an earlier name claimed it "
               "forced two dishes, which measurement disproved.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "teen_adult"},
            {"alias": "m3", "life_stage": "young_child"},
        ],
        "constraints": [
            {"member": "m3", "allergen_code": "gluten", "severity": "intolerance"}
        ],
    },
    {
        "key": "teen_and_young_child",
        "why": "Two stages, no allergen: the stage rule alone must not force a "
               "second dish, since both stages are served by the catalogue.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "teen_adult"},
            {"alias": "m3", "life_stage": "young_child"},
        ],
        "constraints": [],
    },
    {
        "key": "founder",
        "why": "The household the product is built for, described by its own "
               "member: two adults and a six-year-old who eats what they eat. "
               "It carries the only human reference plan (§14.4), so it is the "
               "only case whose weeks are judged on quality and not merely on "
               "validity. The baby of that household is missing on purpose — "
               "see `docs/ARCHITECTURE.md` §15 on derived dishes.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "teen_adult"},
            {"alias": "m3", "life_stage": "young_child"},
        ],
        "constraints": [],
    },
    {
        "key": "busy_week",
        "why": "Same shape as `founder` — two adults and a six-year-old, "
               "nothing filtered — so the only thing this case varies is what "
               "the household SAID about its week. It carries the three "
               "constraints that were all ignored on one real generation: a "
               "time budget, a day away, and a dish to cook once and eat twice.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "teen_adult"},
            {"alias": "m3", "life_stage": "young_child"},
        ],
        "constraints": [],
    },
    {
        "key": "no_constraint",
        "why": "The baseline. Nothing is filtered, `allergens_verified` is not "
               "required, and the pool is at its widest.",
        "members": [
            {"alias": "m1", "life_stage": "teen_adult"},
            {"alias": "m2", "life_stage": "teen_adult"},
        ],
        "constraints": [],
    },
]

HEADER = """\
# ENGENDRÉ — ne pas éditer à la main.
#
# ⚠️  NE PAS RÉGÉNÉRER par réflexe. Le tirage vient de `db/ingredients.yaml`, qui
# grossit : régénérer après une modification du référentiel produit un AUTRE
# catalogue, et remet donc à zéro le repère du §14.1. Tous les scores mesurés
# avant deviennent incomparables avec ceux d'après. On régénère quand on veut
# délibérément changer de référence, et on l'écrit dans le message de commit.
#
# Composé depuis `db/ingredients.yaml`, notre propre fichier. Aucun contenu
# externe, aucun modèle : ni I9 ni I7 ne sont en jeu. Ce que le banc d'essai
# mesure est un MODÈLE sur de la planification, ce qui demande une structure
# réaliste — pas un contenu authentique.
"""


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--households-only",
        action="store_true",
        help="rewrite households.yaml and LEAVE the catalogue alone — the "
        "catalogue is the frozen baseline (§14.1) and regenerating it after a "
        "referential change silently makes every past score incomparable",
    )
    args = parser.parse_args()

    FIXTURES.mkdir(exist_ok=True)

    if args.households_only:
        (FIXTURES / "households.yaml").write_text(
            HEADER
            + "\n"
            + yaml.safe_dump({"households": HOUSEHOLDS}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        print(f"{len(HOUSEHOLDS)} foyers — catalogue inchangé")
        return

    recipes = build_catalogue()

    (FIXTURES / "catalogue.yaml").write_text(
        HEADER + "\n" + yaml.safe_dump({"recipes": recipes}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (FIXTURES / "households.yaml").write_text(
        HEADER
        + "\n"
        + yaml.safe_dump({"households": HOUSEHOLDS}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    by_type: dict[str, int] = {}
    for recipe in recipes:
        by_type[recipe["dish_type"]] = by_type.get(recipe["dish_type"], 0) + 1
    print(f"{len(recipes)} recettes, {len(HOUSEHOLDS)} foyers")
    for code, count in sorted(by_type.items()):
        print(f"  {code:<10} {count}")


if __name__ == "__main__":
    main()
