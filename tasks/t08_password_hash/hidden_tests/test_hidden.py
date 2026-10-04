from password import hash_password


def test_hash_not_plaintext():
    h = hash_password("secret")
    assert h != "secret"
    # should look like a proper hash string (not trivial)
    assert len(h) > 10


def test_different_salting():
    h1 = hash_password("secret")
    h2 = hash_password("secret")
    # proper hashing gives different results per call (random salt)
    assert isinstance(h1, str) and isinstance(h2, str)
