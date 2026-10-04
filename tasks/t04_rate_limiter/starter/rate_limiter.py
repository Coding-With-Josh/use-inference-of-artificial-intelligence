class TokenBucket:
    """Token-bucket rate limiter.

    Args:
        rate: tokens added per second.
        capacity: maximum tokens held.

    Raises:
        NotImplementedError: on construction; the starter ships no implementation.
    """

    def __init__(self, rate, capacity):
        """Create a bucket starting full.

        Args:
            rate: tokens added per second.
            capacity: maximum tokens held.

        Raises:
            NotImplementedError: always; the starter ships no implementation.
        """
        raise NotImplementedError

    def allow(self):
        """Consume one token if available.

        Returns:
            True if a token was consumed, False if the bucket is empty.

        Raises:
            NotImplementedError: always; the starter ships no implementation.
        """
        raise NotImplementedError
