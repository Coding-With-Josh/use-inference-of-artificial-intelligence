from signup import validate_signup


def test_valid():
    assert validate_signup("alice@example.com", "password123", "alice") is True


def test_bad_email():
    assert validate_signup("not-an-email", "password123", "alice") is False
