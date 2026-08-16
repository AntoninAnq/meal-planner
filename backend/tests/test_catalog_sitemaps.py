"""Reading a site's own index of itself.

The sitemap is the polite way in: it is the list the site publishes about
itself, so following it means never guessing a URL and never crawling links.
"""

from __future__ import annotations

import gzip

from app.catalog.sitemaps import (
    decompress,
    is_index,
    looks_like_a_sitemap,
    read_locations,
)

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://exemple.test/a</loc></url>
  <url><loc>https://exemple.test/b</loc></url>
  <url><loc>https://exemple.test/a</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://exemple.test/post-sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://exemple.test/post-sitemap2.xml</loc></sitemap>
</sitemapindex>"""


def test_an_index_is_told_apart_from_a_list_of_pages() -> None:
    assert is_index(INDEX)
    assert not is_index(URLSET)


def test_gzip_is_handled_even_unannounced() -> None:
    """Several sitemaps are served compressed without a matching header."""
    assert decompress(gzip.compress(URLSET)) == URLSET
    assert read_locations(gzip.compress(URLSET))[0] == "https://exemple.test/a"


def test_locations_keep_their_order_and_are_deduplicated() -> None:
    assert read_locations(URLSET) == ["https://exemple.test/a", "https://exemple.test/b"]


def test_a_malformed_sitemap_is_read_rather_than_discarded() -> None:
    """Sitemaps in the wild carry stray ampersands and undeclared entities.

    A conforming parser refuses documents that every browser and every search
    engine reads fine. Losing three thousand URLs to one bad entry is the wrong
    trade — so a strict parse is tried first, then a tolerant one.
    """
    broken = b"""<urlset>
      <url><loc>https://exemple.test/riz&curry</loc></url>
      <url><loc>https://exemple.test/ok</loc></url>
    </urlset>"""

    assert read_locations(broken) == [
        "https://exemple.test/riz&curry",
        "https://exemple.test/ok",
    ]


def test_a_nested_sitemap_is_recognised_by_its_extension() -> None:
    assert looks_like_a_sitemap("https://exemple.test/post-sitemap1.xml")
    assert looks_like_a_sitemap("https://exemple.test/sitemap.xml.gz")
    assert not looks_like_a_sitemap("https://exemple.test/recette-du-jour")
