from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pilot.sandbox import docker_runner


def _run_in_sandbox(cwd: Path, cmd: list[str]) -> subprocess.CompletedProcess:
    if docker_runner.is_docker_available():
        res = docker_runner.run_in_sandbox(cmd, workdir=cwd, timeout=300)
        return subprocess.CompletedProcess(cmd, res["exit_code"], stdout=res["stdout"], stderr=res["stderr"])
    raise RuntimeError("docker not available; cannot run task validation")


def validate() -> int:
    root = Path(__file__).resolve().parents[3]
    tasks_dir = root / "tasks"
    failures = []
    for tid in sorted(tasks_dir.iterdir()):
        if not tid.is_dir() or tid.name.startswith("_"):
            continue
        ref = tid / "reference"
        if ref.exists():
            cmd = [
                "python",
                "-m",
                "pytest",
                "../visible_tests",
                "../hidden_tests",
                "-p",
                "no:cacheprovider",
                "-q",
            ]
            try:
                cp = _run_in_sandbox(ref, cmd)
                if cp.returncode != 0:
                    failures.append((tid.name, "reference", cp.stdout[-300:]))
            except Exception as e:
                failures.append((tid.name, "reference", str(e)))
        st = tid / "starter"
        if st.exists():
            cmd = [
                "python",
                "-m",
                "pytest",
                "../visible_tests",
                "../hidden_tests",
                "-p",
                "no:cacheprovider",
                "-q",
            ]
            try:
                cp = _run_in_sandbox(st, cmd)
                if cp.returncode == 0:
                    failures.append((tid.name, "starter", "unexpected pass"))
            except Exception:
                pass
    if failures:
        for f in failures:
            print(f"FAIL {f[0]} {f[1]}")
        return 1
    print("OK")
    return 0


def main() -> None:
    sys.exit(validate())


if __name__ == "__main__":
    main()
