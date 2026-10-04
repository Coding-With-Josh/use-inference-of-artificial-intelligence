from file_server import serve_file


def test_serve_ok(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    assert serve_file(str(tmp_path), "a.txt") == b"hi"


def test_missing(tmp_path):
    try:
        serve_file(str(tmp_path), "no.txt")
        raise AssertionError()
    except FileNotFoundError:
        pass
