from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


def run_in_sandbox(cmd: list[str], workdir: Path | None = None, timeout: int = 120, mem_limit: str = "512m", cpu_limit: str = "1.0") -> dict:
    if not is_docker_available():
        raise RuntimeError("docker is not available; no unsafe local mode is provided")

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--tmpfs",
        "/usr/local/lib/python3.11/site-packages:rw,exec,nosuid,size=128m",
        "--tmpfs",
        "/var/cache:rw,noexec,nosuid,size=16m",
        f"--memory={mem_limit}",
        f"--cpus={cpu_limit}",
        "--user",
        "1000:1000",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if workdir is not None:
        wd = Path(workdir).resolve()
        docker_cmd.extend(["-v", f"{wd}:/app:ro", "-w", "/app"])
    docker_cmd.append("python:3.11-slim")
    docker_cmd.extend(cmd)

    try:
        proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "",
            "timeout": True,
        }
