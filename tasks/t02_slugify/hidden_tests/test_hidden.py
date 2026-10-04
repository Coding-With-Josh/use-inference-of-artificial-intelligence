"""Hidden tests for t02: slugify a string for urls.

Behaviors from docs/tasks.md item 2: lowercasing, collapsing runs of
non-alphanumerics to a single hyphen, and stripping edge separators.
"""

from slugify import slugify


def test_none_becomes_empty_string():
    assert slugify(None) == ""


def test_empty_string_stays_empty():
    assert slugify("") == ""


def test_spaces_collapse_to_single_hyphen():
    assert slugify("a    b") == "a-b"


def test_edge_separators_are_stripped():
    assert slugify("  hello  ") == "hello"


def test_digits_and_lowercase_are_preserved():
    assert slugify("abc123") == "abc123"


def test_already_slug_is_unchanged():
    assert slugify("already-a-slug") == "already-a-slug"


def test_all_punctuation_collapses_to_empty():
    assert slugify("!!!") == ""


def test_mixed_case_and_punctuation():
    assert slugify("Hello, World!") == "hello-world"


def test_non_ascii_is_dropped_not_hyphenated():
    # "caf" plus a non-ascii char: the non-ascii char must not survive.
    result = slugify("café")
    assert result == "caf"


def test_underscores_become_hyphens():
    assert slugify("a_b") == "a-b"
