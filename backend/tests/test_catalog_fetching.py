"""The manners, exercised.

Every rule in §11.4 is checked here against a fake transport, a fake clock and a
fake sleep. The reasoning is the same one that made `FakeLLMClient` a first-class
implementation (§13.3): a policy that is never exercised before the day it
matters will be wrong that day, and this one governs what we do to servers
belonging to people who never agreed to any of it.

Nothing here touches a network, and nothing here waits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.catalog.descriptors import Source
from app.catalog.fetching import (
    MAX_CONSECUTIVE_ERRORS,
    DomainAbandoned,
    PoliteFetcher,
    Response,
    ResponseCache,
)


class FakeTransport:
    """Scripted answers, and a log of exactly what was asked and when."""

    def __init__(self, answers: dict[str, list[Response]] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.default = Response(status=200, body=b"<html></html>")

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> Response:
        self.calls.append((url, dict(headers)))
        queued = self.answers.get(url)
        if not queued:
            return self.default
        return queued.pop(0) if len(queued) > 1 else queued[0]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_source(**overrides) -> Source:
    defaults = dict(
        code="test",
        enabled=True,
        base_url="https://exemple.test",
        sitemaps=("https://exemple.test/sitemap.xml",),
        request_interval_seconds=3.0,
        max_pages_per_campaign=100,
        user_agent="meal-planner/test",
        language="fr",
    )
    return Source(**{**defaults, **overrides})


def make_fetcher(transport: FakeTransport, clock: FakeClock, **overrides) -> PoliteFetcher:
    return PoliteFetcher(
        source=make_source(**overrides),
        transport=transport,
        clock=clock.time,
        sleep=clock.sleep,
    )


# --------------------------------------------------------------------------
# Pacing
# --------------------------------------------------------------------------


def test_requests_are_spaced_by_the_interval() -> None:
    clock, transport = FakeClock(), FakeTransport()
    fetcher = make_fetcher(transport, clock)

    for n in range(3):
        fetcher.fetch(f"https://exemple.test/{n}")

    # The first goes out immediately; each of the others waits its turn.
    assert clock.slept == [3.0, 3.0]


def test_time_already_spent_counts_towards_the_interval() -> None:
    """Waiting the full interval on top of a slow response would be wrong.

    The pace is one request every N seconds, not N seconds of idling between
    them — otherwise a site that answers slowly gets crawled more gently than
    intended, which sounds harmless but means a campaign silently takes days.
    """
    clock, transport = FakeClock(), FakeTransport()
    fetcher = make_fetcher(transport, clock)

    fetcher.fetch("https://exemple.test/1")
    clock.now += 2.5
    fetcher.fetch("https://exemple.test/2")

    assert clock.slept == [pytest.approx(0.5)]


def test_a_declared_crawl_delay_can_only_slow_us_down() -> None:
    """The descriptor says what we are willing to do; the site says what it wants.

    We take the gentler of the two, in both directions: a site asking for 10s
    gets 10s, and a site asking for 1s still gets our 3s.
    """
    clock = FakeClock()
    slow = FakeTransport(
        {"https://exemple.test/robots.txt": [Response(200, b"User-agent: *\nCrawl-delay: 10\n")]}
    )
    fetcher = make_fetcher(slow, clock)
    fetcher.load_robots()
    fetcher.fetch("https://exemple.test/a")
    fetcher.fetch("https://exemple.test/b")
    assert clock.slept[-1] == 10.0

    clock = FakeClock()
    fast = FakeTransport(
        {"https://exemple.test/robots.txt": [Response(200, b"User-agent: *\nCrawl-delay: 1\n")]}
    )
    fetcher = make_fetcher(fast, clock)
    fetcher.load_robots()
    fetcher.fetch("https://exemple.test/a")
    fetcher.fetch("https://exemple.test/b")
    assert clock.slept[-1] == 3.0


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------


def test_a_disallowed_path_is_never_requested() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        {"https://exemple.test/robots.txt": [Response(200, b"User-agent: *\nDisallow: /prive/\n")]}
    )
    fetcher = make_fetcher(transport, clock)
    fetcher.load_robots()
    transport.calls.clear()

    assert fetcher.fetch("https://exemple.test/prive/secret") is None
    assert transport.calls == []
    assert fetcher.stats.disallowed == 1

    assert fetcher.fetch("https://exemple.test/public") is not None


def test_an_unreadable_robots_is_not_taken_as_permission_to_hurry() -> None:
    """It means "no rules stated", not "no rules".

    The interval stays at the descriptor's value rather than falling back to
    anything faster — a server that cannot serve its own robots.txt is not a
    server to lean on.
    """
    clock = FakeClock()

    class Broken(FakeTransport):
        def get(self, url, *, headers, timeout):
            if url.endswith("robots.txt"):
                raise ConnectionError("refused")
            return super().get(url, headers=headers, timeout=timeout)

    fetcher = make_fetcher(Broken(), clock)
    fetcher.load_robots()

    fetcher.fetch("https://exemple.test/a")
    fetcher.fetch("https://exemple.test/b")
    assert clock.slept == [3.0]


# --------------------------------------------------------------------------
# Backing off
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503])
def test_the_server_asking_us_to_slow_down_is_obeyed(status: int) -> None:
    """Retrying at the normal pace would be ignoring what it just said."""
    clock = FakeClock()
    transport = FakeTransport({"https://exemple.test/a": [Response(status, b"")]})
    fetcher = make_fetcher(transport, clock)

    assert fetcher.fetch("https://exemple.test/a") is None
    # Doubling each time: the waits grow instead of repeating.
    assert clock.slept == [3.0, 6.0]
    assert fetcher.stats.failed == 1


def test_a_404_is_an_answer_not_a_failure_to_retry() -> None:
    clock = FakeClock()
    transport = FakeTransport({"https://exemple.test/gone": [Response(404, b"")]})
    fetcher = make_fetcher(transport, clock)

    assert fetcher.fetch("https://exemple.test/gone") is None
    assert len(transport.calls) == 1
    assert clock.slept == []


def test_a_domain_that_keeps_failing_is_left_alone() -> None:
    """A site answering with errors is telling us something.

    The campaign for that domain ends; it does not keep knocking. This is the
    difference between a pipeline and a nuisance.
    """
    clock = FakeClock()
    transport = FakeTransport()
    transport.default = Response(status=500, body=b"")
    fetcher = make_fetcher(transport, clock)

    with pytest.raises(DomainAbandoned):
        for n in range(MAX_CONSECUTIVE_ERRORS + 2):
            fetcher.fetch(f"https://exemple.test/{n}")


def test_success_clears_the_failure_count() -> None:
    """Otherwise a long campaign with scattered errors abandons a healthy site."""
    clock = FakeClock()
    transport = FakeTransport(
        {
            "https://exemple.test/flaky": [Response(500, b""), Response(200, b"<html></html>")],
        }
    )
    fetcher = make_fetcher(transport, clock)

    assert fetcher.fetch("https://exemple.test/flaky") is not None
    for n in range(MAX_CONSECUTIVE_ERRORS):
        fetcher.fetch(f"https://exemple.test/ok{n}")  # never raises


# --------------------------------------------------------------------------
# Cache and conditional requests
# --------------------------------------------------------------------------


def test_a_fresh_cache_entry_costs_the_server_nothing(tmp_path: Path) -> None:
    clock = FakeClock()
    cache = ResponseCache(tmp_path, ttl_seconds=3600, clock=clock.time)
    transport = FakeTransport({"https://exemple.test/a": [Response(200, b"<html>x</html>")]})
    fetcher = make_fetcher(transport, clock)
    fetcher.cache = cache

    first = fetcher.fetch("https://exemple.test/a")
    second = fetcher.fetch("https://exemple.test/a")

    assert first is not None and second is not None
    assert first.body == second.body
    assert len(transport.calls) == 1
    assert fetcher.stats.from_cache == 1


def test_a_stale_entry_still_spares_the_transfer(tmp_path: Path) -> None:
    """This is what makes a second campaign nearly free for the other side.

    The body has expired, but the validators have not: the request goes out
    conditional, and a `304` transfers nothing.
    """
    clock = FakeClock()
    cache = ResponseCache(tmp_path, ttl_seconds=10, clock=clock.time)
    cache.write("https://exemple.test/a", Response(200, b"<html>x</html>", etag='W/"abc"'))
    clock.now += 100

    transport = FakeTransport({"https://exemple.test/a": [Response(304, b"")]})
    fetcher = make_fetcher(transport, clock)
    fetcher.cache = cache

    response = fetcher.fetch("https://exemple.test/a")

    assert response is not None and response.unchanged
    assert transport.calls[0][1]["If-None-Match"] == 'W/"abc"'
    assert fetcher.stats.not_modified == 1


def test_the_cache_can_be_emptied(tmp_path: Path) -> None:
    """It is a campaign artefact, not an archive of anyone's pages (I9)."""
    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.write("https://exemple.test/a", Response(200, b"x"))
    cache.write("https://exemple.test/b", Response(200, b"y"))

    assert cache.purge() == 2
    assert cache.read("https://exemple.test/a") == (None, {})


def test_every_request_says_who_we_are() -> None:
    clock, transport = FakeClock(), FakeTransport()
    fetcher = make_fetcher(transport, clock)

    fetcher.fetch("https://exemple.test/a")

    assert transport.calls[0][1]["User-Agent"] == "meal-planner/test"
