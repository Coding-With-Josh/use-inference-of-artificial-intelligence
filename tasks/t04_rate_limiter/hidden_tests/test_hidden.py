"""Hidden tests for t04: token-bucket rate limiter.

Behaviors from docs/tasks.md item 4: the bucket starts full, denies once
drained, and refills at the configured rate without exceeding capacity.
"""

import time

from rate_limiter import TokenBucket


class _FakeClock:
    """Deterministic replacement for time.time so refill is testable."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_starts_full_and_grants_capacity_tokens(monkeypatch):
    monkeypatch.setattr(time, "time", _FakeClock())
    b = TokenBucket(rate=1, capacity=3)
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is False


def test_denies_when_empty(monkeypatch):
    monkeypatch.setattr(time, "time", _FakeClock())
    b = TokenBucket(rate=1, capacity=1)
    assert b.allow() is True
    assert b.allow() is False


def test_refills_after_elapsed_time(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "time", clock)
    b = TokenBucket(rate=1, capacity=1)
    assert b.allow() is True
    assert b.allow() is False
    clock.advance(2.0)
    assert b.allow() is True


def test_refill_respects_rate(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "time", clock)
    b = TokenBucket(rate=1, capacity=10)
    for _ in range(10):
        assert b.allow() is True
    clock.advance(0.5)  # only half a token accrued
    assert b.allow() is False
    clock.advance(0.5)  # now a full token
    assert b.allow() is True


def test_never_exceeds_capacity(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "time", clock)
    b = TokenBucket(rate=100, capacity=2)
    clock.advance(1000.0)  # huge idle period
    granted = sum(1 for _ in range(5) if b.allow())
    assert granted == 2


def test_allow_returns_booleans(monkeypatch):
    monkeypatch.setattr(time, "time", _FakeClock())
    b = TokenBucket(rate=1, capacity=1)
    assert isinstance(b.allow(), bool)
    assert isinstance(b.allow(), bool)


def test_instances_are_independent(monkeypatch):
    monkeypatch.setattr(time, "time", _FakeClock())
    a = TokenBucket(rate=1, capacity=1)
    c = TokenBucket(rate=1, capacity=1)
    assert a.allow() is True
    assert c.allow() is True
    assert a.allow() is False
    assert c.allow() is False
