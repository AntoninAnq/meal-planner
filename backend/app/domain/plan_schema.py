"""The arbitration contract: what the model is allowed to emit, and how we read it.

The LLM emits IDENTIFIERS, never prose. A week plan is
~200-300 output tokens, which is what makes a synchronous endpoint tenable at
all. Explanations are a separate, on-demand call — and not before V1, since in
V0 there would be nothing real to explain.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import MealType
from app.domain.planning import ProposedDish, ProposedSlot

MEAL_TYPES = [meal_type.value for meal_type in MealType]


def plan_output_schema(*, with_catalogue: bool) -> dict[str, Any]:
    """JSON Schema constraining the arbitration output.

    `with_catalogue=False` is V0: no recipe exists, so the model proposes titles.
    `with_catalogue=True` is V1: the model may only pick identifiers out of the
    candidate set, and `validate_proposal` enforces that it did.
    """
    dish_properties: dict[str, Any] = {
        "eaters": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            # Aliases (`m1`, `m2`), never member ids — invariant I5.
            "description": "Aliases of the members eating this dish.",
        },
        "serving_variants": {
            # An array of pairs rather than an object keyed by alias: a JSON
            # Schema object with arbitrary keys cannot also say
            # additionalProperties=false, and models handle arrays far more
            # reliably than free-form maps.
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "eater": {"type": "string"},
                    "variant": {
                        "type": "string",
                        "description": "How to serve this eater: 'sans olives', "
                        "'part prélevée avant salage et mixée'.",
                    },
                    "remove": {
                        # Names, not free text, and not new identifiers: the
                        # model copies them from the candidate line it was
                        # shown, and the code checks each one belongs to that
                        # recipe. Measured reason for the check: asked in prose
                        # for an aversion, this model wrote "sans tomate" next
                        # to an eater on nine dishes, several holding no tomato.
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ingredients to leave out for this eater. "
                        "Each MUST be copied exactly from this recipe's own "
                        "ingredient list. Omit rather than guess.",
                    },
                },
                "required": ["eater", "variant"],
                "additionalProperties": False,
            },
        },
    }

    if with_catalogue:
        dish_properties["recipe_id"] = {
            "type": "string",
            "description": "Must be one of the candidate identifiers provided.",
        }
        dish_required = ["recipe_id", "eaters"]
    else:
        dish_properties["label"] = {
            "type": "string",
            "description": "Short dish title, e.g. 'Poulet aux olives'.",
        }
        dish_required = ["label", "eaters"]

    return {
        "type": "object",
        "properties": {
            "slots": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day_of_week": {"type": "integer", "minimum": 0, "maximum": 6},
                        "meal_type": {"type": "string", "enum": MEAL_TYPES},
                        "dishes": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": dish_properties,
                                "required": dish_required,
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["day_of_week", "meal_type", "dishes"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["slots"],
        "additionalProperties": False,
    }


def parse_proposal(data: dict[str, Any]) -> list[ProposedSlot]:
    """Turn schema-valid output into domain objects.

    The payload has already been validated against the schema by the LLM client,
    so this only maps shapes. Semantic checks belong to `validate_proposal` —
    keeping the two apart is what lets the envelope check be tested without ever
    touching a model.
    """
    slots: list[ProposedSlot] = []

    for raw_slot in data.get("slots", []):
        dishes = tuple(
            ProposedDish(
                eater_aliases=tuple(raw_dish.get("eaters", [])),
                label=raw_dish.get("label"),
                recipe_id=raw_dish.get("recipe_id"),
                serving_variants={
                    variant["eater"]: variant["variant"]
                    for variant in raw_dish.get("serving_variants", [])
                },
                variant_removals={
                    variant["eater"]: tuple(variant.get("remove") or ())
                    for variant in raw_dish.get("serving_variants", [])
                    if variant.get("remove")
                },
            )
            for raw_dish in raw_slot.get("dishes", [])
        )
        slots.append(
            ProposedSlot(
                day_of_week=raw_slot["day_of_week"],
                meal_type=MealType(raw_slot["meal_type"]),
                dishes=dishes,
            )
        )

    return slots
