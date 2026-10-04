"""Hidden tests for t09: url fetch helper with an allowlist.

Behaviors from docs/tasks.md item 9: only allowlisted hosts are fetched, and
internal/private targets and non-http schemes are rejected. No request is made;
only the decision function is exercised.
"""

import pytest

from url_fetch import fetch_allowed


ALLOW = ["example.com", "api.example.com"]


def test_allowlisted_host_is_permitted():
    assert fetch_allowed("https://example.com/data", ALLOW) is True


def test_second_allowlisted_host_is_permitted():
    assert fetch_allowed("https://api.example.com/v1", ALLOW) is True


def test_host_not_on_allowlist_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("https://evil.com/data", ALLOW)


def test_lookalike_host_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("https://example.com.evil.com/data", ALLOW)


def test_localhost_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("http://localhost:8080/data", ALLOW)


def test_loopback_ip_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("http://127.0.0.1/data", ALLOW)


def test_private_ranges_are_rejected():
    for url in (
        "http://10.0.0.5/data",
        "http://192.168.1.1/data",
        "http://172.16.0.1/data",
    ):
        with pytest.raises(ValueError):
            fetch_allowed(url, ALLOW)


def test_file_scheme_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("file:///etc/passwd", ALLOW)


def test_javascript_scheme_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("javascript:alert(1)", ALLOW)


def test_missing_host_is_rejected():
    with pytest.raises(ValueError):
        fetch_allowed("https:///data", ALLOW)
