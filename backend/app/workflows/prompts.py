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

from app.domain.days import DAY_NAMES, LANGUAGE_NAMES
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
   product useless. This yields to rule 6: a repeat is still better than a meal
   nobody can eat.

   It also yields to a household that ASKS for a repeat under THIS WEEK —
   "a dish we'll eat two evenings", "something cooked once and served twice".
   Then you repeat ONE dish, on exactly TWO slots, and preferably consecutive
   ones; every other slot still gets a dish of its own. Cooking once and eating
   twice is the point of this product, so honour it exactly — a household that
   asked for one repeat and received four got neither variety nor a batch.
9. Do not use any title listed under ALREADY SERVED, nor a reworded version of
   it. Those meals were eaten in the last three weeks. You know more dishes
   than the ones that come to mind first — reach for them. A title comes back
   into play once it leaves that list.
10. Write every dish title and serving variant in the language given under
   LANGUAGE. These strings are shown to the household as-is — they are not
   translated afterwards.

Answer with identifiers and short titles only. No explanation, no commentary, no
reasoning — a separate call handles that.
"""

#: Instructions are stable and cacheable, so the language cannot be baked into
#: them: it travels with the request instead.
#:
#: The day names come from the domain rather than being spelled again here. The
#: prompt writes `day 1 = mardi` and `skip_slot` reads `mardi` back to cancel a
#: slot; two copies of that table is two chances for the week the household
#: reads and the week the planner builds to disagree.


def build_context(
    *,
    spec: Sequence[SlotSpec],
    prompt_context: PromptContext,
    language: str = "fr",
    user_constraints: Sequence[str] = (),
    candidate_lines: Sequence[str] = (),
    catalogue_signals: Sequence[str] = (),
    forbidden: Sequence[str] = (),
    rotation: Sequence[str] = (),
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

    # The DAY IS NAMED, in the household's language. It used to read `day 1
    # dinner`, and the free-text intent reads "je rentre tard du mardi au
    # vendredi" — nothing in the prompt connected the two, so the model was
    # asked to honour a request about Tuesday without being told which slot
    # Tuesday was. Measured: the effort it put into weeknights and weekends was
    # identical, 1.85 against 2.02 on a scale of three.
    # BOTH the name and the index, and the honest history of this line is worth
    # keeping. The household writes "je rentre tard du mardi au vendredi" and
    # the prompt read `day 1 dinner`, so the hypothesis was that nothing
    # connected the two. Naming the day INSTEAD of numbering it was a
    # regression — the output schema wants `day_of_week` as an integer, so the
    # model had to guess it: three attempts every run, `duplicate_slot`,
    # `missing_slot` and `unknown_slot` on five runs out of five.
    #
    # Naming it AS WELL fixed the regression and changed nothing else: the
    # effort gap stayed at zero. The hypothesis was wrong — this model does not
    # honour a free-text preference about the SHAPE of the week, and it is not
    # for want of knowing which day is Tuesday. Kept anyway, because it is
    # strictly more information for ten tokens, and a better model may use it.
    names = DAY_NAMES.get(language, DAY_NAMES["en"])
    slots = "\n".join(
        f"- day {slot.day_of_week} = {names[slot.day_of_week]}, {slot.meal_type}: "
        f"{', '.join(slot.eater_aliases)}"
        for slot in spec
    )
    blocks.append(f"SLOTS TO FILL\n{slots}")

    if user_constraints:
        blocks.append("THIS WEEK\n" + "\n".join(f"- {line}" for line in user_constraints))

    if recent_meals:
        # Stated as an exclusion, not as a preference. Measured on qwen3:8b:
        # presented as a soft signal, a second week reused 7 of its 7 dishes
        # from the first; presented as a list not to draw from, the same model
        # produced 7 new ones. It reaches past the obvious answers only when
        # the obvious answers are gone.
        #
        # The window is what keeps this from starving: a title leaves the list
        # after three weeks and becomes available again, which is a rotation
        # rather than a ban.
        blocks.append(
            "ALREADY SERVED — do not use these titles, nor reworded versions\n"
            + "\n".join(f"- {meal}" for meal in sorted(set(recent_meals)))
        )

    if candidate_lines:
        blocks.append(
            "CANDIDATES — you may ONLY choose from these\n"
            + "\n".join(f"- {line}" for line in candidate_lines)
        )

    # NOT a signal — a hard fact, and the model is told it plainly because it
    # cannot derive it. The eater list says "m3 is gluten-intolerant" and the
    # candidate list shows five ingredients per dish; nothing connects the two,
    # so the model was being asked to respect a constraint whose data it did
    # not have. Measured before this block existed: gluten served to a
    # gluten-intolerant eater on 6 slots out of 9, reproducibly.
    #
    # The deterministic check still runs afterwards (§6.2 step 4). This only
    # gives the model a chance to be right the first time; it never replaces
    # the verdict.
    if forbidden:
        blocks.append(
            "MUST NOT BE SERVED — these eaters cannot eat these dishes. This is "
            "not a preference: a plan that breaks it is rejected.\n"
            + "\n".join(f"- {line}" for line in forbidden)
        )

    # Soft, and worded so. §6.3 is explicit that nutritional rotation is a wish,
    # not a constraint: "some pulses would be good this week" must yield to a
    # teenager who hates lentils and a vegetarian dish already on the plan.
    # Forcing it in SQL would produce mechanical menus.
    if rotation:
        blocks.append(
            "ROTATION — how long since each kind of food was last eaten here. "
            "A long gap is worth filling, but variety and what the household "
            "actually likes come first.\n" + " · ".join(rotation)
        )

    # A soft signal, and the block says so in as many words. Overlap is worth
    # money — one shopping trip, one base cooked twice — but a household that
    # wants variety must win against it, so it is written as an opportunity and
    # never as an instruction.
    if catalogue_signals:
        blocks.append(
            "SHARED BASES — these candidates use several of the same "
            "ingredients. Reusing one across the week saves shopping and "
            "cooking, but variety matters more than saving; treat this as an "
            "opportunity, not a rule.\n"
            + "\n".join(f"- {group}" for group in catalogue_signals)
        )

    return "\n\n".join(blocks)


INTERPRETATION_INSTRUCTIONS = """\
You turn a household's free-text note about their week into structured planning
constraints.

