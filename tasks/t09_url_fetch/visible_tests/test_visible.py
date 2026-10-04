from url_fetch import fetch_allowed


def test_allowed():
    try:
        fetch_allowed("https://example.com/data", ["example.com"])
    except Exception:
        pass


def test_disallowed():
    try:
        fetch_allowed("https://evil.com/data", ["example.com"])
        raise AssertionError()
    except ValueError:
        pass
