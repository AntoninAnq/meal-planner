"""Turning a page into structured metadata — and nothing else (I9).

Pure: HTML in, a frozen result out. No network, no database, no clock. That is
what lets the whole thing be tested on the reduced fixtures in
`tests/fixtures/catalog/`, one per markup shape actually encountered.

The order is always the same, and each step exists because a real source needed
it (§11.5):

  1. JSON-LD, read tolerantly — one source publishes a document with a
     trailing comma that `json.loads` refuses outright.
  2. Microdata `recipeIngredient`.
  3. Microdata `ingredients` — the DEPRECATED spelling, which one source
     still emits.
  4. The descriptor's CSS selectors, for what no vocabulary carries.

Two rules that are not negotiable:

**Everything is scoped to the Recipe subtree.** These pages carry sidebars of
neighbouring recipes, with their own durations and their own ratings. A
page-wide search attributes to a dish the cooking time of the one next to it —
measured, and it is exactly how a first reading of one source reported 100 %
duration coverage where the real figure is 81 %.

The single exception is `selectors["categories"]`, and it is named as such
below: a blog's taxonomy is a property of the PAGE, emitted outside every
`itemscope`, so scoping it to the Recipe subtree would read nothing at all.
It is capped instead — see `MAX_TAXONOMY_LABELS`.

**What cannot be read is counted, never dropped.** An extractor that fails
quietly builds a catalogue whose holes nobody knows about.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from selectolax.parser import HTMLParser, Node

from app.catalog.descriptors import Source

RECIPE_ITEMTYPE = re.compile(r"schema\.org/Recipe\b")
_JSON_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

#: Marks a heading that arrived tagged as an ingredient: `Pour la pâte sucrée :`.
#: Ends with a colon and states no quantity — a line with a number is an
#: ingredient however it is punctuated.
_SECTION = re.compile(r"^[^\d]*[:：]\s*$")

#: Above this, a `categories` selector is not reading a taxonomy — it has caught
#: a tag cloud or a navigation menu. Refused whole rather than trusted in part:
#: `dish_types.yaml` resolves several labels by taking the most restrictive one,
#: so inheriting a sidebar's twelve rubrics turns every recipe into a component.
#: Measured on the source that motivated this: exactly one label per page.
MAX_TAXONOMY_LABELS = 5

_ISO_DURATION = re.compile(r"^P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?", re.I)
_FRENCH_DURATION = re.compile(
    r"(?:(\d+)\s*(?:h|heures?)\s*(\d+)?)|(?:(\d+)\s*(?:min|minutes?|mn)\b)", re.I
)


@dataclass(frozen=True)
class IngredientLine:
    position: int
    raw_text: str
    is_section: bool


@dataclass(frozen=True)
class ParsedRecipe:
    title: str
    ingredients: tuple[IngredientLine, ...]
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    servings: int | None = None
    servings_raw: str | None = None
    categories: tuple[str, ...] = ()
    license: str | None = None
    step_count: int | None = None

    @property
    def resolvable_lines(self) -> int:
        return sum(1 for line in self.ingredients if not line.is_section)


@dataclass
class ExtractionReport:
    """What the extractor managed, and what it did not.

    Aggregated over a campaign, this is the only honest answer to "how good is
    the catalogue" — and the reason a silent failure is not an option.
    """

    url: str
    is_recipe: bool = False
    ingredient_source: str | None = None
    json_ld_blocks: int = 0
    json_ld_unparsable: int = 0
    json_ld_repaired: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.is_recipe and self.ingredient_source is not None


def _clean(text: str | None) -> str:
    """Whitespace, unicode form, and HTML entities.

    The entities are not paranoia: one source double-encodes inside its JSON-LD,
    so `"name": "B&#233;chamel"` arrives as valid JSON whose value is mojibake.
    JSON has no reason to decode HTML, and a DOM parser never sees these because
    they are inside a `<script>`. Unescaping is idempotent on text that came
    through the DOM path, where selectolax has already done it.
    """
    if not text:
        return ""
    unescaped = html.unescape(unicodedata.normalize("NFC", text))
    return re.sub(r"\s+", " ", unescaped.replace("\xa0", " ")).strip()


def read_json_ld(document: str, report: ExtractionReport) -> list[Any]:
    """Parse every JSON-LD block, repairing what can be repaired.

    A strict parser throws away a whole source, for a trailing comma.
    Repairs are counted, because a source that needs repairing today may emit
    something worse tomorrow.
    """
    documents: list[Any] = []
    for raw in _JSON_LD.findall(document):
        report.json_ld_blocks += 1
        payload = raw.strip()
        try:
            documents.append(json.loads(payload))
            continue
        except ValueError:
            pass
        try:
            documents.append(json.loads(_TRAILING_COMMA.sub(r"\1", payload)))
            report.json_ld_repaired += 1
        except ValueError:
            report.json_ld_unparsable += 1
    return documents


def find_recipe_node(documents: list[Any]) -> dict[str, Any] | None:
    """`Recipe` may sit at the root, in an `@graph`, or nested in a list."""
    stack: list[Any] = list(documents)
    while stack:
        node = stack.pop(0)
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            declared = node.get("@type")
            declared = declared if isinstance(declared, list) else [declared]
            if "Recipe" in declared:
                return node
            for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement"):
                if key in node:
                    stack.append(node[key])
    return None


def parse_duration(value: Any) -> int | None:
    """ISO 8601 (`PT30M`) or French prose (`1 h 30`, `15 min`) to minutes."""
    text = _clean(str(value)) if value is not None else ""
    if not text:
        return None

    iso = _ISO_DURATION.match(text)
    if iso and (iso.group(1) or iso.group(2)):
        return int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0)

    total = 0
    for hours, hour_minutes, minutes in _FRENCH_DURATION.findall(text):
        if hours:
            total += int(hours) * 60 + int(hour_minutes or 0)
        elif minutes:
            total += int(minutes)
    return total or None


def parse_servings(value: Any) -> tuple[int | None, str | None]:
    """`recipeYield` verbatim, plus the number when there is one.

    "20 tartelettes" and "4 personnes" are not the same unit, and scaling
    portions against the first would be nonsense. The raw string is what lets a
    human tell them apart later (§8.2).
    """
    if isinstance(value, list):
        value = value[0] if value else None
    raw = _clean(str(value)) if value is not None else ""
    if not raw:
        return None, None
    match = re.search(r"\d+", raw)
    return (int(match.group()) if match else None), raw


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(_clean(part) for part in value.split(",") if _clean(part))
    if isinstance(value, list):
        return tuple(_clean(str(item)) for item in value if _clean(str(item)))
    return ()


def _ingredient_lines(texts: list[str]) -> tuple[IngredientLine, ...]:
    lines: list[IngredientLine] = []
    for text in texts:
        cleaned = _clean(text)
        if not cleaned:
            continue
        lines.append(
            IngredientLine(
                position=len(lines),
                raw_text=cleaned,
                is_section=bool(_SECTION.match(cleaned)),
            )
        )
    return tuple(lines)


def _recipe_subtree(tree: HTMLParser) -> Node | None:
    for node in tree.css("[itemtype]"):
        if RECIPE_ITEMTYPE.search(node.attributes.get("itemtype") or ""):
            return node
    return None


def _microdata(node: Node, prop: str) -> list[str]:
    return [element.text(deep=True) for element in node.css(f'[itemprop="{prop}"]')]


def _count_steps(node: Node | None, recipe: dict[str, Any] | None) -> int | None:
    """A count is a fact; the steps themselves are the author's (I9).

    Three spellings, because three sources write steps three ways. The last one
    — paragraphs — exists for a blog that marks up `recipeInstructions` as a
    `<div>` of `<p>`: no list anywhere, and without it 502 recipes carry no
    complexity signal at all. That source publishes no duration either, so the
    step count is the ONLY thing `complexity.py` has to go on for them.
    """
    if recipe is not None:
        instructions = recipe.get("recipeInstructions")
        if isinstance(instructions, list):
            return len(instructions) or None
    if node is not None:
        for element in node.css('[itemprop="recipeInstructions"]'):
            items = element.css("li")
            if items:
                return len(items)
            # Paragraphs, and only the ones carrying text: these blocks end on
            # an image credit and a share widget, both of them empty `<p>`.
            paragraphs = [p for p in element.css("p") if _clean(p.text(deep=True))]
            if paragraphs:
                return len(paragraphs)
    return None


def _read_categories(
    tree: HTMLParser, node: Node | None, recipe: dict[str, Any] | None, source: Source
) -> tuple[str, ...]:
    """The rubric, in the same order as everything else: JSON-LD, microdata, selector.

    It used to be read from JSON-LD alone, which meant a microdata-only source
    got an empty tuple whatever it published. Measured consequence: 502 recipes
    with no `dish_type`, half of one household's eligible pool — and a waffle
    proposed for Sunday lunch. The same waffle is correctly excluded when it
    comes from a source that emits JSON-LD.
    """
    if recipe is not None:
        declared = _as_tuple(recipe.get("recipeCategory"))
        if declared:
            return declared

    if node is not None:
        marked = tuple(text for text in map(_clean, _microdata(node, "recipeCategory")) if text)
        if marked:
            return marked

    # Page-scoped, deliberately — see the module docstring. A blog's taxonomy
    # sits in the article footer, outside every `itemscope`.
    selector = source.selectors.get("categories")
    if selector:
        found = tuple(
            text for text in (_clean(el.text(deep=True)) for el in tree.css(selector)) if text
        )
        if len(found) > MAX_TAXONOMY_LABELS:
            # Counted by the caller as missing, never trusted in part.
            return ()
        return found

    return ()


def extract(
    document: str, *, url: str, source: Source
) -> tuple[ParsedRecipe | None, ExtractionReport]:
    report = ExtractionReport(url=url)
    tree = HTMLParser(document)

    documents = read_json_ld(document, report)
    recipe = find_recipe_node(documents)
    node = _recipe_subtree(tree)

    if recipe is None and node is None:
        return None, report
    report.is_recipe = True

    # 1. JSON-LD, then 2. and 3. the two microdata spellings — in that order,
    # and always inside the Recipe subtree.
    texts: list[str] = []
    if recipe is not None:
        texts = [str(item) for item in (recipe.get("recipeIngredient") or [])]
        if texts:
            report.ingredient_source = "json_ld"
    if not texts and node is not None:
        for prop, label in (("recipeIngredient", "microdata"), ("ingredients", "microdata_legacy")):
            texts = _microdata(node, prop)
            if texts:
                report.ingredient_source = label
                break

    lines = _ingredient_lines(texts)
    if not lines:
        report.ingredient_source = None
        report.missing.append("ingredients")
        return None, report

    title = _clean(str(recipe.get("name"))) if recipe and recipe.get("name") else ""
    if not title and node is not None:
        title = _clean(next(iter(_microdata(node, "name")), ""))
    if not title:
        report.missing.append("title")
        return None, report

    prep = parse_duration(recipe.get("prepTime")) if recipe else None
    cook = parse_duration(recipe.get("cookTime")) if recipe else None
    servings, servings_raw = parse_servings(recipe.get("recipeYield") if recipe else None)

    # 4. The descriptor's selectors, only for what is still missing — and read
    # inside the Recipe subtree, never across the page.
    if node is not None:
        scope = node
        if prep is None and "prep_minutes" in source.selectors:
            prep = parse_duration(_selector_text(scope, source.selectors["prep_minutes"]))
        if cook is None and "cook_minutes" in source.selectors:
            cook = parse_duration(_selector_text(scope, source.selectors["cook_minutes"]))
        if servings is None:
            servings, servings_raw = parse_servings(
                next(iter(_microdata(node, "recipeYield")), None)
            )

    categories = _read_categories(tree, node, recipe, source)

    for name, value in (
        ("prep_minutes", prep),
        ("cook_minutes", cook),
        ("servings", servings),
        # Reported like the rest, because an unclassified recipe is not a
        # neutral gap: an unknown rubric passes the meal-slot filter, so what
        # is not read here comes back as a dessert at dinner.
        ("categories", categories or None),
    ):
        if value is None:
            report.missing.append(name)

    return (
        ParsedRecipe(
            title=title,
            ingredients=lines,
            prep_minutes=prep,
            cook_minutes=cook,
            servings=servings,
            servings_raw=servings_raw,
            categories=categories,
            license=_clean(str(recipe["license"])) or None
            if recipe and recipe.get("license")
            else None,
            step_count=_count_steps(node, recipe),
        ),
        report,
    )


def _selector_text(scope: Node, selector: str) -> str:
    found = scope.css_first(selector)
    if found is None:
        return ""
    # `<time datetime="PT30M">` when the site fills it, the visible label
    # otherwise. One source leaves `datetime` empty and writes "15 min".
    stamp = found.css_first("time")
    if stamp is not None and _clean(stamp.attributes.get("datetime") or ""):
        return stamp.attributes["datetime"] or ""
    return found.text(deep=True)
