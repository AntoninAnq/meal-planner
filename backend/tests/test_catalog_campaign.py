"""Walking a source, without a network and without a database.

`collect_page_urls` is the part of a campaign that decides *what* gets fetched,
which is the part with consequences for the other side. It is exercised here
against the fake transport; writing rows is checked against a real database
instead, since no assertion about SQLAlchemy proves a foreign key.
"""

from __future__ import annotations

from app.catalog.ingest import CampaignReport, collect_page_urls, spread
from tests.test_catalog_fetching import FakeClock, FakeTransport, make_fetcher

from app.catalog.fetching import Response  # isort: skip

INDEX = b"""<sitemapindex>
  <sitemap><loc>https://exemple.test/post-sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://exemple.test/post-sitemap2.xml</loc></sitemap>
</sitemapindex>"""

PAGE_ONE = b"""<urlset>
  <url><loc>https://exemple.test/recette-a</loc></url>
  <url><loc>https://exemple.test/en/recipe-a</loc></url>
</urlset>"""

PAGE_TWO = b"""<urlset>
  <url><loc>https://exemple.test/recette-b</loc></url>
</urlset>"""


def build(**overrides):
    clock = FakeClock()
    transport = FakeTransport(
        {
            "https://exemple.test/sitemap.xml": [Response(200, INDEX)],
            "https://exemple.test/post-sitemap1.xml": [Response(200, PAGE_ONE)],
            "https://exemple.test/post-sitemap2.xml": [Response(200, PAGE_TWO)],
        }
    )
    return make_fetcher(transport, clock, **overrides), transport


def test_an_index_is_followed_one_level_down() -> None:
    fetcher, _ = build()

    urls, skipped = collect_page_urls(fetcher, fetcher.source)

    assert urls == [
        "https://exemple.test/recette-a",
        "https://exemple.test/en/recipe-a",
        "https://exemple.test/recette-b",
    ]
    assert skipped == 0


def test_excluded_urls_are_dropped_and_counted() -> None:
    """A bilingual source duplicates every recipe.

    Counting the exclusions is what makes it visible that the filter is doing
    something — a silent filter and a broken filter look identical.
    """
    fetcher, _ = build(exclude_url_patterns=("/en/",))

    urls, skipped = collect_page_urls(fetcher, fetcher.source)

    assert urls == ["https://exemple.test/recette-a", "https://exemple.test/recette-b"]
    assert skipped == 1


def test_a_sitemap_is_never_walked_twice() -> None:
    """Indexes in the wild reference each other, and one cycle is one campaign."""
    clock = FakeClock()
    looping = FakeTransport(
        {
            "https://exemple.test/sitemap.xml": [
                Response(200, b"<sitemapindex><sitemap><loc>"
                              b"https://exemple.test/sitemap.xml</loc></sitemap>"
                              b"<sitemap><loc>https://exemple.test/post-sitemap1.xml</loc>"
                              b"</sitemap></sitemapindex>")
            ],
            "https://exemple.test/post-sitemap1.xml": [Response(200, PAGE_ONE)],
        }
    )
    fetcher = make_fetcher(looping, clock)

    urls, _ = collect_page_urls(fetcher, fetcher.source)

    assert len(urls) == 2
    assert [url for url, _ in looping.calls].count("https://exemple.test/sitemap.xml") == 1


def test_a_cap_takes_a_spread_not_the_head() -> None:
    """Sitemaps are not shuffled, and the head is not a sample.

    Measured: the first dozen entries of one source are all tag and ingredient
    pages — a head slice fetches a hundred URLs and finds no recipe. Since the
    first campaigns exist to measure the distribution of ingredient strings, a
    biased subset is worse than a small one.
    """
    urls = [f"https://exemple.test/{n}" for n in range(100)]

    picked = spread(urls, 5)

    assert picked == [
        "https://exemple.test/0",
        "https://exemple.test/20",
        "https://exemple.test/40",
        "https://exemple.test/60",
        "https://exemple.test/80",
    ]
    # Deterministic: a repeated campaign walks the same subset.
    assert spread(urls, 5) == picked
    assert spread(urls, 500) == urls


def test_a_truncated_campaign_says_so() -> None:
    """Silence here reads as "the whole source was covered", and it would be false.

    A ceiling exists so a loop bug cannot become someone else's incident — but a
    ceiling that is hit without a word produces a catalogue quietly missing a
    third of a source (§11.4).
    """
    report = CampaignReport(source_code="test", capped=True)

    assert "PLAFOND ATTEINT" in report.render()
    assert "n'a pas été parcourue en entier" in report.render()
