"""Reading the whitelist.

A source is described, never coded (I8). Adding one is a block of YAML; the
extractor does not change. The one escape hatch the design allows — naming an
adaptation function — is deliberately absent until a site earns it.

**The whitelist is not in the source tree.** It is mounted, at the path
`CATALOG_SOURCES_PATH` points to. Beyond I8, this repository is public and the
list names sites whose authors were never asked: the mechanism and the
collection policy are published in full and can be audited line by line; who is
fetched is deployment configuration. `backend/sources.example.yaml` is the
template, on fictitious domains.

Everything here is pure: it turns text into frozen objects and validates them.
Nothing fetches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings

#: Shipped with the code, on fictitious domains. Doubles as the test whitelist,
#: which is what keeps it from rotting.
EXAMPLE_SOURCES_FILE = Path(__file__).resolve().parents[2] / "sources.example.yaml"

#: A floor, never a target. `request_interval_seconds` may only be raised —
#: by a site's own Crawl-delay, or by the descriptor.
MINIMUM_INTERVAL_SECONDS = 1.0


class DescriptorError(ValueError):
    """The whitelist is malformed.

    Raised rather than tolerated: a descriptor that half-loads is a campaign
    that fetches at a pace nobody chose.
    """


@dataclass(frozen=True)
class Source:
    code: str
    enabled: bool
    base_url: str
    sitemaps: tuple[str, ...]
    request_interval_seconds: float
    max_pages_per_campaign: int
    user_agent: str
    language: str
    exclude_url_patterns: tuple[str, ...] = ()
    #: CSS selectors, tried only when the structured markup says nothing.
    selectors: dict[str, str] = field(default_factory=dict)
    #: Per-source, because the taxonomies are per-source (§11.5).
    sweet_categories: frozenset[str] = frozenset()

    def excludes(self, url: str) -> bool:
        return any(pattern in url for pattern in self.exclude_url_patterns)

    def is_sweet(self, categories: tuple[str, ...]) -> bool:
        lowered = {category.strip().lower() for category in categories}
        return any(sweet.lower() in lowered for sweet in self.sweet_categories)


def _require(mapping: dict[str, Any], key: str, code: str) -> Any:
    if key not in mapping:
        raise DescriptorError(f"source {code!r}: missing {key!r}")
    return mapping[key]


def parse_sources(document: str) -> dict[str, Source]:
    raw = yaml.safe_load(document) or {}
    defaults = raw.get("defaults") or {}
    sources: dict[str, Source] = {}

    for code, entry in (raw.get("sources") or {}).items():
        interval = float(entry.get("request_interval_seconds",
                                   defaults.get("request_interval_seconds", 3.0)))
        if interval < MINIMUM_INTERVAL_SECONDS:
            # Refused rather than clamped: a descriptor asking to go faster than
            # the floor is someone changing the collection policy in a file that
            # is not where that policy lives (§11.4).
            raise DescriptorError(
                f"source {code!r}: request_interval_seconds={interval} is below the "
                f"{MINIMUM_INTERVAL_SECONDS}s floor"
            )

        sitemaps = tuple(_require(entry, "sitemaps", code))
        if not sitemaps:
            raise DescriptorError(f"source {code!r}: no sitemap, nothing to walk")

        sources[code] = Source(
            code=code,
            enabled=bool(entry.get("enabled", True)),
            base_url=str(_require(entry, "base_url", code)).rstrip("/"),
            sitemaps=sitemaps,
            request_interval_seconds=interval,
            max_pages_per_campaign=int(
                entry.get("max_pages_per_campaign", defaults.get("max_pages_per_campaign", 4000))
            ),
            user_agent=str(entry.get("user_agent", defaults.get("user_agent", ""))),
            language=str(entry.get("language", defaults.get("language", "fr"))),
            exclude_url_patterns=tuple(entry.get("exclude_url_patterns") or ()),
            selectors=dict(entry.get("selectors") or {}),
            sweet_categories=frozenset(entry.get("sweet_categories") or ()),
        )

    if not sources:
        raise DescriptorError("the whitelist is empty")
    return sources


def load_sources(path: Path | None = None) -> dict[str, Source]:
    """Read the mounted whitelist.

    Missing is an error, never a silent fallback to the example: a campaign that
    quietly targets `exemple.test` looks like it worked and fetched nothing.
    """
    target = path or Path(get_settings().catalog_sources_path)
    if not target.is_file():
        raise DescriptorError(
            f"no whitelist at {target}. Copy backend/sources.example.yaml, fill it in, "
            "and mount it — it is deliberately not in the repository."
        )
    return parse_sources(target.read_text(encoding="utf-8"))
