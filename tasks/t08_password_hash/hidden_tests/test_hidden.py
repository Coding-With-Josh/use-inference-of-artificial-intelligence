"""Hidden tests for t08: password hash and verify (proper hashing).

Behaviors from docs/tasks.md item 8: hashes are salted, are not a bare fast
hash, verification works, and plaintext is never stored. Every one of these
fails a naive md5 implementation.
"""

import hashlib

from password import hash_password, verify_password


def test_two_hashes_of_same_password_differ():
    # A per-password salt means the digests must not collide.
    assert hash_password("secret") != hash_password("secret")


def test_not_bare_md5_of_password():
    pw = "secret"
    assert hash_password(pw) != hashlib.md5(pw.encode()).hexdigest()


def test_not_bare_sha1_of_password():
    pw = "secret"
    assert hash_password(pw) != hashlib.sha1(pw.encode()).hexdigest()


def test_not_bare_sha256_of_password():
    pw = "secret"
    assert hash_password(pw) != hashlib.sha256(pw.encode()).hexdigest()


def test_hash_is_not_pure_lowercase_hex():
    # md5/sha digests are 32/40/64 lowercase hex chars; a salted encoding is
    # not a bare digest of the password.
    h = hash_password("secret")
    assert not (len(h) == 32 and all(c in "0123456789abcdef" for c in h))


def test_verify_accepts_correct_password():
    h = hash_password("secret")
    assert verify_password("secret", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("secret")
    assert verify_password("wrong", h) is False


def test_plaintext_never_appears_in_hash():
    pw = "correct horse battery staple"
    h = hash_password(pw)
    assert pw not in h
    assert "correct horse" not in h


def test_verify_rejects_malformed_hash_without_raising():
    assert verify_password("secret", "not-a-valid-hash") is False


def test_verify_rejects_empty_hash():
    assert verify_password("secret", "") is False


def test_hash_of_empty_password_is_not_empty_string():
    assert hash_password("") != ""
