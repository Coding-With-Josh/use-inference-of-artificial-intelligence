from rate_limiter import TokenBucket


def test_basic():
    b = TokenBucket(rate=1, capacity=2)
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is False
