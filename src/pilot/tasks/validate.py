from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pilot.sandbox import docker_runner


def _run_in_sandbox_or_local(cwd: Path, cmd: list[str]) -> subprocess.CompletedProcess:
    # try sandbox if docker available
    if docker_runner.is_docker_available():
        res = docker_runner.run_in_sandbox(cmd, workdir=cwd, timeout=180)
        return subprocess.CompletedProcess(cmd, res["exit_code"], stdout=res["stdout"], stderr=res["stderr"])
    # fallback not allowed by rules, but just in case - we should refuse; raise
    raise RuntimeError("docker not available; cannot run task validation")


def validate() -> int:
    root = Path(__file__).resolve().parents[3]
    tasks_dir = root / "tasks"
    failures = []
    for tid in sorted(tasks_dir.iterdir()):
        if not tid.is_dir() or tid.name.startswith("_"):
            continue
        # reference
        ref = tid / "reference"
        if ref.exists():
            cmd = [
                "python",
                "-m",
                "pytest",
                "../visible_tests",
                "../hidden_tests",
                "--override-ini=addopts=",
                "-q",
            ]
            try:
                cp = _run_in_sandbox_or_local(ref, cmd)
                if cp.returncode != 0:
                    failures.append((tid.name, "reference", cp.stdout[-500:]))
            except Exception as e:
                failures.append((tid.name, "reference", str(e)))
        # starter
        st = tid / "starter"
        if st.exists():
            cmd = [
                "python",
                "-m",
                "pytest",
                "../visible_tests",
                "../hidden_tests",
                "--override-ini=addopts=",
                "-q",
            ]
            try:
                cp = _run_in_sandbox_or_local(st, cmd)
                if cp.returncode == 0:  # starters must fail
                    failures.append((tid.name, "starter", "unexpected pass"))
            except Exception as e:
                # if it fails as expected, that's fine? failures might be assertion errors - good
                pass
    if failures:
        for f in failures:
            print(f"FAIL {f[0]} {f[1]}: {f[2]}")
        return 1
    print("OK")
    return 0


def main() -> None:
    sys.exit(validate())


if __name__ == "__main__":
    main()
