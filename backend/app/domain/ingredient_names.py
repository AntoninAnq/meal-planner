"""Normalising an ingredient NAME, and reading its variants.

Pure text: no I/O, no SQL. It lives in `domain/` rather than beside the parser
because two very different callers need it — the catalogue pipeline, which
parses scraped lines, and the pre-filter, which turns `leftover: jambon` into a
set of recipes.

`tests/test_catalog_boundaries.py` forbids the second from importing the first,
and rightly: the day the pipeline earns its own deployment, that import is the
thing that would break the API. So what both need lives here, and
`app/catalog/ingredient_lines.py` re-exports it so its own callers see nothing.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

#: Vulgar fractions and the ligatures that a naive NFKD pass silently destroys.
_LIGATURES = {"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"}
_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3"}

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
