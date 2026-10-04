from file_server import serve_file


def test_path_traversal_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    outside = tmp_path.parent / "evil.txt"
    outside.write_text("bad")
    try:
        serve_file(str(tmp_path), "../evil.txt")
        raise AssertionError("should reject")
    except (ValueError, PermissionError, FileNotFoundError):
        pass
    finally:
        if outside.exists():
            outside.unlink()
