"""Run the frozen cases against a model, and report rates rather than verdicts.

`ARCHITECTURE.md` §14. Three properties this file exists to hold:

**A separate database.** A harness that reads production cannot compare
anything over time — the catalogue grows, the history changes, and October's
score is not December's. So the fixtures are loaded into a database of their
own, dropped and rebuilt on every run.

**N runs per case, never one.** A single run measures nothing on a stochastic
system: the same model on the same case can pass then fail. A golden that
passes one time in two and gets re-run until green is worse than no golden.

**Hard invariants at zero, everything else as a rate.** An allergen violation
is not a percentage. A dish outside the candidate set is not a percentage.
Everything else — how often a shared base is reused, how many dishes a slot
gets — is a tendency, and reporting it as pass/fail would invent a precision
the system does not have.

    docker compose run --rm --no-deps \\
        -v "$PWD/eval:/eval" -v "$PWD/db:/db:ro" -w / api \\
        python /eval/run.py --runs 5

The model comes from the environment (`LLM_PROVIDER`, `OLLAMA_MODEL`), so
comparing two models is two runs with one variable changed — which is the whole
point of the exercise.
"""

from __future__ import annotations

import argparse
import pathlib
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = pathlib.Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
CASES = ROOT / "cases"

#: A fixed Monday. The pre-filter seeds its ranking on the week, so pinning it
#: is what makes two runs of the harness comparable at all.
WEEK = date(2026, 3, 2)

#: Namespace for fixture recipe ids. Derived from the fixture key so the same
#: recipe always gets the same UUID — which is what lets a golden name
#: `candidates_after_filters` by identifier instead of by position.
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def recipe_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, key)


# ---------------------------------------------------------------------------
# The eval database
# ---------------------------------------------------------------------------


def build_database(name: str) -> sessionmaker[Session]:
    """Drop and recreate the eval database, then create the schema.

    `create_all` rather than Alembic on purpose: this database exists for the
    length of a run and is thrown away, so replaying twenty migrations to reach
    the same shape buys nothing. Migrations are exercised where they matter, on
    the real database.
    """
    from app.config import get_settings
    from app.db.models import Base

    settings = get_settings()
    admin = create_engine(settings.sqlalchemy_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    url = settings.sqlalchemy_url.rsplit("/", 1)[0] + f"/{name}"
    engine = create_engine(url)
    with engine.connect() as connection:
        for extension in ("unaccent", "pg_trgm"):
            connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        connection.commit()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def load_fixtures(db: Session) -> dict[str, Any]:
    """Referential, catalogue, households — then the same derivations as prod.

    The allergens are NOT written from the fixture: they are derived from the
    ingredients by the real resolution pass, exactly as they are in production.
    A fixture that declared its own allergens would be testing the fixture.
    """
    from app.catalog.complexity import derive as derive_complexity
    from app.catalog.referential import load_referential, spelling_index
    from app.catalog.ingredient_lines import normalise
    from app.catalog.resolution import resolve
    from app.db.models import (
        DietaryConstraint,
        Household,
        HouseholdSettings,
        MealSlotConfig,
        Member,
        Recipe,
        RecipeIngredient,
        RecipeSuitableStage,
    )
    from app.domain.enums import (
        AllergenCode,
        ConstraintSeverity,
        DishType,
        LifeStage,
        MealType,
        RecipeSourceType,
    )

    load_referential(db, pathlib.Path("/db/ingredients.yaml"))
    # Everything is confirmed here. The confirmation is a human act on the REAL
    # referential (I1); inside a fixture, leaving entries unconfirmed would only
    # measure how much of `db/confirmations.yaml` happens to be filled in.
    db.execute(text("UPDATE ingredient SET confirmed_at = now()"))
    db.commit()

    index = spelling_index(db)
    catalogue = yaml.safe_load((FIXTURES / "catalogue.yaml").read_text(encoding="utf-8"))

    for entry in catalogue["recipes"]:
        recipe = Recipe(
            id=recipe_uuid(entry["id"]),
            title=entry["title"],
            # Ours, written here — not scraped, not licensed. That is what
            # keeps I9 and I7 out of this file entirely.
            source_type=RecipeSourceType.USER,
            prep_minutes=entry["prep_minutes"],
            cook_minutes=entry["cook_minutes"],
            step_count=entry["step_count"],
            servings=entry["servings"],
            dish_type=DishType(entry["dish_type"]),
        )
        db.add(recipe)
        db.flush()
        for position, name in enumerate(entry["ingredients"]):
            match = index.get(normalise(name))
            db.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    position=position,
                    raw_text=name,
                    ingredient_id=match[0] if match else None,
                )
            )
        for stage in (LifeStage.YOUNG_CHILD, LifeStage.TEEN_ADULT):
            db.add(RecipeSuitableStage(recipe_id=recipe.id, life_stage=stage))
    db.commit()

    resolve(db)
    derive_complexity(db)

    households = yaml.safe_load((FIXTURES / "households.yaml").read_text(encoding="utf-8"))
    built: dict[str, Any] = {}
    for spec in households["households"]:
        household = Household(name=spec["key"])
        db.add(household)
        db.flush()
        db.add(HouseholdSettings(household_id=household.id))

        aliases: dict[str, uuid.UUID] = {}
        for entry in spec["members"]:
            member = Member(
                household_id=household.id,
                display_name=entry["alias"],
                life_stage=LifeStage(entry["life_stage"]),
            )
            db.add(member)
            db.flush()
            aliases[entry["alias"]] = member.id

        for entry in spec["constraints"]:
            db.add(
                DietaryConstraint(
                    household_id=household.id,
                    member_id=aliases[entry["member"]],
                    allergen_code=AllergenCode(entry["allergen_code"]),
                    severity=ConstraintSeverity(entry["severity"]),
                )
            )

        # The default grid of §4.7: weekday dinners plus the full weekend.
        for day in range(7):
            db.add(
                MealSlotConfig(
                    household_id=household.id,
                    day_of_week=day,
                    meal_type=MealType.DINNER,
                    enabled=True,
                )
            )
            if day >= 5:
                db.add(
                    MealSlotConfig(
                        household_id=household.id,
                        day_of_week=day,
                        meal_type=MealType.LUNCH,
                        enabled=True,
                    )
                )
        built[spec["key"]] = household.id
    db.commit()

    total = db.scalar(select(text("count(*)")).select_from(Recipe.__table__))
    verified = db.scalar(
        select(text("count(*)")).select_from(Recipe.__table__).where(Recipe.allergens_verified)
    )
    print(f"catalogue de test : {total} recettes, {verified} vérifiées")
    return built


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    seconds: float
    attempts: int
    input_tokens: int
    output_tokens: int
    dishes: int
    distinct_dishes: int
    max_dishes_per_slot: int
    #: How many candidates survived the pre-filter. Reported because a case can
    #: pass every assertion while having almost nothing to choose from.
    pool_size: int = 0
    #: Slots carrying more than one dish. The product's whole premise, and the
    #: only way to see whether it ever happens.
    slots_with_two_dishes: int = 0
    violations: list[str] = field(default_factory=list)
    allergen_violations: int = 0
    outside_candidates: int = 0
    overlap_followed: bool = False
    failed: str | None = None


