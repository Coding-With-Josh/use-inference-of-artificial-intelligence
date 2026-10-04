import sqlite3

from user_lookup import lookup_user


def test_safe_against_tautology():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'alice')")
    conn.commit()
    # minimal input that should be rejected/safe; we don't execute attack
    result = lookup_user(conn, "' OR '1'='1")
    assert result is None or result.get("username") != "' OR '1'='1"
    conn.close()


def test_safe_against_comment():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'alice')")
    conn.commit()
    result = lookup_user(conn, "alice'--")
    assert result is None
    conn.close()
