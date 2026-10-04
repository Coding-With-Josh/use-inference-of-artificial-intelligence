from __future__ import annotations

import shutil
from pathlib import Path


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


def run_in_sandbox(cmd: list[str], workdir: Path | None = None, timeout: int = 120) -> dict:
    if not is_docker_available():
        raise RuntimeError("docker is not available; no unsafe local mode is provided")
    # minimal stub implementation - full one to be built
    return {"exit_code": 0, "stdout": "", "stderr": "", "timeout": False}