def one_run(session_factory: sessionmaker[Session], household_id: uuid.UUID) -> RunResult:
    from app.db.models import DietaryConstraint, PlannedDish, PlannedDishMember, RecipeAllergen
    from app.domain.enums import ConstraintSeverity
    from app.llm.factory import get_llm_client
    from app.services import planning_service as ps

    with session_factory() as db:
        started = time.monotonic()
        try:
            plan, outcome = ps.generate_plan(
                db, household_id=household_id, llm=get_llm_client(), week_start=WEEK
            )
        except Exception as exc:  # noqa: BLE001 — a failed run is a datum
            return RunResult(
                seconds=time.monotonic() - started,
                attempts=0,
                input_tokens=0,
                output_tokens=0,
                dishes=0,
                distinct_dishes=0,
                max_dishes_per_slot=0,
                failed=f"{type(exc).__name__}: {exc}"[:120],
            )
        seconds = time.monotonic() - started

        dishes = list(db.scalars(select(PlannedDish).where(PlannedDish.meal_plan_id == plan.id)))
        per_slot: dict[tuple[int, str], int] = {}
        for dish in dishes:
            key = (dish.day_of_week, dish.meal_type)
            per_slot[key] = per_slot.get(key, 0) + 1

        pool = ps.catalogue_for(db, household_id=household_id, week_start=WEEK).pool_size

        # The safety check, done independently of the pipeline that produced the
        # plan: this is the one number that must be zero, so it is not read back
        # from the code under test.
        #
        # BOTH severities. A first version counted only severe allergies and
        # reported "0, OK" on a run where the pipeline had itself raised ten
        # `allergen_for_eater` violations — the harness's most load-bearing
        # number, wrong by omission. A severe allergy is excluded from the pool
        # by the pre-filter, so counting it alone measures the easy half.
        excluded: dict[uuid.UUID, set[str]] = {}
        for constraint in db.scalars(
            select(DietaryConstraint).where(
                DietaryConstraint.household_id == household_id,
                DietaryConstraint.severity.in_(
                    [ConstraintSeverity.SEVERE_ALLERGY, ConstraintSeverity.INTOLERANCE]
                ),
            )
        ):
            if constraint.allergen_code and constraint.member_id:
                excluded.setdefault(constraint.member_id, set()).add(
                    constraint.allergen_code.value
                )

        carried: dict[uuid.UUID, set[str]] = {}
        for row in db.scalars(select(RecipeAllergen)):
            carried.setdefault(row.recipe_id, set()).add(row.allergen_code.value)

        breaches = 0
        by_dish = {dish.id: dish for dish in dishes}
        for assignment in db.scalars(
            select(PlannedDishMember).where(
                PlannedDishMember.planned_dish_id.in_([d.id for d in dishes] or [None])
            )
        ):
            dish = by_dish.get(assignment.planned_dish_id)
            if dish is None or dish.recipe_id is None:
                continue
            if carried.get(dish.recipe_id, set()) & excluded.get(assignment.member_id, set()):
                breaches += 1

        codes = [violation.code for violation in outcome.violations]
        return RunResult(
            seconds=seconds,
            attempts=outcome.attempts,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            dishes=len(dishes),
            distinct_dishes=len({d.recipe_id or d.free_text_label for d in dishes}),
            max_dishes_per_slot=max(per_slot.values(), default=0),
            violations=codes,
            allergen_violations=breaches,
            outside_candidates=codes.count("dish_outside_candidates"),
            pool_size=pool,
            slots_with_two_dishes=sum(1 for count in per_slot.values() if count > 1),
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _check(label: str, expected: Any, observed: float) -> bool:
    """Hard invariants compare to a number; tendencies to `<= n` / `>= n`."""
    if isinstance(expected, int):
        passed = observed == expected
        rendered = str(expected)
    else:
        operator, _, value = str(expected).partition(" ")
        threshold = float(value)
        passed = observed <= threshold if operator == "<=" else observed >= threshold
        rendered = str(expected)
    print(f"  {label:<22} {observed:<8g} attendu {rendered:<8} {'OK' if passed else 'ÉCHEC'}")
    return passed


def report(case: str, runs: list[RunResult], golden: dict[str, Any]) -> None:
    ok = [run for run in runs if run.failed is None]
    expected = golden.get("expected_properties") or {}
    empty_expected = bool((golden.get("expected_exact") or {}).get("plan_is_empty"))

    print(f"\n=== {case}  ({len(ok)}/{len(runs)} exécutions abouties)")

    if empty_expected:
        # Not a failure: this household has no plannable member, and refusing
        # to invent a meal IS the expected answer (§6.4).
        refused = [run for run in runs if run.failed and "catalogue yet" in run.failed]
        print(
            f"  plan vide              {len(refused)}/{len(runs)} "
            f"{'OK' if len(refused) == len(runs) else 'ÉCHEC'}"
        )
        if ok:
            print("  ÉCHEC : un plan a été produit pour un foyer que rien ne peut nourrir")
        return

    if not ok:
        print(f"  échec : {runs[0].failed}")
        return

    seconds = statistics.median(run.seconds for run in ok)
    attempts = statistics.mean(run.attempts for run in ok)
    print(f"  latence médiane      {seconds:6.1f} s")
    print(f"  tentatives moyennes  {attempts:6.2f}")
    print(
        f"  tokens               in {statistics.mean(r.input_tokens for r in ok):.0f}"
        f" / out {statistics.mean(r.output_tokens for r in ok):.0f}"
    )
    print(f"  candidats            {ok[0].pool_size}")

    # The two that are not rates, checked against the golden rather than
    # against a constant written here.
    if "allergen_violations" in expected:
        _check("violations allergène", expected["allergen_violations"],
               sum(run.allergen_violations for run in ok))
    if "dishes_outside_candidates" in expected:
        _check("hors candidats", expected["dishes_outside_candidates"],
               sum(run.outside_candidates for run in ok))
    if "max_dishes_per_slot" in expected:
        _check("max plats / créneau", expected["max_dishes_per_slot"],
               max(run.max_dishes_per_slot for run in ok))
    if "distinct_dishes" in expected:
        _check("plats distincts", expected["distinct_dishes"],
               statistics.mean(run.distinct_dishes for run in ok))
    if "candidates_minimum" in expected:
        _check("candidats", f">= {expected['candidates_minimum']}", ok[0].pool_size)
    if "slots_with_two_dishes" in expected:
        _check("créneaux à 2 plats", expected["slots_with_two_dishes"],
               statistics.mean(run.slots_with_two_dishes for run in ok))

    counts: dict[str, int] = {}
    for run in ok:
        for code in run.violations:
            counts[code] = counts.get(code, 0) + 1
    if counts:
        rates = ", ".join(f"{code} {n}/{len(ok)}" for code, n in sorted(counts.items()))
        print(f"  violations           {rates}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="runs per case (§14.3: 5 minimum)")
    parser.add_argument("--case", help="run a single household key")
    parser.add_argument("--database", default="meal_eval", help="scratch database name")
    args = parser.parse_args()

    if args.runs < 5 and not args.case:
        print("⚠ moins de 5 exécutions : le résultat ne mesure rien (§14.3)")

    session_factory = build_database(args.database)
    with session_factory() as db:
        households = load_fixtures(db)

    for key, household_id in households.items():
        if args.case and key != args.case:
            continue
        golden_path = CASES / f"{key}.yaml"
        golden = (
            yaml.safe_load(golden_path.read_text(encoding="utf-8"))
            if golden_path.is_file()
            else {}
        )
        runs = [one_run(session_factory, household_id) for _ in range(args.runs)]
        report(key, runs, golden)


if __name__ == "__main__":
    main()
