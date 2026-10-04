"""Tests for the scoped write authority.

These cover the deny-by-default control and every escape the Phase 3 review
named: absolute paths, parent traversal, NUL bytes, and symlink redirection.
"""

from __future__ import annotations

import os

import pytest

from pilot.authority import UnauthorizedWrite, WriteAuthority


@pytest.fixture
def scoped(tmp_path):
    (tmp_path / "starter").mkdir()
    (tmp_path / "outside").mkdir()
    return tmp_path


def test_allows_granted_relative_path(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    decision = authority.check("starter/solution.py")
    assert decision.allowed is True
    assert decision.reason == "within granted authority"


def test_write_creates_parents_and_file(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    target = authority.write("starter/solution.py", "print('hi')")
    assert target.read_text() == "print('hi')"


def test_denies_unlisted_path_by_default(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    decision = authority.check("secrets.txt")
    assert decision.allowed is False
    assert "outside granted authority" in decision.reason


def test_denies_absolute_path(scoped):
    authority = WriteAuthority(scoped, allowed=("starter",))
    decision = authority.check("/etc/passwd")
    assert decision.allowed is False
    assert "absolute path" in decision.reason


def test_denies_parent_traversal(scoped):
    authority = WriteAuthority(scoped, allowed=("starter",))
    decision = authority.check("starter/../../outside/evil.txt")
    assert decision.allowed is False
    assert "parent traversal" in decision.reason


def test_denies_nul_byte(scoped):
    authority = WriteAuthority(scoped, allowed=("starter",))
    decision = authority.check("starter/sol\x00ution.py")
    assert decision.allowed is False
    assert "nul byte" in decision.reason


def test_denies_empty_path(scoped):
    authority = WriteAuthority(scoped, allowed=("starter",))
    assert authority.check("   ").allowed is False


def test_allows_path_inside_granted_directory(scoped):
    authority = WriteAuthority(scoped, allowed=("starter",))
    assert authority.check("starter/nested/deep.py").allowed is True


def test_prefix_is_not_enough_to_escape(scoped):
    """`starter_evil` must not be granted by an allowance of `starter`."""
    authority = WriteAuthority(scoped, allowed=("starter",))
    assert authority.check("starter_evil/x.py").allowed is False


def test_symlink_escape_is_denied(tmp_path):
    """A symlink planted inside a granted directory must not redirect a write.

    The link target is outside the authority root, which is the only case that
    matters: a symlink resolving *inside* the root is legitimately writable.
    """
    outside = tmp_path / "outside_root"
    outside.mkdir()
    (outside / "target.txt").write_text("secret")

    root = tmp_path / "scoped"
    (root / "starter").mkdir(parents=True)
    link = root / "starter" / "escape.py"
    os.symlink(str(outside / "target.txt"), str(link))

    authority = WriteAuthority(root, allowed=("starter/escape.py",))
    decision = authority.check("starter/escape.py")
    assert decision.allowed is False
    assert "symlink escape" in decision.reason


def test_write_raises_on_denied(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    with pytest.raises(UnauthorizedWrite) as excinfo:
        authority.write("starter/../outside/evil.txt", "x")
    assert "refused" in str(excinfo.value)


def test_denied_write_leaves_no_file(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    with pytest.raises(UnauthorizedWrite):
        authority.write("outside/evil.txt", "x")
    assert not (scoped / "outside" / "evil.txt").exists()


def test_rejections_are_recorded(scoped):
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",))
    authority.write("starter/solution.py", "ok")
    authority.check("nope.txt")
    authority.check("/abs")
    assert len(authority.grants()) == 1
    assert len(authority.rejections()) == 2


def test_decisions_are_audited_to_disk(scoped):
    audit = scoped / "audit" / "writes.jsonl"
    authority = WriteAuthority(scoped, allowed=("starter/solution.py",), audit_path=audit)
    authority.write("starter/solution.py", "ok")
    authority.check("evil.txt")
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 2
    assert '"allowed": true' in lines[0]
    assert '"allowed": false' in lines[1]


def test_empty_allowlist_denies_everything(scoped):
    authority = WriteAuthority(scoped, allowed=())
    assert authority.check("starter/solution.py").allowed is False


def test_decision_record_is_serialisable(scoped):
    import json

    authority = WriteAuthority(scoped, allowed=("starter",))
    record = authority.check("starter/a.py").as_record()
    json.dumps(record)  # must not raise
    assert record["allowed"] is True
    assert "timestamp" in record


def test_authority_scoped_to_root(tmp_path):
    """A different root must not grant access to the original tree."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    authority = WriteAuthority(a, allowed=("starter/solution.py",))
    assert authority.root == a.resolve()
    assert b.resolve() != authority.root
