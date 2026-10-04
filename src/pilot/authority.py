"""Scoped authority: restrict model-directed writes to designated files.

Condition C's fourth stage ("scoped authority: writes only to designated task
files; other writes rejected and logged", docs/conditions.md) is implemented
here. This is a trust boundary: a model is untrusted, so the set of paths it may
write is an allow-list decided by the harness, never by the model.

Controls, matching the Phase 3 review:
  * deny by default -- anything not explicitly allowed is refused
  * no absolute paths, no `..` segments, no NUL bytes
  * symlink escape is blocked by resolving and re-checking containment
  * every rejection is recorded with the requested path, so a model probing for
    an escape leaves an audit trail
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class UnauthorizedWrite(PermissionError):
    """Raised when a write target is outside the granted authority."""


@dataclass
class WriteDecision:
    requested: str
    allowed: bool
    reason: str
    resolved: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_record(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "allowed": self.allowed,
            "reason": self.reason,
            "resolved": self.resolved,
            "timestamp": self.timestamp,
        }


class WriteAuthority:
    """Grant write access to an explicit set of relative paths under `root`.

    Args:
        root: directory the authority is scoped to.
        allowed: relative paths (or prefixes) writable without further checks.
        audit_path: optional jsonl file receiving every accept/reject decision.
    """

    def __init__(
        self,
        root: Path,
        allowed: tuple[str, ...],
        audit_path: Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.allowed = tuple(allowed)
        self.audit_path = Path(audit_path) if audit_path else None
        self.decisions: list[WriteDecision] = []

    # -- validation ---------------------------------------------------------

    def _is_allowed_relative(self, candidate: str) -> bool:
        """Allow-list check on the *relative* path, before touching the disk."""
        normalized = candidate.strip().replace("\\", "/")
        if not normalized:
            return False
        # An exact match, or a path inside an allowed directory.
        return any(
            normalized == allow or normalized.startswith(f"{allow}/") for allow in self.allowed
        )

    def check(self, requested: str) -> WriteDecision:
        """Decide whether `requested` may be written, without writing."""
        # Control: reject NUL bytes, absolute paths and parent traversal before
        # any filesystem call, so a malformed target cannot reach the resolver.
        if "\x00" in requested:
            return self._record(requested, False, "nul byte in path")
        if requested.startswith("/") or Path(requested).is_absolute():
            return self._record(requested, False, "absolute path not permitted")
        if ".." in Path(requested).parts:
            return self._record(requested, False, "parent traversal not permitted")
        if not self._is_allowed_relative(requested):
            return self._record(requested, False, "outside granted authority")

        target = (self.root / requested).resolve()
        # Control: resolve() has followed any symlink, so re-check containment
        # against the real root. This is what stops a symlink planted inside an
        # allowed directory from redirecting the write elsewhere.
        try:
            target.relative_to(self.root)
        except ValueError:
            return self._record(requested, False, "resolves outside root (symlink escape)")
        return self._record(requested, True, "within granted authority", str(target))

    def _record(
        self, requested: str, allowed: bool, reason: str, resolved: str | None = None
    ) -> WriteDecision:
        decision = WriteDecision(
            requested=requested, allowed=allowed, reason=reason, resolved=resolved
        )
        self.decisions.append(decision)
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(decision.as_record()) + "\n")
        return decision

    # -- actions ------------------------------------------------------------

    def write(self, requested: str, content: str) -> Path:
        """Write `content` to `requested`, or raise UnauthorizedWrite."""
        decision = self.check(requested)
        if not decision.allowed:
            raise UnauthorizedWrite(f"write to {requested!r} refused: {decision.reason}")
        assert decision.resolved is not None
        target = Path(decision.resolved)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def rejections(self) -> list[WriteDecision]:
        return [d for d in self.decisions if not d.allowed]

    def grants(self) -> list[WriteDecision]:
        return [d for d in self.decisions if d.allowed]
