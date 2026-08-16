"""Walking a site's own index of itself.

Pure: bytes in, URLs out. Nothing fetches here — `ingest` hands it what the
fetcher returned, which is what makes the whole traversal testable without a
network.

A sitemap is the polite way in. It is the list the site publishes about itself,
so following it means never guessing a URL and never crawling links.
"""

from __future__ import annotations

import gzip
import re
from xml.etree import ElementTree

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def decompress(payload: bytes) -> bytes:
    """Several sitemaps are served gzipped, sometimes without saying so."""
    if payload[:2] == b"\x1f\x8b":
        return gzip.decompress(payload)
    return payload


def is_index(payload: bytes) -> bool:
    """A `<sitemapindex>` lists other sitemaps rather than pages."""
    head = decompress(payload)[:2000].lower()
    return b"<sitemapindex" in head


def read_locations(payload: bytes) -> list[str]:
    """Every `<loc>`, in order, deduplicated.

    Parsed strictly first, then by regex. Not laziness: sitemaps in the wild
    carry stray ampersands and undeclared entities that make a conforming parser
    refuse a document every browser and every search engine reads fine. Losing a
    whole sitemap to one malformed entry is the wrong trade.
    """
    text = decompress(payload)
    found: list[str]
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        found = _LOC.findall(text.decode("utf-8", "replace"))
    else:
        found = [
            element.text.strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "loc" and element.text and element.text.strip()
        ]

    seen: set[str] = set()
    ordered: list[str] = []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def looks_like_a_sitemap(url: str) -> bool:
    return url.lower().endswith((".xml", ".xml.gz"))
