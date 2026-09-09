"""The back office, and the one gate in front of all of it.

It exists for judgement no rule reaches. `Tartes, Clafoutis` is the case that
settled the argument: the rubric groups an onion tart with a strawberry one, so
`db/dish_types.yaml` maps it to nothing on purpose, and a dessert tart ends up
offered as an alternative for a Thursday dinner. Only a person looking at one
recipe can tell those apart.

**Every route here takes `CurrentOperator` INSTEAD of `CurrentHousehold`**, and
`tests/test_admin_authorisation.py` walks this module to enforce it. That is
the whole defence: a back office is new surface reachable from the internet,
and the route that gets left unguarded is never the one being looked at.

Granting is separated behind `CurrentOwner`. Recruiting help to retag is the
point; letting a helper recruit — or remove the person who invited them — is
not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import actions
from app.auth.deps import CurrentOperator, CurrentOwner
from app.config import Settings, get_settings
from app.db.models import (
    HouseholdAccess,
    Ingredient,
    Operator,
    Recipe,
    RecipeIngredient,
    SuggestionReport,
)
from app.db.session import get_db
from app.domain.enums import DishType, OperatorLevel, ReportCategory
from app.domain.support_code import looks_like_code, normalise, support_code

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

router = APIRouter(prefix="/admin", tags=["admin"])


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    auth_subject: str
    level: OperatorLevel
    granted_at: datetime
    granted_by: str | None
    #: The code this person reads in their own settings screen, so a list of
    #: operators can be compared to what someone sent you. `auth_subject` is a
    #: twenty-one digit Google identifier: correct, unique, and impossible to
    #: recognise on a screen — granting by code and revoking by identifier would
    #: mean removing a row nobody can put a person behind.
    #:
    #: None when the identity has no live household access — revoked, or an
    #: operator whose household was removed. Blank rather than wrong.
    support_code: str | None


def with_support_code(db: Session, operator: Operator) -> OperatorOut:
    access = db.get(HouseholdAccess, operator.auth_subject)
    code = (
        support_code(access.household_id)
        if access is not None and access.revoked_at is None
        else None
    )
    return OperatorOut(
        auth_subject=operator.auth_subject,
        level=operator.level,
        granted_at=operator.granted_at,
        granted_by=operator.granted_by,
        support_code=code,
    )


class GrantRequest(BaseModel):
    """Who to let in, named by the code they read in their own settings screen.

    Not an email, and not because one was forgotten: none is stored (§11.7).
    The person signs in with Google first, reads their support code, and sends
    it over by any channel. The right is then granted to an identity Google has
    already verified — rather than to an address someone typed, which is the
    weaker thing to trust.
    """

    support_code: str = Field(min_length=8, max_length=16)
    level: OperatorLevel = OperatorLevel.CONTRIBUTOR


@router.get("/me", response_model=OperatorOut)
def me(db: DbDep, operator: CurrentOperator) -> OperatorOut:
    """Am I an operator, and at which level?

    Exists so the interface can show a way in without guessing. The alternative
    was a flag on `/household`, and it is the wrong place for the same reason
    the operator table is not a column on `household_access`: operating the
    instance is not a property of owning a household, and a reader looking at a
    household should not find one there.

    Answers 404 like everything else under `/admin`, so a household that is not
    an operator learns nothing — the absence of a link and the absence of the
    page say the same thing.
    """
    return with_support_code(db, operator)


@router.get("/operators", response_model=list[OperatorOut])
def list_operators(db: DbDep, operator: CurrentOperator) -> list[OperatorOut]:
    """Readable by any operator: a contributor should be able to see who else
    can change the catalogue they are working on."""
    rows = db.scalars(select(Operator).order_by(Operator.granted_at))
    return [with_support_code(db, row) for row in rows]


@router.post("/operators", response_model=OperatorOut, status_code=status.HTTP_201_CREATED)
def grant(payload: GrantRequest, db: DbDep, owner: CurrentOwner) -> OperatorOut:
    if not looks_like_code(payload.support_code):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "not a support code — expected eight hex characters",
        )

    wanted = normalise(payload.support_code)
    live = select(HouseholdAccess).where(HouseholdAccess.revoked_at.is_(None))
    matches = [
        access
        for access in db.scalars(live)
        if normalise(support_code(access.household_id)) == wanted
    ]
    if not matches:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no household with this support code")
    if len({access.household_id for access in matches}) > 1:
        # Eight hex characters can in principle name two households. Refusing is
        # the honest answer: granting to the wrong person is not recoverable by
        # the person who was granted nothing.
        raise HTTPException(status.HTTP_409_CONFLICT, "several households share this code")

    subject = matches[0].auth_subject
    existing = db.get(Operator, subject)
    if existing is not None:
        # Idempotent on the level, so re-granting is a correction and not an
        # error. `granted_by` follows, because who last decided is the useful
        # fact, not who decided first.
        existing.level = payload.level
        existing.granted_by = owner.auth_subject
        existing.granted_at = datetime.now(UTC)
        db.commit()
        return with_support_code(db, existing)

    operator = Operator(
        auth_subject=subject,
        level=payload.level,
        granted_by=owner.auth_subject,
    )
    db.add(operator)
    db.commit()
    return with_support_code(db, operator)


@router.delete("/operators/{auth_subject}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(auth_subject: str, db: DbDep, owner: CurrentOwner) -> None:
    """Remove the right to operate. The person keeps their household.

    Refuses to remove the last owner: an instance with no owner can never grant
    again, and the only way back is a shell on the production database. That is
    the kind of lockout a confirmation dialog does not prevent and a check does.
    """
    operator = db.get(Operator, auth_subject)
    if operator is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not an operator")

    if operator.level is OperatorLevel.OWNER:
        owners = db.scalars(
            select(Operator).where(Operator.level == OperatorLevel.OWNER)
        ).all()
        if len(owners) <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "the last owner cannot be removed: nobody could grant access again",
            )

    db.delete(operator)
    db.commit()


# -- The households -----------------------------------------------------------
#
# The other half of the back office, and a different kind of thing entirely.
# Everything below acts on PEOPLE rather than on the catalogue, so all of it is
# `CurrentOwner`: a contributor recruited to retag recipes has no business
# reading the list of households, and none of these verbs has anything to do
# with the work they were invited for.
#
# The logic is `app.admin.actions`, unchanged and unduplicated. Those functions
# already ran from a terminal on the worst nights; a second implementation
# behind HTTP would be a second set of edge cases, and the one that diverges is
# always the one nobody exercised.

#: How many households the screen shows. Ordered by recent spend, so the top of
#: the list is the reason anybody opened it. A complete list would grow with the
#: instance and be read by nobody.
HOUSEHOLDS_SHOWN = 25


class HouseholdOut(BaseModel):
    household_id: uuid.UUID
    #: What the person themselves reads in their settings screen — the only
    #: name both sides of a support conversation can say out loud.
    code: str
    name: str
    members: int
    #: Live identities, then cut-off ones. No email anywhere: none is stored.
    subjects: list[str]
    revoked: list[str]
    limit_override: int | None
    calls_in_window: int


class HouseholdsOut(BaseModel):
    """The rows, and the two numbers needed to read them.

    `limit_override` is null for most households, which means "on the rate
    card" — and a screen showing a blank there would be asking the operator to
    remember what the rate card says. It is sent once rather than per row.
    """

    default_limit: int
    window_hours: int
    households: list[HouseholdOut]


class LimitDecision(BaseModel):
    """Null clears the override; zero is a value.

    Zero stops the spend and leaves the weeks already generated readable — the
    softest useful sanction, and the right first move on a household that looks
    like a bot but might be a family with a slow week.
    """

    limit: int | None = Field(default=None, ge=0)


@router.get("/households", response_model=HouseholdsOut)
def households(
    db: DbDep,
    settings: SettingsDep,
    owner: CurrentOwner,
    code: Annotated[str | None, Query()] = None,
) -> HouseholdsOut:
    """Who is here, and who is spending — or the one household behind a code.

    The two questions an operator actually has, and they are the two commands
    the CLI grew: `list` and `find`. Searching by code goes to the server rather
    than filtering a list in the browser, so the page does not quietly depend on
    the instance being small.
    """
    window = settings.generation_window_hours
    if code is not None:
        try:
            rows = actions.find(db, code)
        except ValueError as bad:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(bad)) from bad
    else:
        rows = actions.survey(db, window_hours=window)[:HOUSEHOLDS_SHOWN]

    return HouseholdsOut(
        default_limit=settings.generation_daily_limit,
        window_hours=window,
        households=[
            HouseholdOut(
                household_id=row.household_id,
                code=row.code,
                name=row.name,
                members=row.members,
                subjects=list(row.subjects),
                revoked=list(row.revoked),
                limit_override=row.limit_override,
                calls_in_window=row.calls_in_window,
            )
            for row in rows
        ],
    )


@router.put("/households/{household_id}/limit", status_code=status.HTTP_204_NO_CONTENT)
def set_limit(
    household_id: uuid.UUID, payload: LimitDecision, db: DbDep, owner: CurrentOwner
) -> None:
    try:
        actions.set_limit(db, household_id, payload.limit)
    except actions.UnknownHousehold as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such household") from unknown


@router.post("/households/access/{auth_subject}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_access(auth_subject: str, db: DbDep, owner: CurrentOwner) -> None:
    """Cut an identity off. The access row SURVIVES, and that is the mechanism.

    `callback` provisions a household exactly when it finds no access row, so a
    delete would hand the identity that was just cut off a brand-new household
    on its next login.
    """
    try:
        actions.revoke(db, auth_subject)
    except actions.UnknownSubject as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such identity") from unknown


@router.post("/households/access/{auth_subject}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_access(auth_subject: str, db: DbDep, owner: CurrentOwner) -> None:
    try:
        actions.restore(db, auth_subject)
    except actions.UnknownSubject as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such identity") from unknown


# -- The retagging queue ----------------------------------------------------
#
# The reason the back office exists. `Tartes, Clafoutis` groups an onion tart
# with a strawberry one, so `db/dish_types.yaml` maps it to nothing on purpose
# and its recipes stay untyped — which is how a dessert tart came to be offered
# for a Thursday dinner. No rubric rule can be right for both; a person reading
# one title can.

#: How many the queue hands over at once. Enough to keep working without
#: refetching, short enough that a decision made now is on a row still on
#: screen.
QUEUE_PAGE = 25

#: What the ingredient list shows. Sweet or savoury is usually settled by the
#: first few, and a full list would turn a one-second judgement into reading.
INGREDIENTS_SHOWN = 8


class ToTypeOut(BaseModel):
    """One recipe, with what is needed to judge it and nothing more."""

    id: uuid.UUID
    title: str
    #: The rubric its source published. Usually the reason it is here: either
    #: absent, or one the mapping deliberately refuses to read.
    source_categories: list[str]
    source_url: str | None
    minutes: int | None
    ingredients: list[str]


class TypeDecision(BaseModel):
    dish_type: DishType


@router.get("/recipes/untyped", response_model=list[ToTypeOut])
def untyped(db: DbDep, operator: CurrentOperator) -> list[ToTypeOut]:
    """Recipes a meal slot may currently be offered, that nobody has classified.

    Withdrawn sources are out: a judgement spent on a site that answers 404
    buys nothing (0013). Verified recipes come first — they are the ones that
    reach a household with an allergy today, so a wrong type there costs the
    most.
    """
    recipes = list(
        db.scalars(
            select(Recipe)
            .where(Recipe.deprecated_at.is_(None), Recipe.dish_type.is_(None))
            .order_by(Recipe.allergens_verified.desc(), Recipe.title)
            .limit(QUEUE_PAGE)
        )
    )
    if not recipes:
        return []

    lines: dict[uuid.UUID, list[str]] = {}
    for recipe_id, name in db.execute(
        select(RecipeIngredient.recipe_id, Ingredient.canonical_name)
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(RecipeIngredient.recipe_id.in_([r.id for r in recipes]))
        .order_by(RecipeIngredient.position)
    ).all():
        lines.setdefault(recipe_id, []).append(name)

    return [
        ToTypeOut(
            id=recipe.id,
            title=recipe.title,
            source_categories=list(recipe.source_categories or []),
            source_url=recipe.source_url,
            minutes=(
                (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
                if recipe.prep_minutes is not None or recipe.cook_minutes is not None
                else None
            ),
            ingredients=lines.get(recipe.id, [])[:INGREDIENTS_SHOWN],
        )
        for recipe in recipes
    ]


@router.put("/recipes/{recipe_id}/dish-type", response_model=ToTypeOut)
def set_dish_type(
    recipe_id: uuid.UUID, payload: TypeDecision, db: DbDep, operator: CurrentOperator
) -> ToTypeOut:
    """Record a person's decision, and who made it.

    `dish_type_set_by` is what stops `catalog dish-types` from overwriting this
    on its next run — that pass rewrites every recipe from the rubric mapping,
    which is the property that makes a mapping change correctable and the one
    that would erase this work.

    A contributor may do this: it is the work the back office exists to
    delegate, it is reversible, and it hurts nobody.
    """
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such recipe")

    recipe.dish_type = payload.dish_type
    recipe.dish_type_set_by = operator.auth_subject
    recipe.dish_type_set_at = datetime.now(UTC)
    # Retagging IS the resolution `not_a_meal` was asking for, so the reports
    # close with it. Leaving them open would have the operator do the work and
    # then be asked to say they did it.
    _resolve_reports(db, recipe.id, operator.auth_subject)
    db.commit()

    return ToTypeOut(
        id=recipe.id,
        title=recipe.title,
        source_categories=list(recipe.source_categories or []),
        source_url=recipe.source_url,
        minutes=None,
        ingredients=[],
    )


# -- What households say is wrong -------------------------------------------


class ReportedOut(BaseModel):
    """One recipe households have complained about, and what they said.

    Grouped by recipe rather than listed per report: ten complaints about the
    same tart are one decision, and a queue that shows them ten times makes the
    operator read nine rows to learn nothing.
    """

    recipe_id: uuid.UUID
    title: str
    dish_type: DishType | None
    source_url: str | None
    #: How many DIFFERENT households said it. One row per household and recipe
    #: is enforced upstream, so this counts voices and not clicks.
    households: int
    categories: list[ReportCategory]
    notes: list[str]


@router.get("/reports", response_model=list[ReportedOut])
def reports(db: DbDep, operator: CurrentOperator) -> list[ReportedOut]:
    """Open reports, the loudest first.

    Only the unresolved ones: a resolved row survives so that the same recipe
    reported again reads as a second complaint rather than a first, but it has
    no business in the queue.
    """
    rows = db.execute(
        select(SuggestionReport, Recipe)
        .join(Recipe, Recipe.id == SuggestionReport.recipe_id)
        .where(SuggestionReport.resolved_at.is_(None))
        .order_by(SuggestionReport.created_at)
    ).all()

    grouped: dict[uuid.UUID, ReportedOut] = {}
    for report, recipe in rows:
        entry = grouped.get(recipe.id)
        if entry is None:
            entry = ReportedOut(
                recipe_id=recipe.id,
                title=recipe.title,
                dish_type=recipe.dish_type,
                source_url=recipe.source_url,
                households=0,
                categories=[],
                notes=[],
            )
            grouped[recipe.id] = entry
        entry.households += 1
        if report.category not in entry.categories:
            entry.categories.append(report.category)
        if report.note:
            entry.notes.append(report.note)

    return sorted(grouped.values(), key=lambda r: (-r.households, r.title))


@router.post("/recipes/{recipe_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
def withdraw(recipe_id: uuid.UUID, db: DbDep, operator: CurrentOperator) -> None:
    """Stop offering this recipe, and keep it.

    The same mechanism migration 0013 used on a whole dead source:
    `planned_dish.recipe_id` is `ondelete="RESTRICT"`, so a week already cooked
    would block a delete or lose the dish it records. Withdrawn rows stay, and
    `offerable()` keeps them out of every future plan.

    `catalog.ingest` clears `deprecated_at` on a successful re-scrape — which is
    right for a source that came back, and wrong for a recipe a person withdrew
    on its merits. Worth knowing before a crawl is run over a source that has
    had recipes withdrawn by hand.
    """
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such recipe")

    recipe.deprecated_at = datetime.now(UTC)
    _resolve_reports(db, recipe_id, operator.auth_subject)
    db.commit()


@router.post("/reports/{recipe_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(recipe_id: uuid.UUID, db: DbDep, operator: CurrentOperator) -> None:
    """Close the reports without changing the recipe — they were mistaken.

    Needed or the queue cannot be emptied, and a queue that only grows stops
    being read. The rows survive marked resolved, so the same recipe coming
    back is visibly a second complaint.
    """
    if db.get(Recipe, recipe_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such recipe")
    _resolve_reports(db, recipe_id, operator.auth_subject)
    db.commit()


def _resolve_reports(db: Session, recipe_id: uuid.UUID, by: str) -> None:
    """Close every open report on a recipe, once it has been acted on."""
    for report in db.scalars(
        select(SuggestionReport).where(
            SuggestionReport.recipe_id == recipe_id,
            SuggestionReport.resolved_at.is_(None),
        )
    ):
        report.resolved_at = datetime.now(UTC)
        report.resolved_by = by
