from file_server import serve_file


def test_path_traversal_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    outside = tmp_path.parent / "evil.txt"
    outside.write_text("bad")
    try:
        res = serve_file(str(tmp_path), "../evil.txt")
        assert False, "should reject"
    except (ValueError, PermissionError, FileNotFoundError, OSError):
        pass
    finally:
        if outside.exists():
            outside.unlink()


def test_nested_path_traversal_rejected(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("hi")
    try:
        serve_file(str(tmp_path), "sub/../../etc/passwd")
        assert False
    except (ValueError, PermissionError, FileNotFoundError, OSError):
        pass


def test_absolute_path_rejected(tmp_path):
    abs_path = str((tmp_path.parent / "abs.txt").resolve())
    (tmp_path.parent / "abs.txt").write_text("bad")
    try:
        serve_file(str(tmp_path), abs_path)
        assert False
    except (ValueError, PermissionError, FileNotFoundError, OSError):
        pass
    finally:
        p = tmp_path.parent / "abs.txt"
        if p.exists():
            p.unlink()


def test_encoded_traversal_rejected(tmp_path):
    try:
        serve_file(str(tmp_path), "..%2F..%2Fetc%2Fpasswd")
        assert False
    except (ValueError, PermissionError, FileNotFoundError, OSError):
        pass
