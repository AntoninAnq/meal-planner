"""Prompt text for the planning workflow.

Split deliberately in two, matching `LLMClient.complete_structured`:

* `instructions` — stable across every request, therefore cacheable by the cloud
  API. Never interpolate anything per-request into it.
* `context` — the candidates, signals and eaters of this particular call.

Merging them into a single prompt would close the prompt-caching door for good.

Nothing here ever receives a `member` entity: eaters are aliases (`m1`, `m2`),
constraints are codes and tags (invariant I5).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.planning import SlotSpec
from app.domain.prompt_context import PromptContext

ARBITRATION_INSTRUCTIONS = """\
You plan family meals for a household where members do not all eat the same thing.

Your job is to fill every requested slot and to assign every eater at that slot to
exactly one dish. You are given each eater's life stage and constraints, plus soft
signals about what the household has eaten recently.

LIFE STAGES, and what each one means for a plate. This vocabulary is fixed:

- `teen_adult` eats the dish as prepared.
- `young_child` eats the same dish, but strong spice, heavy seasoning, alcohol,
  whole nuts and very firm textures need a serving variant.
- `baby` CANNOT eat an adult plate as served. A baby always needs either a
  serving variant — a portion set aside before salting and mashed, vegetables
  cooked soft and blended — or a dish of their own. Assigning a baby to a dish
  with no variant and no reason is the single most common mistake here, and it
  is always wrong.

Rules you must follow:

1. Fill every slot you are given, exactly once. Never invent a slot.
2. At each slot, every eater listed eats exactly one dish. Nobody is left out,
   nobody eats twice.
3. Prefer FEWER distinct dishes. Cooking twice is the problem this product
   exists to solve. One dish everyone can eat is the best outcome — but "can
   eat" means AS SERVED TO THEM, for their own life stage. One dish plus a
   serving variant still counts as one dish.
4. When someone cannot eat the main dish as served, prefer a SERVING VARIANT over
   a second dish. Same preparation, different plate — that costs no extra
   cooking and is better than a separate dish.

   A variant goes in the `serving_variants` field of the dish that eater is
   already assigned to. It NEVER goes in the title, and it is NEVER a second
   dish carrying the same title. One dish for the three of them, with the baby
   on `serving_variants`, looks like this:

       {"label": "Poulet rôti aux légumes",
        "eater_aliases": ["m1", "m2", "m3"],
        "serving_variants": [{"eater": "m3",
                              "variant": "part prélevée avant salage et mixée"}]}

   Producing three dishes all titled "Poulet rôti aux légumes" is the same meal
   written three times: it tells the household to cook three times for one pot.
5. Only add a second dish when no variant can work — and a second dish always
   has a DIFFERENT title from the first.
6. Respect hard constraints absolutely. An excluded allergen must not appear in
   any dish at that slot, for anyone.
7. Treat the soft signals as preferences, not orders. They should yield to
   anything that would make a meal unappealing or impossible.

8. Every slot gets a DIFFERENT dish. Nobody wants the same dinner seven nights
   running, and a plan that repeats itself is the one thing that makes this
   product useless. Also avoid dishes listed as recently eaten. This yields to
   rule 6: a repeat is still better than a meal nobody can eat.
9. Write every dish title and serving variant in the language given under
   LANGUAGE. These strings are shown to the household as-is — they are not
   translated afterwards.

Answer with identifiers and short titles only. No explanation, no commentary, no
reasoning — a separate call handles that.
"""

#: Instructions are stable and cacheable, so the language cannot be baked into
#: them: it travels with the request instead.
LANGUAGE_NAMES = {"fr": "French", "en": "English"}


def build_context(
    *,
    spec: Sequence[SlotSpec],
    prompt_context: PromptContext,
    language: str = "fr",
    user_constraints: Sequence[str] = (),
    candidate_lines: Sequence[str] = (),
    recent_meals: Sequence[str] = (),
) -> str:
    """Assemble the per-request half of the prompt."""
    blocks: list[str] = [f"LANGUAGE\n{LANGUAGE_NAMES.get(language, language)}"]

    eaters = "\n".join(
        f"- {member.alias}: stage={member.life_stage}"
        + (f", intolerances={','.join(member.intolerances)}" if member.intolerances else "")
        + (f", dislikes={','.join(member.aversion_tags)}" if member.aversion_tags else "")
        for member in prompt_context.members
    )
    blocks.append(f"EATERS\n{eaters}")

    if prompt_context.household_excluded_allergens:
        # Severe allergy excludes the allergen for EVERYONE, so it is
        # stated once for the whole prompt rather than per member.
        excluded = ", ".join(prompt_context.household_excluded_allergens)
        blocks.append(f"EXCLUDED FOR EVERYONE (hard)\n{excluded}")

    slots = "\n".join(
        f"- day {slot.day_of_week} {slot.meal_type}: {', '.join(slot.eater_aliases)}"
        for slot in spec
    )
    blocks.append(f"SLOTS TO FILL\n{slots}")

    if user_constraints:
        blocks.append("THIS WEEK\n" + "\n".join(f"- {line}" for line in user_constraints))

    if prompt_context.rotation_signals:
        signals = "\n".join(
            f"- {category}: {days} days since last time"
            for category, days in sorted(prompt_context.rotation_signals.items())
        )
        blocks.append(f"SOFT SIGNALS\n{signals}")

    if recent_meals:
        blocks.append(
            "RECENTLY EATEN (avoid repeating, soft)\n"
            + "\n".join(f"- {meal}" for meal in recent_meals)
        )

    if candidate_lines:
        blocks.append(
            "CANDIDATES — you may ONLY choose from these\n"
            + "\n".join(f"- {line}" for line in candidate_lines)
        )

    return "\n\n".join(blocks)


INTERPRETATION_INSTRUCTIONS = """\
You turn a household's free-text note about their week into structured planning
constraints.

Extract only what the text actually says. Never invent a constraint, never infer
a preference that was not expressed. If the text says nothing useful, return an
empty list — that is a valid and common answer.

Each constraint carries:
- kind: one of `time_budget`, `avoid`, `prefer`, `leftover`, `skip_slot`, `other`
- label: a short human-readable summary, in the language of the input
- detail: the specific value when there is one (a day, an ingredient, a duration)

The user will see and correct this list before anything is generated, so a
missing constraint is far cheaper than a wrong one.
"""

INTERPRETATION_SCHEMA = {
    "type": "object",
    "properties": {
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "time_budget",
                            "avoid",
                            "prefer",
                            "leftover",
                            "skip_slot",
                            "other",
                        ],
                    },
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["kind", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["constraints"],
    "additionalProperties": False,
}
