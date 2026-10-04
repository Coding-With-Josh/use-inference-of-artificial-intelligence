from password import hash_password, verify_password


def test_hash_is_salted():
    h1 = hash_password("secret")
    h2 = hash_password("secret")
    assert h1 != h2


def test_not_fast_hash_hex():
    h = hash_password("secret")
    # reject trivial hex digests of bare password
    assert h != "secret"
    # must not be pure md5/sha1/sha256 hex of password
    import hashlib

    assert h != hashlib.md5(b"secret").hexdigest()
    assert h != hashlib.sha1(b"secret").hexdigest()
    assert h != hashlib.sha256(b"secret").hexdigest()


def test_verify_correct_and_wrong():
    h = hash_password("secret")
    assert verify_password("secret", h) is True
    assert verify_password("wrong", h) is False


def test_no_plaintext_in_hash():
    pw = "my_secret_password"
    h = hash_password(pw)
    assert pw not in h
