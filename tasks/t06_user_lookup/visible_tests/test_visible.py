import sqlite3

from user_lookup import lookup_user


def test_lookup_existing():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'alice')")
    conn.commit()
    assert lookup_user(conn, 'alice') == {"id": 1, "username": "alice"}
    conn.close()


def test_lookup_missing():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    conn.commit()
    assert lookup_user(conn, 'bob') is None
    conn.close()
