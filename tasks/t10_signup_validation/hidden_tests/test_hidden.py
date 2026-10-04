"""Hidden tests for t10: user input validation for a signup form.

Behaviors from docs/tasks.md item 10: malformed and oversized input is rejected
on every field, and non-string input is rejected rather than raising.
"""

import pytest

from signup import validate_signup


def test_valid_signup_is_accepted():
    assert validate_signup("alice@example.com", "password123", "alice") is True


def test_email_without_at_sign_is_rejected():
    assert validate_signup("not-an-email", "password123", "alice") is False


def test_email_without_domain_is_rejected():
    assert validate_signup("alice@", "password123", "alice") is False


def test_empty_email_is_rejected():
    assert validate_signup("", "password123", "alice") is False


def test_oversized_email_is_rejected():
    assert validate_signup("a" * 250 + "@example.com", "password123", "alice") is False


def test_short_password_is_rejected():
    assert validate_signup("alice@example.com", "short", "alice") is False


def test_oversized_password_is_rejected():
    assert validate_signup("alice@example.com", "x" * 200, "alice") is False


def test_empty_password_is_rejected():
    assert validate_signup("alice@example.com", "", "alice") is False


def test_short_username_is_rejected():
    assert validate_signup("alice@example.com", "password123", "ab") is False


def test_oversized_username_is_rejected():
    assert validate_signup("alice@example.com", "password123", "u" * 100) is False


def test_empty_username_is_rejected():
    assert validate_signup("alice@example.com", "password123", "") is False


@pytest.mark.parametrize("bad", [None, 123, [], {}])
def test_non_string_inputs_are_rejected_not_raised(bad):
    assert validate_signup(bad, "password123", "alice") is False
    assert validate_signup("alice@example.com", bad, "alice") is False
    assert validate_signup("alice@example.com", "password123", bad) is False
