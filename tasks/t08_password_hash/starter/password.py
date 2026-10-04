def hash_password(pw):
    """Hash a password with a slow, salted algorithm.

    Args:
        pw: the plaintext password.

    Returns:
        the encoded hash, carrying its own salt.

    Raises:
        NotImplementedError: always; the starter ships no implementation.
    """
    raise NotImplementedError


def verify_password(pw, h):
    """Verify a plaintext password against an encoded hash.

    Args:
        pw: the candidate plaintext password.
        h: the encoded hash produced by hash_password.

    Returns:
        True if the password matches, False otherwise.

    Raises:
        NotImplementedError: always; the starter ships no implementation.
    """
    raise NotImplementedError
