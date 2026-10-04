import time
from rate_limiter import TokenBucket


def test_refills():
    b = TokenBucket(rate=10, capacity=1)
    assert b.allow() is True
    assert b.allow() is False
    time.sleep(0.12)
    assert b.allow() is True
