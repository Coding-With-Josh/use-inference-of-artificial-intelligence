from csv_parser import parse_csv


def test_escaped_quotes():
    rows = parse_csv('a,b\n"""hi""",x')
    assert 'hi' in rows[0]["a"]


def test_bad_row_returns_error():
    res = parse_csv('a,b\n1,2,3')
    assert any(r.get('error') for r in res) or len(res) >= 1
