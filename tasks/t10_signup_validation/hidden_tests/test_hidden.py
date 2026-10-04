from signup import validate_signup


def test_oversized_password():
    longpw = "a" * 200
    assert validate_signup("alice@example.com", longpw, "alice") is False


def test_short_username():
    assert validate_signup("alice@example.com", "password123", "a") is False
