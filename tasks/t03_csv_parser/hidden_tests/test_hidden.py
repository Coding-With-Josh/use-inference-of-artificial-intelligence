"""Hidden tests for t03: csv parser with quoted fields and bad rows.

Behaviors from docs/tasks.md item 3: quoted fields survive intact, and
malformed rows do not crash the whole parse.
"""

from csv_parser import parse_csv


def test_empty_document_yields_no_rows():
    assert parse_csv("") == []


def test_header_only_yields_no_rows():
    assert parse_csv("a,b\n") == []


def test_ragged_row_with_missing_field():
    rows = parse_csv("a,b\n1\n")
    assert isinstance(rows, list)
    assert len(rows) == 1


def test_embedded_newline_inside_quotes():
    rows = parse_csv('a,b\n"line1\nline2",2')
    assert rows[0]["a"] == "line1\nline2"


def test_embedded_comma_inside_quotes():
    rows = parse_csv('a,b\n"1,2","3"')
    assert rows[0]["a"] == "1,2"


def test_embedded_quote_is_escaped():
    rows = parse_csv('a\n"say ""hi"""')
    assert rows[0]["a"] == 'say "hi"'


def test_unicode_values_round_trip():
    rows = parse_csv("name\ncafé")
    assert rows[0]["name"] == "café"


def test_multiple_rows_preserve_order():
    rows = parse_csv("a\n1\n2\n3")
    assert [r["a"] for r in rows] == ["1", "2", "3"]


def test_extra_fields_do_not_crash():
    rows = parse_csv("a,b\n1,2,3,4")
    assert rows[0]["a"] == "1"


def test_blank_line_is_tolerated():
    rows = parse_csv("a,b\n1,2\n\n3,4")
    assert isinstance(rows, list)
