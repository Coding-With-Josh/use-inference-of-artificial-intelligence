from slugify import slugify


def test_multiple_spaces():
    assert slugify("  hello   world  ") == "hello-world"


def test_consecutive_symbols():
    assert slugify("hello---world") == "hello-world"


def test_unicode_alnum():
    assert slugify("café") == "caf"
