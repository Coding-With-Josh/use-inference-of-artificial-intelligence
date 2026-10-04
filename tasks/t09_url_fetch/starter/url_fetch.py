def fetch_allowed(url, allowlist):
    """Decide whether a URL may be fetched.

    Args:
        url: the target URL.
        allowlist: the permitted hosts.

    Returns:
        True if the fetch is permitted.

    Raises:
        NotImplementedError: always; the starter ships no implementation.
    """
    raise NotImplementedError
