"""What one more referential entry would unlock, as something you can paste.

`resolve --report` already ranks unresolved names by recipes completed, and
that ranking is right. What it does not do is the part that costs the time: for
each name, work out which recipe it is holding up, what the source actually
wrote, and then hand-write a YAML entry against `db/ingredients.yaml`'s
conventions. This does that, and the output is the file's own shape.

**Measured, which is why it exists.** On the offerable catalogue, 410 recipes
sit exactly one line short of `allergens_verified`, and those 410 are blocked by
401 distinct names — one apiece. There is no leverage anywhere in that
distribution: no parser rule and no clever alias reaches more than a handful.
The five most plausible relaxation rules, measured together, moved 31 of the
410, and the best of them turned `riz au lait` into `riz` — removing an
allergen, which is the exact thing `domain/ingredient_names` rule 2 forbids. So
the work is genuinely four hundred small human decisions, and the only useful
tool is one that makes each decision fast.

**It proposes and never decides** (I1). Every stub comes out with its
`allergens` list empty and a marker on it, because that field is the one that
can hurt someone and no amount of string matching has an opinion about it. The
loader inserts with `confirmed_at = NULL` anyway, so nothing reaches a
household with a severe allergy until a person has been through `review`.

Withdrawn recipes are skipped, and so is anything a meal slot never accepts.
Spending a judgement on a source that answers 404 buys nothing (migration
0013) — and neither does one on a dessert. Measured before this filter existed:
of 417 recipes one line short, 237 were a dessert, a snack, a side, a drink, a
breakfast or a component. More than half the work bought a week nothing.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Recipe, RecipeIngredient
from app.domain.enums import NOT_A_MEAL
from app.domain.ingredient_lines import parse_line

#: Where a human has to look. Left empty on purpose rather than guessed: a
#: category is cheap to fix and an allergen is not, so neither is invented.
NEEDS_A_HUMAN = "TODO"


@dataclass
class Gap:
    """One name, and everything needed to judge it without a query."""

    name: str
    #: Recipes this name alone would complete — the ranking key.
    completes: int
    #: Everywhere it appears, completing or not. Tells a one-off from a staple.
    occurrences: int
    #: What the sources actually wrote, so an odd normalisation is visible.
    raw: list[str] = field(default_factory=list)
    #: A recipe it holds up, to open and look at.
    example: str = ""


@dataclass(frozen=True)
class Line:
    """One ingredient line of one servable recipe, as ranking needs it."""

    recipe: str
    title: str
    name: str
    resolved: bool
    raw: str


def rank(lines: Iterable[Line], *, limit: int = 40) -> list[Gap]:
    """The pure half: which names to write, most valuable first.

    Separated from the reading so it can be tested without a database — and
    because the ranking rule is the part with an opinion in it, while the query
    is only a query.
    """
    per_recipe: dict[str, list[Line]] = collections.defaultdict(list)
    occurrences: collections.Counter[str] = collections.Counter()
    raw_forms: dict[str, set[str]] = collections.defaultdict(set)

    for line in lines:
        per_recipe[line.recipe].append(line)
        if not line.resolved:
            occurrences[line.name] += 1
            raw_forms[line.name].add(line.raw.strip())

    completes: collections.Counter[str] = collections.Counter()
    example: dict[str, str] = {}
    for recipe_lines in per_recipe.values():
        missing = {line.name for line in recipe_lines if not line.resolved}
        # Only the recipes ONE line short. A name appearing in a recipe with
        # three other unknowns unlocks nothing on its own, and ranking by raw
        # frequency would send a reviewer down exactly that list.
        if len(missing) == 1:
            name = next(iter(missing))
            completes[name] += 1
            example.setdefault(name, recipe_lines[0].title)

    ranked = sorted(occurrences, key=lambda name: (-completes[name], -occurrences[name], name))
    return [
        Gap(
            name=name,
            completes=completes[name],
            occurrences=occurrences[name],
            raw=sorted(raw_forms[name])[:3],
            example=example.get(name, ""),
        )
        for name in ranked[:limit]
    ]


def gaps(db: Session, *, limit: int = 40) -> list[Gap]:
    """Read the servable catalogue, then rank it."""
    offerable = dict(
        db.execute(
            select(Recipe.id, Recipe.title).where(
                Recipe.deprecated_at.is_(None),
                Recipe.dish_type.is_(None) | Recipe.dish_type.not_in(NOT_A_MEAL),
            )
        ).all()
    )

    lines: list[Line] = []
    for line in db.scalars(select(RecipeIngredient)):
        if line.recipe_id not in offerable or line.is_section:
            continue
        parsed = parse_line(line.raw_text)
        if parsed.is_structural or not parsed.normalized:
            continue
        lines.append(
            Line(
                recipe=str(line.recipe_id),
                title=offerable[line.recipe_id],
                name=parsed.normalized,
                resolved=line.ingredient_id is not None,
                raw=line.raw_text,
            )
        )
    return rank(lines, limit=limit)


def as_yaml(found: list[Gap]) -> str:
    """Stubs shaped like `db/ingredients.yaml`, ready to review and paste.

    `name` is left as the normalised string rather than title-cased: the
    reviewer has to read it anyway, and a machine-made capital would look like
    a decision somebody made.
    """
    if not found:
        return "# Rien à combler : toute ligne offrable résout.\n"

    lines = [
        "# Proposé, pas décidé — à relire avant de coller dans db/ingredients.yaml.",
        "# `allergens` est vide partout : c'est le seul champ qui puisse blesser",
        "# quelqu'un, et aucune correspondance de chaîne n'a d'avis dessus.",
        "",
    ]
    for gap in found:
        lines.append(
            f"  # {gap.completes} recette(s) complétée(s), "
            f"{gap.occurrences} occurrence(s)"
        )
        if gap.example:
            lines.append(f"  # ex. : {gap.example}")
        for raw in gap.raw:
            lines.append(f"  #   source : {raw}")
        lines.append(f"  - name: {gap.name}")
        lines.append(f"    aliases: [{gap.name}]")
        lines.append(f"    allergens: []        # {NEEDS_A_HUMAN}")
        lines.append(f"    categories: []       # {NEEDS_A_HUMAN}")
        lines.append("")
    return "\n".join(lines)


def render(found: list[Gap], *, total_blocked: int) -> str:
    """The human-readable side: what this list is worth before writing any of it."""
    if not found:
        return "Rien à combler : toute ligne offrable résout.\n"

    reachable = sum(gap.completes for gap in found)
    out = [
        f"{total_blocked} recettes offrables sont à UNE ligne d'être vérifiées.",
        f"Les {len(found)} entrées ci-dessous en débloqueraient {reachable}.",
        "",
    ]
    for gap in found:
        out.append(
            f"  {gap.completes:>3} recette(s)  ×{gap.occurrences:<3}  {gap.name[:48]}"
        )
    return "\n".join(out) + "\n"
