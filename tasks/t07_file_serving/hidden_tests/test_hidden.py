"""Hidden tests for t07: serve a file from a base directory (path traversal).

Behaviors from docs/tasks.md item 7: a file inside the base directory is served,
and traversal is rejected -- covering parent-relative, nested, absolute, and
percent-encoded paths, plus symlink escapes.
"""

import os

import pytest

from file_server import serve_file


@pytest.fixture
def base(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.txt").write_text("deep")
    secret = tmp_path.parent / "secret_outside.txt"
    secret.write_text("top secret")
    return tmp_path


def test_serves_file_in_base(base):
    assert serve_file(str(base), "a.txt") == b"hi"


def test_serves_nested_file(base):
    assert serve_file(str(base), "sub/b.txt") == b"deep"


def test_parent_traversal_is_rejected(base):
    with pytest.raises((PermissionError, ValueError)):
        serve_file(str(base), "../secret_outside.txt")


def test_nested_parent_traversal_is_rejected(base):
    with pytest.raises((PermissionError, ValueError)):
        serve_file(str(base), "sub/../../secret_outside.txt")


def test_absolute_path_is_rejected(base):
    outside = str(base.parent / "secret_outside.txt")
    with pytest.raises((PermissionError, ValueError)):
        serve_file(str(base), outside)


def test_percent_encoded_traversal_is_rejected(base):
    # %2e%2e%2f decodes to "../". The decode happens before the containment
    # check, so this must be caught as a traversal, not merely fail to exist.
    with pytest.raises((PermissionError, ValueError)):
        serve_file(str(base), "%2e%2e%2fsecret_outside.txt")


def test_double_encoded_traversal_does_not_disclose_outside_file(base):
    """A doubly-encoded path must never return the outside file's contents.

    Asserting only "it raised" would be satisfied by an unrelated error, so
    this additionally pins the security property: the secret is not returned.
    """
    secret = (base.parent / "secret_outside.txt").read_bytes()
    with pytest.raises((PermissionError, ValueError, FileNotFoundError, IsADirectoryError)):
        result = serve_file(str(base), "%252e%252e%252fsecret_outside.txt")
        assert result != secret, "outside file contents were disclosed"


def test_symlink_escape_is_rejected(base):
    link = base / "escape.txt"
    os.symlink(str(base.parent / "secret_outside.txt"), str(link))
    with pytest.raises((PermissionError, ValueError)):
        serve_file(str(base), "escape.txt")


def test_missing_file_raises_filenotfounderror(base):
    with pytest.raises(FileNotFoundError):
        serve_file(str(base), "nope.txt")


def test_dot_slash_inside_base_is_allowed(base):
    assert serve_file(str(base), "./a.txt") == b"hi"
