import time

from rate_limiter import TokenBucket


def test_refills():
    b = TokenBucket(rate=10, capacity=1)
    assert b.allow() is True
    assert b.allow() is False
    time.sleep(0.12)
    assert b.allow() is True


def test_burst_capacity():
    b = TokenBucket(rate=1, capacity=3)
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is False


def test_boundary_refill():
    b = TokenBucket(rate=5, capacity=1)
    assert b.allow() is True
    assert b.allow() is False
    time.sleep(0.21)
    assert b.allow() is True
