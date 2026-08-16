"""Life-stage derivation.

Pure functions: no database, no I/O. The stored `member.life_stage` is the
EFFECTIVE value, confirmed by a parent. `birth_date` only ever produces a
*proposal*.

Why proposals rather than automatic transitions: crossing BABY -> YOUNG_CHILD
WIDENS what is allowed. Overnight the candidate set would open up to salted,
spiced, chunky dishes without anyone judging whether that particular child is
ready. That is the safety-relevant direction, so it is never silent — and a
uniform rule is simpler than an asymmetric one.
"""

from dataclasses import dataclass
from datetime import date

from app.domain.enums import LifeStage

#: Upper bound in months, exclusive. None = open-ended.
#:
#: 18 months rather than 12: the regulatory prohibitions (honey, cow's milk)
#: lift at 12 months, but textures and choking risk do not. A safety threshold
#: should be more conservative than a legal one.
DEFAULT_THRESHOLDS_MONTHS: dict[LifeStage, int | None] = {
    LifeStage.BABY: 18,
    LifeStage.YOUNG_CHILD: 132,  # 11 years
    LifeStage.TEEN_ADULT: None,
}

_ORDER: tuple[LifeStage, ...] = (
    LifeStage.BABY,
    LifeStage.YOUNG_CHILD,
    LifeStage.TEEN_ADULT,
)


def age_in_months(birth_date: date, on: date) -> int:
    """Whole months elapsed, never negative."""
    months = (on.year - birth_date.year) * 12 + (on.month - birth_date.month)
    if on.day < birth_date.day:
        months -= 1
    return max(months, 0)


def proposed_life_stage(
    birth_date: date,
    on: date,
    thresholds: dict[LifeStage, int | None] | None = None,
) -> LifeStage:
    """The stage the member's age suggests. Never applied on its own."""
    bounds = thresholds or DEFAULT_THRESHOLDS_MONTHS
    months = age_in_months(birth_date, on)
    for stage in _ORDER:
        upper = bounds[stage]
        if upper is None or months < upper:
            return stage
    return LifeStage.TEEN_ADULT


@dataclass(frozen=True)
class PendingTransition:
    current: LifeStage
    proposed: LifeStage


def pending_transition(
    current: LifeStage,
    birth_date: date | None,
    on: date,
    thresholds: dict[LifeStage, int | None] | None = None,
) -> PendingTransition | None:
    """Return a transition to submit to the parent, or None.

    A member without a birth date never generates a proposal: there is nothing
    to derive from, and guessing is exactly what we refuse to do here.
    """
    if birth_date is None:
        return None
    proposed = proposed_life_stage(birth_date, on, thresholds)
    if proposed == current:
        return None
    return PendingTransition(current=current, proposed=proposed)
