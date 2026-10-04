def lookup_user(conn, username):
    """Look up a user by username using a parameterized query.

    Args:
        conn: a sqlite3 connection.
        username: the username to look up.

    Returns:
        dict with id and username, or None if no such user.

    Raises:
        NotImplementedError: always; the starter ships no implementation.
    """
    raise NotImplementedError
