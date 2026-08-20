"""The extractor, against one reduced page per markup shape actually met.

Each fixture is a real page from a source that was measured, stripped before
being committed: the author's prose is elided (I9), and the source's identity —
hostnames, names, everything but the shape — is scrubbed. What a fixture is FOR
is the shape of its markup; who emitted it is deployment configuration and does
not belong in a public repository. See `fixtures/catalog/README.md`.

The whitelist used here is `sources.example.yaml`, on fictitious domains. Using
the shipped template as the test whitelist is what keeps the template from
rotting: a broken example fails the build.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.catalog.descriptors import (
    EXAMPLE_SOURCES_FILE,
    DescriptorError,
    load_sources,
    parse_sources,
)
from app.catalog.extraction import (
    MAX_TAXONOMY_LABELS,
    extract,
    parse_duration,
    parse_servings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
SOURCES = load_sources(EXAMPLE_SOURCES_FILE)


def run(fixture: str, source_code: str):
    html = (FIXTURES / f"{fixture}.html").read_text(encoding="utf-8")
    return extract(html, url=f"https://exemple.test/{fixture}", source=SOURCES[source_code])


# --------------------------------------------------------------------------
# One case per markup shape
# --------------------------------------------------------------------------


def test_invalid_json_ld_is_repaired_and_counted() -> None:
    """A trailing comma. A strict parser drops the whole page for it.

    Repairing silently would be worse than failing: the counter is what tells us
    a source has started emitting something we only half understand.
    """
    recipe, report = run("json_ld_invalid_microdata_ingredients", "microdata-site")

    assert report.json_ld_blocks == 1
    assert report.json_ld_repaired == 1
    assert report.json_ld_unparsable == 0
    assert recipe is not None


def test_ingredients_come_from_microdata_when_the_json_ld_has_none() -> None:
    """The document parses, declares `Recipe`, and carries no ingredient.

    This is why the extraction order exists at all: a pipeline that trusted
    JSON-LD alone would index this source as two thousand recipes with no
    contents, and the count would look like success.
    """
    recipe, report = run("json_ld_invalid_microdata_ingredients", "microdata-site")

    assert report.ingredient_source == "microdata"
    assert recipe is not None
    assert recipe.title == "Tartelettes aux myrtilles"
    assert recipe.ingredients[0].raw_text == (
        "400 g de myrtilles fraîches voire surgelées ou encore en conserve"
    )


def test_a_section_heading_is_kept_in_place_and_marked() -> None:
    """`Pour la pâte sucrée :` arrives tagged as an ingredient and is not one.

    Dropping it would shift every position after it; resolving it would put a
    heading in the referential.
    """
    recipe, _ = run("json_ld_invalid_microdata_ingredients", "microdata-site")
    assert recipe is not None

    sections = [line for line in recipe.ingredients if line.is_section]
    assert [line.raw_text for line in sections] == [
        "Pour la pâte sucrée :",
        "Pour la crème pâtissière :",
    ]
    # Positions stay contiguous: the heading holds its place in the list.
    assert [line.position for line in recipe.ingredients] == list(range(len(recipe.ingredients)))
    assert recipe.resolvable_lines == len(recipe.ingredients) - 2


def test_a_duration_the_markup_does_not_carry_is_read_by_the_descriptor() -> None:
    """The fourth step of the extraction order, on the source that needs it.

    This source marks up no duration at all — yet 81 % of its recipes display
    one, in the template. The selector reads it, scoped to the Recipe subtree:
    these pages carry a sidebar of neighbouring recipes with THEIR durations,
    and a page-wide search hands a dish the cooking time of the one beside it.
    """
    recipe, report = run("selector_durations", "microdata-site")

    assert recipe is not None
    assert (recipe.prep_minutes, recipe.cook_minutes) == (15, 35)
    assert report.missing == []


def test_a_duration_left_empty_stays_empty() -> None:
    """The same source renders an unfilled duration as a literal `?`.

    Nothing is invented, and the gap is reported rather than defaulted — a
    catalogue of plausible durations nobody measured is worse than one whose
    holes are counted.
    """
    recipe, report = run("json_ld_invalid_microdata_ingredients", "microdata-site")

    assert recipe is not None
    assert recipe.prep_minutes is None
    assert "prep_minutes" in report.missing


def test_the_licence_is_taken_from_the_page_that_declares_it() -> None:
    """One source states a licence per recipe; blogs state none.

    NULL is not "unknown, assume the best": it is what makes I9 apply strictly.
    """
    declared, _ = run("json_ld_invalid_microdata_ingredients", "microdata-site")
    silent, _ = run("json_ld_complete", "json-ld-site")

    assert declared is not None and silent is not None
    assert declared.license == "https://creativecommons.org/publicdomain/zero/1.0/deed.fr"
    assert silent.license is None


def test_html_entities_are_decoded_out_of_the_json_ld() -> None:
    """One source double-encodes inside its JSON-LD.

    `"name": "B&#233;chamel"` is valid JSON whose value is mojibake, and nothing
    else in the chain would fix it: JSON has no reason to decode HTML, and the
    DOM parser never sees these because they sit inside a `<script>`. Caught in
    the database, after a real campaign wrote `Po&#234;l&#233;es` as a category.
    """
    recipe, _ = run("json_ld_complete", "json-ld-site")

    assert recipe is not None
    everything = " ".join(
        [recipe.title, *(recipe.categories), *(line.raw_text for line in recipe.ingredients)]
    )
    assert "&#" not in everything
    assert "&amp;" not in everything


def test_steps_are_counted_never_stored() -> None:
    """A count is a fact; the steps are the author's (I9)."""
    recipe, _ = run("json_ld_invalid_microdata_ingredients", "microdata-site")

    assert recipe is not None
    assert recipe.step_count == 10
    assert not hasattr(recipe, "instructions")


