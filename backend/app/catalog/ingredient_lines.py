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
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

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


#: Elided articles left stranded once the digits are gone. `Jus d’1 citron`
#: keeps its `d'` through the `[^a-z' ]` pass and yields `jus d' citron` — a
#: string distinct from `jus de citron` for no reason a reader would accept.
#:
#: Only the apostrophe forms. A bare `l` is the litre — `50 cl de lait` reads
#: its unit through this same function, and dropping it left the line unitless.
_ORPHAN_ARTICLES = frozenset({"d'", "l'", "n'", "s'", "qu'"})


def normalise(name: str) -> str:
    folded = fold(name)
    folded = re.sub(r"[^a-z' ]", " ", folded)
    words = [singularise(word) for word in folded.split()]
    return " ".join(word for word in words if word and word not in _ORPHAN_ARTICLES)


# ---------------------------------------------------------------------------
# Relaxation — reading `courgette moyenne` as a courgette
# ---------------------------------------------------------------------------
#
# Measured cause: 423 savoury recipes in the catalogue were ONE line short of
# resolving, and three quarters of those lines were a known food carrying a
# size, a state or a packaging. Writing `betterave cuite` by hand when
# `betterave` already exists is paying for a missing tool.
#
# This is NOT fuzzy matching, and I4 is not bent here. Four properties hold,
# and each was chosen against a case that appeared in the real data:
#
# 1. **A relaxation is only ever TRIED when the full string is unknown.**
#    The referential shields every compound it already carries: `petits pois`,
#    `chocolat noir`, `crème fraîche`, `raisin sec` are never touched, because
#    they resolve before any of this runs.
# 2. **A complement in `de X` / `au X` is never removed.** `crème de soja`
#    would become `crème` — swapping `soybeans` for `milk`, an UNDER-exclusion.
#    So `noix de beurre` cannot be reached by rule either; it is an alias.
# 3. **Varieties and colours are not in any list.** `farine de blé noir` is
#    buckwheat, which has no gluten and is not wheat; `chocolat noir` carries
#    `milk` where `chocolat au lait` does too. A colour can cross an allergen
#    boundary, so colours are written as referential entries, one at a time.
# 4. **`sec` / `séché` is not in any list.** `Raisin sec` carries `sulphites`
#    and `Raisin` does not — dried fruit is sulphited. Removing it would
#    remove an allergen.
#
# The lists are closed and written in NORMALISED form: unaccented, singular,
# which is what `normalise` produces.

#: Size and calibre. Removable at either end: `grosse carotte`, `courgette
#: moyenne`.
_CALIBRE = (
    r"gros|grosse|petit|petite|moyen|moyenne|grand|grande|beau|bel|belle|joli|jolie"
)
#: How the food arrives or is cut. None of these changes what the food IS.
#: Some `-us` forms are spelled out because `singularise` treats that ending as
#: invariable (`moulus` stays `moulus`, by design — it protects `maïs`).
_PREPARATION = (
    r"rape|rapee|moulu|moulue|moulus|torrefie|torrefiee|surgele|surgelee"
    r"|cuit|cuite|cru|crue|crus|emince|emincee|hache|hachee|pele|pelee"
    r"|coupe|coupee|fondu|fondue|ramolli|ramollie|egoutte|egouttee|essore|essoree"
    r"|denoyaute|denoyautee|epluche|epluchee|lave|lavee|ecrase|ecrasee"
    r"|concasse|concassee|effile|effilee|cisele|ciselee|blanchi|blanchie"
    r"|decortique|decortiquee|entier|entiere|tiede|froid|froide|mur|mure"
    r"|bio|nature|frais|fraiche|nouveau|nouvelle|grille|grillee"
    # Adverbs, removed in a second pass: `oignon finement hache` loses its
    # participle first, then this. An adverb qualifies the gesture and can
    # never be a food nor change one.
    r"|finement|grossierement|fraichement|legerement|prealablement"
)
#: Packaging and provenance of the product, not of the food.
#: `a l'huile` is listed alone and never `a l'huile de X`, which could hide
#: `arachide` or `sesame`.
_PACKAGING = (
    # `en des` and not `en de`: `singularise` leaves words of three letters
    # alone, so `en dés` normalises to `en des`.
    r"a point|en poudre|en morceau|en des|en boite|en conserve|en lamelle"
    r"|en rondelle|en tranche|en branche|en grain|en filet|au naturel"
    r"|a l'huile|a temperature ambiante|du commerce|maison|de qualite"
    r"|de preference|si possible|bien mur|bien mure"
)
#: Geographical origin, a closed list of places rather than a `de X` rule.
_ORIGIN = (
    r"du puy|de bretagne|d'espagne|du perigord|de savoie|de provence|corse"
)

