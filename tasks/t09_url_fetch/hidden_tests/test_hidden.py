from url_fetch import fetch_allowed


def test_localhost_blocked():
    try:
        fetch_allowed("http://127.0.0.1/data", ["example.com"])
        assert False
    except ValueError:
        pass


def test_private_ip_blocked():
    try:
        fetch_allowed("http://192.168.1.1/data", ["example.com"])
        assert False
    except ValueError:
        pass
