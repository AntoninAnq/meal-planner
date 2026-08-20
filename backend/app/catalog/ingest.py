"""One campaign: walk a source, extract, write, report.

The shape is deliberately dull — sitemaps, then pages, then rows. What is not
dull is what it refuses to do:

* **It never writes `allergens_verified`.** That flag is derived by the
  resolution pass from resolved ingredients, and only from those (I3). A
  collection pipeline that set it would be declaring a safety property it has no
  way of knowing.
* **It never writes `recipe_allergen`.** Same reason, one step further (I2).
* **It counts everything it could not do.** A campaign that reports "1 200
  recipes" without saying that 300 pages failed to parse is a catalogue with
  holes nobody knows about.

Re-running is safe and is the normal case: recipes are keyed by `source_url`, so
a second campaign updates rather than duplicates, and conditional requests make
most of it cost a `304`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.catalog import sitemaps
from app.catalog.descriptors import Source
from app.catalog.extraction import ParsedRecipe, extract
from app.catalog.fetching import CampaignStats, DomainAbandoned, PoliteFetcher
from app.db.models import Recipe, RecipeIngredient, RecipeSuitableStage
from app.domain.enums import LifeStage, RecipeSourceType

#: §4.5. `baby` is never reachable from scraping — an assumed limit of the
#: wedge, not an omission. Phase 1 makes no model call, so this default stands
#: over the whole scraped catalogue (§6.4).
DEFAULT_STAGES = (LifeStage.YOUNG_CHILD, LifeStage.TEEN_ADULT)


@dataclass
class CampaignReport:
    source_code: str
    urls_seen: int = 0
    urls_skipped: int = 0
    pages_fetched: int = 0
    not_a_recipe: int = 0
    no_ingredients: int = 0
    recipes_written: int = 0
    recipes_updated: int = 0
    json_ld_repaired: int = 0
    json_ld_unparsable: int = 0
    missing_prep: int = 0
    missing_cook: int = 0
    missing_servings: int = 0
    #: Counted like the other gaps, and it is the one that costs the most: an
    #: unread rubric is not an absent field, it is a recipe that passes the
    #: meal-slot filter without anyone having decided it should.
    missing_categories: int = 0
    sweet: int = 0
    write_errors: int = 0
    write_error_samples: list[str] = field(default_factory=list)
    capped: bool = False
    abandoned: str | None = None
    fetch: CampaignStats = field(default_factory=CampaignStats)

    def render(self) -> str:
        lines = [
            f"source            {self.source_code}",
            f"URLs au sitemap   {self.urls_seen} (dont {self.urls_skipped} exclues)",
            f"pages récupérées  {self.pages_fetched}",
            f"  pas une recette {self.not_a_recipe}",
            f"  sans ingrédient {self.no_ingredients}",
            f"recettes écrites  {self.recipes_written} nouvelles, "
            f"{self.recipes_updated} mises à jour ({self.sweet} sucrées)",
            f"JSON-LD           {self.json_ld_repaired} réparés, "
            f"{self.json_ld_unparsable} illisibles",
            f"champs absents    préparation {self.missing_prep}, cuisson {self.missing_cook}, "
            f"portions {self.missing_servings}, rubrique {self.missing_categories}",
            f"réseau            {self.fetch.as_dict()}",
        ]
        if self.write_errors:
            lines.append(f"ÉCHECS D'ÉCRITURE {self.write_errors}")
            lines.extend(f"                  {sample}" for sample in self.write_error_samples)
        if self.capped:
            # Never silent: a truncated campaign that reads as a complete one is
            # how a catalogue ends up quietly missing a third of a source.
            lines.append("PLAFOND ATTEINT   la source n'a pas été parcourue en entier")
        if self.abandoned:
            lines.append(f"ABANDONNÉ         {self.abandoned}")
        return "\n".join(lines)


def collect_page_urls(fetcher: PoliteFetcher, source: Source) -> tuple[list[str], int]:
    """Follow the sitemaps, descending one level into indexes.

    Returns the page URLs and how many were excluded by the descriptor — a
    bilingual site duplicates every recipe, and counting the exclusions is what
    makes it obvious the filter is doing something.
    """
    pending = list(source.sitemaps)
    seen_sitemaps: set[str] = set()
    urls: list[str] = []
    skipped = 0

    while pending:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = fetcher.fetch(sitemap_url)
        if response is None or not response.ok:
            continue

        if sitemaps.is_index(response.body):
            pending.extend(
                url for url in sitemaps.read_locations(response.body) if url not in seen_sitemaps
            )
            continue

        for url in sitemaps.read_locations(response.body):
            if sitemaps.looks_like_a_sitemap(url):
                pending.append(url)
            elif source.excludes(url):
                skipped += 1
            else:
                urls.append(url)

    return urls, skipped


def spread(urls: list[str], ceiling: int) -> list[str]:
    """Take an evenly-spaced subset rather than the first N.

    Sitemaps are not shuffled. On one measured source the first dozen entries
    are all tag and ingredient pages, so a head slice fetches a hundred URLs and
    finds no recipe at all — and a capped campaign would then bias the whole
    catalogue towards whatever the site happens to list first. That matters
    beyond the smoke test: the point of the first campaigns is to measure the
    distribution of ingredient strings, and a distribution measured on the head
    of a sitemap is a distribution of nothing in particular.

    Deterministic, so a repeated campaign fetches the same subset instead of
    walking a different slice each time.
    """
    if ceiling >= len(urls):
        return urls
    stride = len(urls) / ceiling
    return [urls[int(index * stride)] for index in range(ceiling)]


def _upsert(db: Session, source: Source, url: str, parsed: ParsedRecipe) -> bool:
    """Write one recipe. Returns True when it is a new one.

    `source_url` is the identity, which is what makes a second campaign an
    update. Ingredient lines are replaced wholesale rather than merged: their
    position is part of their meaning, and a source that reorders its list would
    otherwise leave a interleaved mess behind.
    """
    recipe = db.scalar(select(Recipe).where(Recipe.source_url == url))
    created = recipe is None
    if recipe is None:
        recipe = Recipe(source_url=url, source_type=RecipeSourceType.SCRAPED)
        db.add(recipe)

    recipe.title = parsed.title
    recipe.source_code = source.code
    recipe.license = parsed.license
    recipe.instructions_url = url
    recipe.prep_minutes = parsed.prep_minutes
    recipe.cook_minutes = parsed.cook_minutes
    recipe.step_count = parsed.step_count
    recipe.servings = parsed.servings
    recipe.servings_raw = parsed.servings_raw
    recipe.source_categories = list(parsed.categories)
    recipe.last_checked_at = datetime.now(UTC)
    # `allergens_verified` and `recipe_allergen` are NOT touched here: they are
    # derived by the resolution pass, and only from resolved ingredients (I3).

    # Flushed only once every column is set — the row is INSERTed here, and a
    # flush before `title` was assigned would violate its NOT NULL. It has to
    # happen before the wipe below all the same: on a new recipe `recipe.id` is
    # None until the INSERT, and the filter would compile to
    # `WHERE recipe_id IS NULL` and quietly delete nothing.
    db.flush()
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete()

    for line in parsed.ingredients:
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                position=line.position,
                raw_text=line.raw_text,
                is_section=line.is_section,
            )
        )

    if created:
        for stage in DEFAULT_STAGES:
            db.add(RecipeSuitableStage(recipe_id=recipe.id, life_stage=stage))

    return created


def run_campaign(
    db: Session,
    *,
    source: Source,
    fetcher: PoliteFetcher,
    limit: int | None = None,
    dry_run: bool = False,
    on_progress: object = None,
) -> CampaignReport:
    report = CampaignReport(source_code=source.code, fetch=fetcher.stats)

    fetcher.load_robots()

    try:
        urls, skipped = collect_page_urls(fetcher, source)
    except DomainAbandoned as exc:
        report.abandoned = str(exc)
        return report

    report.urls_seen = len(urls) + skipped
    report.urls_skipped = skipped

    ceiling = min(limit or source.max_pages_per_campaign, source.max_pages_per_campaign)
    if len(urls) > ceiling:
        report.capped = True
        urls = spread(urls, ceiling)

    for url in urls:
        try:
            response = fetcher.fetch(url)
        except DomainAbandoned as exc:
            report.abandoned = str(exc)
            break

        if response is None or response.unchanged or not response.ok:
            continue
        report.pages_fetched += 1

        parsed, extraction = extract(
            response.body.decode("utf-8", "replace"), url=url, source=source
        )
        report.json_ld_repaired += extraction.json_ld_repaired
        report.json_ld_unparsable += extraction.json_ld_unparsable

        if parsed is None:
            if extraction.is_recipe:
                report.no_ingredients += 1
            else:
                report.not_a_recipe += 1
            continue

        report.missing_prep += "prep_minutes" in extraction.missing
        report.missing_cook += "cook_minutes" in extraction.missing
        report.missing_servings += "servings" in extraction.missing
        report.missing_categories += "categories" in extraction.missing
        report.sweet += source.is_sweet(parsed.categories)

        if dry_run:
            report.recipes_written += 1
            continue

        # One unwritable page must not end a three-hour campaign. It is counted
        # and named, not swallowed: a write that fails is a bug in the pipeline,
        # and the report is where it has to be visible.
        try:
            if _upsert(db, source, url, parsed):
                report.recipes_written += 1
            else:
                report.recipes_updated += 1
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            report.write_errors += 1
            if len(report.write_error_samples) < 5:
                report.write_error_samples.append(f"{url} — {type(exc).__name__}")

    return report


def cache_directory(path: str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
