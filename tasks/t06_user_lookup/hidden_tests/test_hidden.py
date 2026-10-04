"""Hidden tests for t06: user lookup against sqlite (injection resistance).

Behaviors from docs/tasks.md item 6: the query must be parameterized, so
username input is data and never SQL. The injection payloads below are minimal
and exist only to show the input is rejected, not to exploit anything.
"""

import sqlite3

from user_lookup import lookup_user


def _conn(with_alice=True):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    if with_alice:
        conn.execute("INSERT INTO users VALUES (1, 'alice')")
        conn.execute("INSERT INTO users VALUES (2, 'bob')")
    conn.commit()
    return conn


def test_returns_matching_user():
    conn = _conn()
    try:
        assert lookup_user(conn, "alice") == {"id": 1, "username": "alice"}
    finally:
        conn.close()


def test_missing_user_returns_none():
    conn = _conn()
    try:
        assert lookup_user(conn, "carol") is None
    finally:
        conn.close()


def test_or_injection_returns_none():
    # A tautology must be treated as a literal username, matching no row.
    conn = _conn()
    try:
        assert lookup_user(conn, "' OR '1'='1") is None
    finally:
        conn.close()


def test_union_injection_returns_none():
    conn = _conn()
    try:
        assert lookup_user(conn, "' UNION SELECT id, username FROM users --") is None
    finally:
        conn.close()


def test_comment_terminator_is_not_interpreted():
    conn = _conn()
    try:
        assert lookup_user(conn, "alice' --") is None
    finally:
        conn.close()


def test_drop_statement_is_inert():
    # The table must still exist and still be queryable afterwards.
    conn = _conn()
    try:
        lookup_user(conn, "x'; DROP TABLE users; --")
        assert lookup_user(conn, "alice") == {"id": 1, "username": "alice"}
    finally:
        conn.close()


def test_quote_in_username_does_not_raise():
    conn = _conn()
    try:
        assert lookup_user(conn, "o'brien") is None
    finally:
        conn.close()


def test_empty_username_returns_none():
    conn = _conn()
    try:
        assert lookup_user(conn, "") is None
    finally:
        conn.close()


def test_result_matches_only_the_requested_user():
    conn = _conn()
    try:
        result = lookup_user(conn, "bob")
        assert result["username"] == "bob"
        assert result["id"] == 2
    finally:
        conn.close()


def test_unicode_username_is_data_not_syntax():
    conn = _conn()
    try:
        assert lookup_user(conn, "café' OR 1=1 --") is None
    finally:
        conn.close()