Extract only what the text actually says. Never invent a constraint, never infer
a preference that was not expressed.

People often write to you as if talking to someone — "I have no idea what to
cook, can you suggest something, I won't have much time". THAT IS STILL A NOTE
ABOUT THEIR WEEK. Asking you for help is not a constraint and yields nothing,
but the rest of the same sentence usually is one: extract it. Measured on this
exact input, the whole note was returned as empty because it was phrased as a
request. A note is only empty when it truly states nothing about the week.

The kinds, and what each one is for:

- `time_budget` — how much time or energy there is to cook. "I get home late on
  Tuesday", "quick meals on weeknights", "I have time at the weekend".
- `avoid` — a FOOD not to serve this week. An ingredient or a dish, never a day
  and never a moment. "no fish", "we've had too much pasta".
- `prefer` — a food or a style they would like. "something with vegetables".
- `leftover` — a food already in the kitchen to use up. "there's ham left".
- `skip_slot` — a meal not to plan at all. "we're out on Friday night".
- `repeat` — a wish to cook one dish once and eat it twice. "a dish we'll have
  two evenings", "something in a big batch". `detail` is how many times when
  they say, otherwise leave it out.
- `other` — anything real that fits none of the above.

`detail` carries the specific value and nothing else: an ingredient for `avoid`,
`prefer` and `leftover`; a day or a duration for `time_budget` and `skip_slot`.
A day never belongs in an `avoid` — "Tuesday I get home late" is a
`time_budget` whose detail is the day.

Write `label` in the SAME LANGUAGE as the input. The household reads this list
back and corrects it before anything is generated, so a French note must come
back in French.

A missing constraint is cheaper than a wrong one, but an empty list on a note
that said something is the failure this prompt exists to avoid.

Worked examples. The first is the one this model kept getting wrong — a request
addressed to you, wrapped around a real constraint:

  "Je n'ai pas d'idée pour cette semaine et je n'aurai pas beaucoup de temps,
   est-ce que tu peux me faire des propositions ?"
  -> [{"kind": "time_budget", "label": "peu de temps cette semaine",
       "detail": "cette semaine"}]
  Having no idea is not a constraint, and asking for suggestions is what the
  product does anyway. Having little time IS one, and it changes the week.

  "mardi je rentre tard, il reste du jambon"
  -> [{"kind": "time_budget", "label": "retour tardif mardi", "detail": "mardi"},
      {"kind": "leftover", "label": "jambon à finir", "detail": "jambon"}]
  Note the shape: `label` is the summary a human reads back, `detail` is the
  bare value the planner uses — the day, the ingredient. Never the reverse.

  "coucou"
  -> []
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
                            "repeat",
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