def test_the_deprecated_ingredients_property_is_read() -> None:
    """One source still emits `itemprop="ingredients"`, dropped from schema.org.

    Its JSON-LD describes a `BlogPosting`, so there is nothing to fall back on.
    """
    recipe, report = run("microdata_legacy_property", "legacy-microdata-site")

    assert report.ingredient_source == "microdata_legacy"
    assert recipe is not None
    assert recipe.ingredients[0].raw_text == "50cl de lait"


def test_the_rubric_is_read_from_the_page_taxonomy_when_the_markup_has_none() -> None:
    """The same source marks up no `recipeCategory` anywhere — and classifies
    every one of its pages in the article footer.

    Read from JSON-LD alone, this source produced 502 recipes with no dish type.
    They are not excluded by the meal-slot filter — an unknown rubric passes —
    so they made up half of a household's eligible pool, and a waffle was
    proposed for Sunday lunch. The identical waffle from a source that emits
    JSON-LD is correctly filtered out.
    """
    recipe, report = run("microdata_legacy_property", "legacy-microdata-site")

    assert recipe is not None
    assert recipe.categories == ("Céréales",)
    assert "categories" not in report.missing


def test_a_taxonomy_selector_that_catches_a_tag_cloud_is_refused_whole() -> None:
    """`dish_types.yaml` resolves several labels by keeping the most restrictive.

    So inheriting a navigation menu is not a small error that averages out: one
    `Sauces` in twelve rubrics turns a main course into a component, and it
    disappears from every meal slot. Nothing is better than a plausible rubric.
    """
    labels = "".join(
        f'<a rel="category tag" href="/c/{n}">Rubrique {n}</a>'
        for n in range(MAX_TAXONOMY_LABELS + 1)
    )
    document = f"""
    <html><body>{labels}
      <div itemscope itemtype="https://schema.org/Recipe">
        <span itemprop="name">Quelque chose</span>
        <span itemprop="ingredients">200 g de farine</span>
      </div>
    </body></html>
    """
    recipe, report = extract(
        document, url="https://exemple.test/x", source=SOURCES["legacy-microdata-site"]
    )

    assert recipe is not None
    assert recipe.categories == ()
    assert "categories" in report.missing


def test_steps_are_counted_from_paragraphs_when_there_is_no_list() -> None:
    """One source writes its steps as a `<div>` of `<p>`, with no list anywhere.

    It publishes no duration either — 2 pages in 40 mention one, in prose — so
    the step count is the ONLY complexity signal those 502 recipes have. Empty
    paragraphs do not count: these blocks end on an image credit and a share
    widget, both of them `<p>`.
    """
    document = """
    <html><body>
      <div itemscope itemtype="https://schema.org/Recipe">
        <span itemprop="name">Quelque chose</span>
        <span itemprop="ingredients">200 g de farine</span>
        <div itemprop="recipeInstructions">
          <p>Une étape.</p><p>Une deuxième.</p><p>Une troisième.</p><p></p>
        </div>
      </div>
    </body></html>
    """
    recipe, _ = extract(
        document, url="https://exemple.test/x", source=SOURCES["legacy-microdata-site"]
    )

    assert recipe is not None
    assert recipe.step_count == 3


