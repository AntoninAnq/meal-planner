"""Fetching, and the manners that go with it.

This is the only part of the system that talks to servers nobody asked. The
policy it implements is `docs/ARCHITECTURE.md` §11.4, and it lives in code
rather than in a document because a rule that only exists in prose is a rule
that gets forgotten at 2am on the third retry.

  * one request at a time per domain, never two connections open at once;
  * a minimum interval between them, which a site's own `Crawl-delay` may only
    RAISE;
  * `robots.txt` fetched first and obeyed;
  * `429` / `503` back off exponentially, and a domain that keeps failing is
    abandoned rather than hammered;
  * conditional requests on anything already seen, so a second campaign costs
    almost nothing to anyone;
  * a hard page ceiling, so a loop bug cannot become someone else's incident.

Transport is an interface with a real implementation and a fake, deliberately —
the same reasoning as the LLM client (§7.1, §13.3). Without a fake, none of the
behaviour above is ever exercised before the day it matters, and the retry path
is the one that will be wrong.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from app.catalog.descriptors import Source

#: Consecutive failures after which a domain is left alone for the rest of the
#: campaign. A site answering with errors is telling us something.
MAX_CONSECUTIVE_ERRORS = 5

#: `429` and `503` are the two ways a server says "slow down" or "not now".
BACKOFF_STATUSES = frozenset({429, 503})
RETRYABLE_STATUSES = BACKOFF_STATUSES | {500, 502, 504}
MAX_RETRIES = 3


class DomainAbandoned(RuntimeError):
    """Raised when a domain has failed too often. Ends its campaign, not the run."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    etag: str | None = None
    last_modified: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def unchanged(self) -> bool:
        return self.status == 304


class Transport(Protocol):
    """One HTTP GET. No retries, no waiting, no policy — that is the fetcher's."""

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> Response: ...


@dataclass
class CampaignStats:
    requested: int = 0
    from_cache: int = 0
    not_modified: int = 0
    failed: int = 0
    disallowed: int = 0
    seconds_waited: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "requested": self.requested,
            "from_cache": self.from_cache,
            "not_modified": self.not_modified,
            "failed": self.failed,
            "disallowed": self.disallowed,
            "seconds_waited": round(self.seconds_waited, 1),
        }


class ResponseCache:
    """Campaign-scoped, on disk, outside the repository.

    It exists so that iterating on a run does not mean asking a stranger's
    server for the same page again. It is NOT an archive: entries expire, and
    `docker compose down -v` removes the volume entirely. Keeping third-party
    pages durably would be the copy I9 forbids (§13.2).
    """

    def __init__(self, directory: Path, ttl_seconds: float, clock: Callable[[], float] = time.time):
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def _entry(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.directory / digest[:2] / f"{digest}.json"

    def read(self, url: str) -> tuple[Response | None, dict[str, str]]:
        """The cached response if it is still fresh, and the validators either way.

        A stale — or shed — entry is not useless: its `ETag` turns the next
        request into a conditional one, and a `304` costs the server nothing but
        a header.
        """
        path = self._entry(url)
        if not path.is_file():
            return None, {}
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None, {}

        validators: dict[str, str] = {}
        if record.get("etag"):
            validators["If-None-Match"] = record["etag"]
        if record.get("last_modified"):
            validators["If-Modified-Since"] = record["last_modified"]

        fresh = self._clock() - record.get("fetched_at", 0) < self.ttl_seconds
        if record.get("body") is None or not fresh:
            return None, validators
        return (
            Response(
                status=record["status"],
                body=record["body"].encode("utf-8", "replace"),
                etag=record.get("etag"),
                last_modified=record.get("last_modified"),
            ),
            validators,
        )

    def write(self, url: str, response: Response) -> None:
        path = self._entry(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "url": url,
                    "status": response.status,
                    "body": response.body.decode("utf-8", "replace"),
                    "etag": response.etag,
                    "last_modified": response.last_modified,
                    "fetched_at": self._clock(),
                }
            ),
            encoding="utf-8",
        )

    def shed_bodies(self) -> tuple[int, int]:
        """Drop every stored page, keep only its validators.

        This is what runs at the end of a campaign, and it is better than a
        blunt purge in both directions that matter.

        **I9**: nothing of anyone's page survives — an `ETag` is an opaque
        string the server itself invented to mean "still the same", not content.
        A cache of full pages kept between campaigns would be the durable copy
        the invariant forbids.

        **Cost to the other side**: the validators are exactly what makes the
        next campaign nearly free for them. Deleting the entries outright would
        throw those away too, and every page would have to be transferred again
        instead of answered with a `304`.

        Measured on a real run: 16 000 entries, 10.8 GB of pages, a few hundred
        kilobytes of validators.
        """
        entries = 0
        freed = 0
        for path in self.directory.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                freed += path.stat().st_size
                path.unlink()
                entries += 1
                continue
            if record.get("body") is None:
                continue
            before = path.stat().st_size
            record["body"] = None
            path.write_text(json.dumps(record), encoding="utf-8")
            freed += before - path.stat().st_size
            entries += 1
        return entries, freed

    def purge(self) -> int:
        """Remove everything, validators included. Only on explicit request."""
        removed = 0
        for entry in self.directory.rglob("*.json"):
            entry.unlink()
            removed += 1
        return removed


