from csv_parser import parse_csv


def test_simple():
    rows = parse_csv("a,b\n1,2")
    assert rows[0]["a"] == "1"
    assert rows[0]["b"] == "2"


def test_quoted():
    rows = parse_csv('a,b\n"1,2","3"')
    assert rows[0]["a"] == "1,2"
    assert rows[0]["b"] == "3"