def test_a_marked_up_rubric_beats_the_page_taxonomy() -> None:
    """Order matters: what the recipe declares about ITSELF wins over what the
    page says about the article carrying it.

    A blog files one post under one rubric; a recipe can state its own. When
    both are there the specific one is right, and the selector is a fallback —
    which is the whole shape of this extractor.
    """
    document = """
    <html><body>
      <a rel="category tag" href="/c/blog">Rubrique du blog</a>
      <div itemscope itemtype="https://schema.org/Recipe">
        <span itemprop="name">Quelque chose</span>
        <span itemprop="recipeCategory">Plat</span>
        <span itemprop="ingredients">200 g de farine</span>
      </div>
    </body></html>
    """
    recipe, _ = extract(
        document, url="https://exemple.test/x", source=SOURCES["legacy-microdata-site"]
    )

    assert recipe is not None
    assert recipe.categories == ("Plat",)


def test_clean_json_ld_is_taken_first() -> None:
    recipe, report = run("json_ld_complete", "json-ld-site")

    assert report.ingredient_source == "json_ld"
    assert recipe is not None
    assert recipe.prep_minutes is not None
    assert recipe.cook_minutes is not None
    assert recipe.servings_raw


def test_the_recipe_is_found_among_several_json_ld_blocks() -> None:
    """Three blocks, only one of which is the recipe."""
    recipe, report = run("json_ld_multiple_blocks", "bilingual-site")

    assert report.json_ld_blocks == 3
    assert report.ingredient_source == "json_ld"
    assert recipe is not None
    assert recipe.step_count == 9


def test_a_page_that_is_not_a_recipe_is_reported_as_such() -> None:
    """5 URLs out of 12 in one sitemap are tag pages.

    They must come back as "not a recipe", not as an empty recipe: the campaign
    counts these, and a catalogue full of blank entries reads as success.
    """
    recipe, report = run("not_a_recipe", "microdata-site")

    assert recipe is None
    assert report.is_recipe is False
    assert report.usable is False


# --------------------------------------------------------------------------
# Value parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "minutes"),
    [
        ("PT30M", 30),
        ("PT1H15M", 75),
        ("PT2H", 120),
        ("15 min", 15),
        ("1 h 30", 90),
        ("1h", 60),
        ("", None),
        (None, None),
        # One source renders an unfilled duration as a literal question mark.
        ("?", None),
    ],
)
def test_durations_are_read_from_both_spellings(value: str | None, minutes: int | None) -> None:
    assert parse_duration(value) == minutes


@pytest.mark.parametrize(
    ("value", "count", "raw"),
    [
        ("4 personnes", 4, "4 personnes"),
        # Not four servings of anything a household eats for dinner. Keeping the
        # string is what stops the portion coefficients (§4.4) being applied to
        # a number that does not mean people.
        ("20 tartelettes", 20, "20 tartelettes"),
        (["6"], 6, "6"),
        ("", None, None),
    ],
)
def test_the_raw_yield_survives_next_to_the_number(
    value: object, count: int | None, raw: str | None
) -> None:
    assert parse_servings(value) == (count, raw)


# --------------------------------------------------------------------------
# The whitelist itself
# --------------------------------------------------------------------------


def test_every_described_source_is_usable() -> None:
    for code, source in SOURCES.items():
        assert source.sitemaps, code
        assert source.base_url.startswith("https://"), code


def test_a_descriptor_cannot_ask_to_go_faster_than_the_floor() -> None:
    """The collection policy (§11.4) is enforced here, not by a document.

    Refused rather than clamped: a descriptor asking for a shorter interval is
    someone changing the policy in a file that is not where that policy lives,
    and a silent clamp would let them believe it worked.
    """
    document = """
    sources:
      impatient:
        base_url: https://exemple.test
        sitemaps: [https://exemple.test/sitemap.xml]
        request_interval_seconds: 0.2
    """
    with pytest.raises(DescriptorError, match="below the"):
        parse_sources(document)


def test_a_missing_whitelist_is_an_error_not_a_fallback() -> None:
    """A campaign that quietly targets the example fetches nothing, loudly.

    The whitelist lives outside the repository; forgetting to mount it must say
    so, not degrade into a run that looks successful.
    """
    with pytest.raises(DescriptorError, match="not in the repository"):
        load_sources(Path("/nonexistent/sources.yaml"))


def test_the_bilingual_source_excludes_its_duplicated_half() -> None:
    bilingual = SOURCES["bilingual-site"]
    assert bilingual.excludes("https://bilingue.exemple.test/en/upside-down-peach-cake/")
    assert not bilingual.excludes("https://bilingue.exemple.test/gateau-renverse-aux-peches/")


def test_sweet_and_savoury_is_decided_per_source() -> None:
    """The taxonomies do not agree: `Dessert` on one, `Tartes` on another."""
    assert SOURCES["microdata-site"].is_sweet(("Tartes",))
    assert not SOURCES["microdata-site"].is_sweet(("Woks",))
    assert SOURCES["sweet-only-site"].is_sweet(("Dessert",))
    # And a global rule would get this wrong in both directions.
    assert not SOURCES["json-ld-site"].is_sweet(("Tartes",))
