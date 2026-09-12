"""Splitting `400 g de myrtilles fraîches` into a quantity, a unit and a name.

This is the highest-leverage component of the whole catalogue, and it is worth
being explicit about why.

Every ingredient line that fails to resolve keeps a recipe out of the verified
catalogue — I3 requires that *all* of them resolve, and recipes average 8.6
lines. So resolution rate is what the phase-1 exit criterion actually measures,
and normalisation is what feeds it.

**And it cannot be rescued by fuzzy matching.** I4 exists because substitute
ingredients are named after the food they replace: `farine de riz` is closest to
`farine de blé`, and taking that similarity for equivalence swaps gluten in or
out. A trigram cannot tell `de lait` from `de la` — a parser can, and must.

The cost of getting it wrong is measurable, not theoretical. Two drafts of this
written ten minutes apart produced 9 914 and 9 779 distinct strings over the same
32 000 lines; the difference was the `œ` ligature and typographic apostrophes
alone. A first draft also emitted `ufs`, `uf` and `oeuf` for one word, split
`ail` from `d ail`, and turned `de lait` into `it` by stripping `de la` without a
word boundary. Every such bug is hand-entry work someone has to do twice.

Pure functions, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# Name normalisation and relaxation live in the domain: the pre-filter needs
# them and may not import this package (`tests/test_catalog_boundaries.py`).
# This module keeps the QUANTITY and UNIT machinery, which is parsing proper.
from app.domain.ingredient_names import fold, normalise

#: Written as one alternation so the same list serves parsing and stripping.
#: Ordered longest-first where prefixes overlap (`cuillère à soupe` before `c`).
UNITS = (
    r"kilogrammes?|kilos?|kg"
    r"|grammes?|gr?\b"
    # Accent-free spellings: this pattern is applied AFTER `fold`, so a literal
    # `décilitres?` could never match anything. `dl` carried the case alone.
    r"|litres?|l\b|d[ée]cilitres?|dl|centilitres?|cl|millilitres?|ml"
    r"|cuill[eè]r[ée]?e?s?\s+[àa]\s+(?:soupe|caf[ée])"
    # Spelled-out forms FIRST: the abbreviated `c. à s.` pattern would otherwise
    # match `c. a s` inside `c. à soupe` and leave a stray `oupe` as the name.
    r"|c\.?\s*[àa]\.?\s*(?:soupe|caf[ée])|c\.?\s*(?:soupe|caf[ée])"
    r"|c\.?\s*[àa]\.?\s*[sc]\.?|cs\b|cc\b"
    # A bare `cuillerée`, with no `à café` after it. Last among the spoon
    # forms so the compound ones win, and worth its own branch: it left
    # `cuilleree levure chimique` as an ingredient name of its own.
    r"|cuill[eè]r[ée]?e?s?"
    r"|pinc[ée]es?|poign[ée]es?|gousses?|branches?|feuilles?|tranches?"
    r"|sachets?|bo[îi]tes?|bocaux?|bocal|verres?|bols?|tasses?"
    r"|bottes?|brins?|tiges?|filets?|morceaux?|pieds?|paquets?|barquettes?"
        # `noix` is NOT listed as a unit. It reads like one in `une noix de
    # beurre`, but it is also the nut itself — and one that carries an
    # allergen. Treating it as a unit turned `15 noix` into a quantity with no
    # ingredient at all, which silently dropped the allergen and blocked the
    # recipe. `noix de beurre` is handled as an alias in the referential.
    r"|rouleaux?|tablettes?|zestes?|gouttes?|cubes?|louches?|traits?"
    # `4 cm gingembre frais` — a length really is how ginger and leeks are
    # measured. Left out, `cm` stayed in the name and `cm gingembre frais`
    # became a string of its own.
    r"|cm\b|mm\b"
)

_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "douze": 12,
    "demi": Fraction(1, 2), "demie": Fraction(1, 2),
}

_QUANTITY = re.compile(
    r"^\s*(?:(?P<whole>\d+)\s+)?(?P<num>\d+)\s*/\s*(?P<den>\d+)"     # 1 1/2, 3/4
    r"|^\s*(?P<dec>\d+(?:[.,]\d+)?)"                                  # 250, 1,5
    r"|^\s*(?P<word>" + "|".join(_NUMBER_WORDS) + r")\b",
    re.I,
)
_UNIT = re.compile(rf"^\s*(?P<unit>{UNITS})\b\.?", re.I)
#: `de`, `du`, `des`, `de la`, `d'` — with word boundaries, or `de lait` loses
#: its middle and becomes `it`.
_ARTICLE = re.compile(
    r"^\s*(?:de\s+la\b|de\s+l'|d'|d\s+|de\b|du\b|des\b|le\b|la\b|les\b)\s*", re.I
)
#: Trailing preparation notes: `oignon, émincé` and `beurre (mou)`.
#: The lookarounds are load-bearing: without them `1,5 l de bouillon` loses
#: everything after the decimal comma and becomes the quantity `1` with no name.
_PARENTHESES = re.compile(r"\([^)]*\)")
_TRAILING_NOTE = re.compile(r"\s*(?<!\d)[,;](?!\d).*$")
#: Truncate from here: what follows is commentary, not an ingredient.
_QUALIFIER = re.compile(
    r"\b(?:facultatifs?|optionnels?|au go[ûu]t|selon\s+(?:le\s+)?go[ûu]t|"
    r"[àa]\s+volont[ée]|bien\s+m[ûu]rs?)\b.*$",
    re.I,
)
#: Adjectives that describe the MEASURE, not the food: `1 cuiller à café
#: bombée de levure`. Left in place they became part of the ingredient name —
#: `bombee de levure chimique` — and each such variant is a referential entry
#: someone would otherwise have to write by hand.
_MEASURE_QUALIFIER = re.compile(
    r"^\s*(?:bomb[ée]es?|rases?|pleines?|g[ée]n[ée]reuses?|bonnes?"
    r"|petites?|grosses?|belles?|beaux?|bel|jolies?|jolis?)\b",
    re.I,
)
#: The same idea in the position AFTER the unit — `2 cuillerées bombées de
#: sucre`. Deliberately a shorter list: there the guard of a following unit is
#: not available, and `petit` / `gros` can open a food name. `1 sachet petits
#: pois` must not become `pois`, which is a different vegetable; `1 pincée
#: généreuse` has no such reading.
_AFTER_UNIT_QUALIFIER = re.compile(
    r"^\s*(?:bomb[ée]es?|rases?|pleines?|g[ée]n[ée]reuses?|bonnes?|belles?)\b", re.I
)
#: What joins two quantities: `2 à 3 gousses`, `225 g+125 g de sucre`,
#: `180-200 g`. The first quantity is kept and the rest consumed — a range is
#: one ingredient, and left in place the tail became the name (`g de sucre`).
#: A digit must follow, or `1 boîte à l'huile` would lose its `à`.
_CONNECTOR = re.compile(r"^\s*(?:[+\-–—]|[àa]|ou)\s*(?=\d)", re.I)
#: Removed as a WORD, never used as a truncation point. `environ` hedges the
#: quantity and these sources put it before the name: truncating there turned
#: `150 g environ farine` into nothing at all, and a line that normalises to
#: nothing can never resolve — so it blocked its whole recipe (I3).
_HEDGE = re.compile(r"\b(?:environ|voire un peu plus|un peu plus|quelques?)\b", re.I)


#: Lines that structure a list without naming a food. They arrive tagged as
#: ingredients, exactly like `Pour la pâte sucrée :` does, but without the colon
#: that gives that one away.
#:
#: They matter more than their number suggests: I3 requires EVERY line of a
#: recipe to resolve, so one unresolvable `pour servir` keeps that whole recipe
#: out of the verified catalogue forever. Found in the real top 300: `pour
#: servir`, `pour la sauce`, `pour la pâte`, `garniture`, `pour décorer`.
_STRUCTURAL_WORDS = frozenset(
    {
        "garniture", "decoration", "marinade", "assaisonnement", "finition",
        "dressage", "accompagnement", "sauce", "ingredient", "materiel",
    }
)


@dataclass(frozen=True)
class ParsedLine:
    """What a raw ingredient line yields. `raw` is never lost (§8.2)."""

    raw: str
    quantity: Fraction | None
    unit: str | None
    name: str
    #: Lowercase, unaccented, singularised, collapsed. What matching reads.
    normalized: str
    #: True when the line organises the list instead of naming a food. Such a
    #: line is never resolved and never counted against the recipe.
    is_structural: bool = False


def looks_structural(normalized: str) -> bool:
    """`pour servir`, `garniture`, `pour le glaçage`.

    No French ingredient name begins with `pour`, which makes that prefix a
    safe test; the rest is a short closed list.
    """
    if not normalized:
        return False
    return normalized.startswith("pour ") or normalized in _STRUCTURAL_WORDS


def _read_quantity(text: str) -> tuple[Fraction | None, str]:
    match = _QUANTITY.match(text)
    if not match:
        return None, text
    groups = match.groupdict()
    if groups["num"]:
        value = Fraction(int(groups["num"]), int(groups["den"]))
        if groups["whole"]:
            value += int(groups["whole"])
    elif groups["dec"]:
        value = Fraction(groups["dec"].replace(",", "."))
    else:
        value = Fraction(_NUMBER_WORDS[groups["word"].lower()])
    return value, text[match.end():]


def _read_quantity_range(text: str) -> tuple[Fraction | None, str]:
    """`2 à 3 gousses`, `180-200 g`, `225 g+125 g` — the first value wins.

    A range is one ingredient, and the sources write it three different ways.
    Consuming only the first number left the rest in the name: `2 à 3 œufs
    entiers` normalised to `a oeuf entier`, and `225 g+125 g de sucre` to
    `g de sucre` — strings no referential will ever carry.
    """
    quantity, text = _read_quantity(text)
    if quantity is None:
        return None, text
    while (connector := _CONNECTOR.match(text)) is not None:
        extra, rest = _read_quantity(text[connector.end():])
        if extra is None:
            break
        text = rest
    return quantity, text


def parse_line(raw: str) -> ParsedLine:
    """One line in, its parts out. Never raises: an unparsable line is a name."""
    text = fold(raw)
    text = _PARENTHESES.sub(" ", text)
    text = _QUALIFIER.sub(" ", text)
    text = _HEDGE.sub(" ", text)
    text = _TRAILING_NOTE.sub("", text)

    quantity, text = _read_quantity_range(text)

    # A measure qualifier is consumed ONLY when a unit follows it. Stripping
    # `petit` unconditionally would turn `petits pois` into `pois` — a
    # different food — while `2 grosses cuillerées` really is about the spoon.
    # The adjective belongs to whichever noun comes next, and only the unit
    # case is safe.
    qualifier = _MEASURE_QUALIFIER.match(text)
    if qualifier and _UNIT.match(text[qualifier.end():]):
        text = text[qualifier.end():]

    unit = None
    unit_match = _UNIT.match(text)
    if unit_match:
        unit = unit_match.group("unit").strip()
        text = text[unit_match.end():]
        # `2 c. à soupe d'huile` — a second quantity sometimes follows the unit
        # in `1 boîte de 400 g de tomates`, and `225 g+125 g de sucre` puts the
        # connector here rather than before the unit.
        text = _AFTER_UNIT_QUALIFIER.sub(" ", text)
        extra, text = _read_quantity(_CONNECTOR.sub("", _ARTICLE.sub(" ", text)))
        if extra is not None:
            second_unit = _UNIT.match(text)
            if second_unit:
                text = text[second_unit.end():]

    text = _ARTICLE.sub(" ", text)
    name = re.sub(r"\s+", " ", text).strip(" .-")

    normalized = normalise(name)
    # Tested on the line as WRITTEN, not on what survived article stripping:
    # `pour la sauce` loses its `pour la` and would look like a plain `sauce`.
    structural = looks_structural(normalise(fold(raw))) or looks_structural(normalized)

    return ParsedLine(
        raw=raw.strip(),
        quantity=quantity,
        unit=normalise(unit) if unit else None,
        name=name,
        normalized=normalized,
        is_structural=structural,
    )