@dataclass
class PoliteFetcher:
    """Serial within a domain, and never faster than the interval.

    The clock and the sleep are injected so the pacing can be asserted in a test
    without a test that takes three seconds per request to run.
    """

    source: Source
    transport: Transport
    cache: ResponseCache | None = None
    timeout: float = 30.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    stats: CampaignStats = field(default_factory=CampaignStats)
    _last_request_at: float | None = field(default=None, init=False)
    _consecutive_errors: int = field(default=0, init=False)
    _robots: urllib.robotparser.RobotFileParser | None = field(default=None, init=False)
    _interval: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._interval = self.source.request_interval_seconds

    # -- politeness ------------------------------------------------------

    def load_robots(self) -> None:
        """Read `robots.txt` before anything else, and let it slow us down.

        A declared `Crawl-delay` RAISES the interval and can never lower it: the
        descriptor states what we are willing to do, the site states what it
        wants, and we take the gentler of the two.
        """
        parser = urllib.robotparser.RobotFileParser()
        url = f"{self.source.base_url}/robots.txt"
        try:
            response = self.transport.get(
                url, headers={"User-Agent": self.source.user_agent}, timeout=self.timeout
            )
        except Exception:
            # Unreadable robots.txt is not permission. Treated as "no rules
            # stated", but the interval stays at the descriptor's value.
            parser.parse([])
        else:
            parser.parse(response.body.decode("utf-8", "replace").splitlines())
        self._robots = parser

        declared = parser.crawl_delay(self.source.user_agent)
        if declared is not None:
            self._interval = max(self._interval, float(declared))

    def allowed(self, url: str) -> bool:
        if self._robots is None:
            return True
        return self._robots.can_fetch(self.source.user_agent, url)

    def _wait_turn(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self._interval - (self.clock() - self._last_request_at)
        if remaining > 0:
            self.stats.seconds_waited += remaining
            self.sleep(remaining)

    # -- fetching --------------------------------------------------------

    def fetch(self, url: str) -> Response | None:
        """One page, cached, conditional, paced, and retried within reason.

        Returns None when the page could not be had — disallowed, or failed past
        retrying. The reason is counted; the caller does not need to care which.
        """
        if not self.allowed(url):
            self.stats.disallowed += 1
            return None

        validators: dict[str, str] = {}
        if self.cache is not None:
            cached, validators = self.cache.read(url)
            if cached is not None:
                self.stats.from_cache += 1
                return cached

        headers = {"User-Agent": self.source.user_agent, **validators}
        backoff = self._interval

        for attempt in range(1, MAX_RETRIES + 1):
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                raise DomainAbandoned(
                    f"{self.source.code}: {MAX_CONSECUTIVE_ERRORS} consecutive failures, "
                    "leaving this domain alone"
                )

            self._wait_turn()
            self.stats.requested += 1
            try:
                response = self.transport.get(url, headers=headers, timeout=self.timeout)
            except Exception:
                response = Response(status=0, body=b"")
            finally:
                self._last_request_at = self.clock()

            if response.unchanged:
                self._consecutive_errors = 0
                self.stats.not_modified += 1
                return response

            if response.ok:
                self._consecutive_errors = 0
                if self.cache is not None:
                    self.cache.write(url, response)
                return response

            if response.status not in RETRYABLE_STATUSES and response.status != 0:
                # A 404 or a 410 is an answer, not a failure to retry.
                self._consecutive_errors = 0
                self.stats.failed += 1
                return None

            self._consecutive_errors += 1
            # The server said slow down. Retrying at the normal interval would
            # be ignoring it.
            if attempt < MAX_RETRIES and response.status in BACKOFF_STATUSES:
                self.stats.seconds_waited += backoff
                self.sleep(backoff)
                backoff *= 2

        self.stats.failed += 1
        return None


class HttpxTransport:
    """The real one. Redirects followed, compression negotiated, nothing else."""

    def __init__(self) -> None:
        import httpx

        self._client = httpx.Client(follow_redirects=True)

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> Response:
        response = self._client.get(url, headers=headers, timeout=timeout)
        return Response(
            status=response.status_code,
            body=response.content,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

    def close(self) -> None:
        self._client.close()


def domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower()
