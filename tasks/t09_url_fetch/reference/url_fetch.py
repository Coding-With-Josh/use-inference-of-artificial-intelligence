from urllib.parse import urlparse


def fetch_allowed(url, allowlist):
    try:
        parsed = urlparse(url)
    except Exception as err:
        raise ValueError("invalid url") from err
    if parsed.scheme not in ("http", "https"):
        raise ValueError("invalid scheme")
    host = parsed.hostname
    if not host:
        raise ValueError("invalid host")
    if host in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("disallowed")
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172."):
        raise ValueError("disallowed")
    if host not in allowlist:
        raise ValueError("disallowed")
    return True