#: Removing a LEADING calibre is the only rule that can cut into a compound
#: noun, so it is kept apart and guarded below.
_CALIBRE_PREFIX = re.compile(rf"^(?:{_CALIBRE})\s+(?P<stem>.+)$")

_SUFFIX_RULES = (
    re.compile(rf"^(?P<stem>.+?)\s+(?:{_CALIBRE})$"),
    re.compile(rf"^(?P<stem>.+?)\s+(?:{_PREPARATION})$"),
    re.compile(rf"^(?P<stem>.+?)\s+(?:{_PACKAGING})$"),
    re.compile(rf"^(?P<stem>.+?)\s+(?:{_ORIGIN})$"),
)

#: Compound nouns that a calibre rule would take apart, with the wrong result.
#: `petit-beurre` is the one case in the whole catalogue where a relaxation
#: would REMOVE an allergen: it is a biscuit — gluten, eggs, milk — and `beurre`
#: carries milk alone. It has its own referential entry; this list makes sure
#: nothing can reach `Beurre` from it even if that entry is ever removed.
_NEVER_RELAXED = frozenset(
    {
        "petit beurre",
        "petit lait",      # lactosérum, not a small quantity of milk
        "petit sale",
        "petit epeautre",  # a different cereal from épeautre
        "petit suisse",
        "petit four",
        "petit dejeuner",
        "petit pois",      # a different vegetable from `pois`
    }
)

#: How many qualifiers one name may carry. `creme liquide entiere froide` needs
#: three; beyond that the string is noise, not a food.
_MAX_RELAXATIONS = 4


def _opens_a_protected_compound(name: str) -> bool:
    """`petit beurre écrasé` still starts with `petit-beurre`.

    Without this, the leading-calibre rule fires first and offers `beurre
    écrasé` before `petit beurre` is ever tried — one alias away from resolving
    a biscuit as butter.
    """
    return any(name == word or name.startswith(f"{word} ") for word in _NEVER_RELAXED)


def variants(normalized: str) -> Iterator[str]:
    """Progressively simpler spellings of a name, most specific first.

    Yields nothing for a name that carries no known qualifier. The caller looks
    each one up and stops at the first hit, so the most specific match wins.
    """
    seen = {normalized}
    frontier = [(normalized, 0)]

    while frontier:
        current, depth = frontier.pop(0)
        if current in _NEVER_RELAXED or depth >= _MAX_RELAXATIONS:
            continue
        rules = _SUFFIX_RULES
        if not _opens_a_protected_compound(current):
            rules = (*rules, _CALIBRE_PREFIX)
        for pattern in rules:
            match = pattern.match(current)
            if match is None:
                continue
            stem = match.group("stem").strip()
            # A protected compound is a valid DESTINATION — `petit pois
            # surgelé` must reach `petits pois`, which is an entry. What the
            # protection forbids is relaxing it FURTHER, and that is enforced
            # when it comes back off the frontier.
            if not stem or stem in seen:
                continue
            seen.add(stem)
            frontier.append((stem, depth + 1))
            yield stem


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
