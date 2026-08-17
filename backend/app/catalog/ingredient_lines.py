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
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

#: Written as one alternation so the same list serves parsing and stripping.
#: Ordered longest-first where prefixes overlap (`cuillère à soupe` before `c`).
UNITS = (
    r"kilogrammes?|kilos?|kg"
    r"|grammes?|gr?\b"
    r"|litres?|l\b|décilitres?|dl|centilitres?|cl|millilitres?|ml"
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
)

#: Vulgar fractions and the ligatures that a naive NFKD pass silently destroys.
_LIGATURES = {"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"}
_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3"}
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
    r"^\s*(?:bomb[ée]es?|rases?|pleines?|g[ée]n[ée]reuses?|bonnes?|petites?|grosses?)\b",
    re.I,
)
#: Removed as a WORD, never used as a truncation point. `environ` hedges the
#: quantity and these sources put it before the name: truncating there turned
#: `150 g environ farine` into nothing at all, and a line that normalises to
#: nothing can never resolve — so it blocked its whole recipe (I3).
_HEDGE = re.compile(r"\b(?:environ|voire un peu plus|un peu plus)\b", re.I)


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


def fold(text: str) -> str:
    """Lowercase, unaccented, ligature-free, straight apostrophes.

    The ligature and apostrophe handling is not cosmetic. `œufs` passed through
    NFKD keeps its `œ`, which the later `[a-z]` filter drops entirely and leaves
    `ufs` — a distinct string from `oeuf`, for the most common ingredient there
    is. Typographic apostrophes do the same to every `d’ail`.
    """
    for ligature, plain in _LIGATURES.items():
        text = text.replace(ligature, plain)
    for glyph, plain in _FRACTIONS.items():
        text = text.replace(glyph, f" {plain} ")
    text = text.replace("\xa0", " ").replace("’", "'").replace("‘", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


#: French singulars that already end in `s`. Stripping it invents a word, and
#: the invented word then becomes a referential entry someone has to notice.
#: Every one of these was found in the real catalogue: `maïs` became `mai`,
#: `petits pois` became `poi chiche`, `basilic frais` became `basilic frai`.
_INVARIABLE_ENDINGS = ("is", "as", "os", "us")


def singularise(word: str) -> str:
    """Crude French plural stripping, deliberately.

    Takes a word that `fold` has already been through: no accents, no ligatures.
    `maïs` still carrying its diaeresis would not match the invariable endings
    below and would come back as `maï`.

    A real stemmer would conflate words that must stay apart — and in a domain
    where `pâte` and `pâtes` are different foods, over-eager stemming is the
    fuzzy-matching mistake wearing another hat. Short words are left alone.
    """
    if len(word) <= 3:
        return word
    # `-eaux` BEFORE `-aux`, or `poireaux` becomes `poireal`. The `-aux → -al`
    # rule is for `chevaux → cheval`; `poireaux → poireau` is a different one,
    # and checking them in the wrong order was worth three bogus entries in the
    # top 200 (`poireal`, `pruneal`, `cerneal`).
    if word.endswith("eaux"):
        return word[:-1]
    if word.endswith("aux"):
        return word[:-3] + "al"
    if word.endswith("eux"):
        return word
    if word.endswith(_INVARIABLE_ENDINGS):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def normalise(name: str) -> str:
    folded = fold(name)
    folded = re.sub(r"[^a-z' ]", " ", folded)
    words = [singularise(word) for word in folded.split()]
    return " ".join(word for word in words if word)


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


def parse_line(raw: str) -> ParsedLine:
    """One line in, its parts out. Never raises: an unparsable line is a name."""
    text = fold(raw)
    text = _PARENTHESES.sub(" ", text)
    text = _QUALIFIER.sub(" ", text)
    text = _HEDGE.sub(" ", text)
    text = _TRAILING_NOTE.sub("", text)

    quantity, text = _read_quantity(text)

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
        # in `1 boîte de 400 g de tomates`.
        text = _MEASURE_QUALIFIER.sub(" ", text)
        extra, text = _read_quantity(_ARTICLE.sub(" ", text))
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
