"""Docker sandbox runner.

This is the *only* code path that executes untrusted task solutions. There is
deliberately no local fallback: if Docker is unusable the runner refuses with an
actionable message rather than running a student's solution on the host.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from pilot.config.config import SandboxConfig

# `docker info` and `docker image inspect` are cheap but not free. Cache them for
# the life of the process so a validation sweep over 10 tasks does not shell out
# to the daemon 40 times.
_DAEMON_OK: bool | None = None
_IMAGE_CACHE: dict[str, bool] = {}


class SandboxUnavailable(RuntimeError):
    """Raised when the sandbox cannot run. Never downgraded to a local run."""


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def is_docker_available() -> bool:
    """True only if the docker *daemon* is reachable.

    Checking `shutil.which("docker")` is not enough: the binary is present when
    Docker Desktop is installed but stopped, which would pass a which-check and
    then fail every run with an opaque daemon error.
    """
    global _DAEMON_OK
    if _DAEMON_OK is not None:
        return _DAEMON_OK
    if shutil.which("docker") is None:
        _DAEMON_OK = False
        return False
    try:
        proc = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    except (subprocess.SubprocessError, OSError):
        _DAEMON_OK = False
        return False
    _DAEMON_OK = proc.returncode == 0
    return _DAEMON_OK


def reset_docker_cache() -> None:
    """Clear the daemon/image caches. For tests that toggle availability."""
    global _DAEMON_OK
    _DAEMON_OK = None
    _IMAGE_CACHE.clear()


def image_exists(image: str) -> bool:
    """True if `image` is present in the local image store."""
    if image in _IMAGE_CACHE:
        return _IMAGE_CACHE[image]
    if not is_docker_available():
        _IMAGE_CACHE[image] = False
        return False
    try:
        proc = _run(["docker", "image", "inspect", image])
        found = proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        found = False
    _IMAGE_CACHE[image] = found
    return found


def _require_sandbox(image: str) -> None:
    """Fail closed, with the exact command to run, if the sandbox is unusable."""
    if shutil.which("docker") is None:
        raise SandboxUnavailable(
            "docker binary not found. Install Docker Desktop; there is no "
            "unsafe local mode, so untrusted solutions cannot be run without it."
        )
    if not is_docker_available():
        raise SandboxUnavailable(
            "docker daemon is not reachable (docker info failed). Start Docker "
            "Desktop and retry; untrusted solutions are never run on the host."
        )
    if not image_exists(image):
        raise SandboxUnavailable(
            f"sandbox image {image!r} is not present locally. "
            "Build it first:  make sandbox-image"
        )


def _build_docker_cmd(
    cmd: list[str],
    workdir: Path | None,
    image: str,
    mem_limit: str,
    cpu_limit: str,
    network_disabled: bool,
    read_only_root: bool,
    extra_mounts: list[str] | None = None,
) -> list[str]:
    """Assemble the isolation flags.

    Every hardening flag here maps to a threat in Phase 3: --network=none kills
    exfiltration, --cap-drop/--security-opt/--user kill privilege escalation,
    --read-only kills persistence, and the :ro bind mount stops the container
    from rewriting the task corpus it is being graded against.
    """
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "1000:1000",
        "--memory",
        mem_limit,
        "--cpus",
        cpu_limit,
    ]
    if network_disabled:
        docker_cmd += ["--network", "none"]
    if read_only_root:
        docker_cmd += [
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
        ]
    if workdir is not None:
        wd = Path(workdir).resolve()
        # Bind mounts are :ro so untrusted code cannot mutate the spec, starter,
        # or the very tests it is being judged by.
        docker_cmd += ["-v", f"{wd}:/app:ro", "-w", "/app"]
    for mount in extra_mounts or []:
        docker_cmd += ["-v", mount]
    docker_cmd.append(image)
    docker_cmd += cmd
    return docker_cmd


def run_in_sandbox(
    cmd: list[str],
    workdir: Path | None = None,
    timeout: int | None = None,
    mem_limit: str | None = None,
    cpu_limit: str | None = None,
    image: str | None = None,
    extra_mounts: list[str] | None = None,
    config: SandboxConfig | None = None,
    network_disabled: bool | None = None,
    read_only_root: bool = True,
) -> dict[str, Any]:
    """Run `cmd` inside the sandbox and return a structured result.

    Image and resource limits come from `SandboxConfig` (env-overridable) rather
    than being hardcoded here, so the harness has one source of truth.

    Returns a dict with `exit_code`, `stdout`, `stderr`, `timeout` and
    `exit_class`. `exit_class` distinguishes a genuine test failure (1) from
    pytest usage/collection errors (4) and "no tests collected" (5) -- conflating
    those is how a broken harness reports a green result.
    """
    cfg = config or SandboxConfig()
    image = image or cfg.docker_image
    mem_limit = mem_limit or f"{cfg.mem_limit_mb}m"
    cpu_limit = cpu_limit or str(cfg.cpu_limit)
    timeout = timeout if timeout is not None else cfg.timeout_s
    if network_disabled is None:
        network_disabled = cfg.network_disabled

    _require_sandbox(image)

    docker_cmd = _build_docker_cmd(
        cmd,
        workdir,
        image,
        mem_limit,
        cpu_limit,
        network_disabled,
        read_only_root,
        extra_mounts,
    )

    try:
        proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        rc = proc.returncode
        stdout, stderr, timed_out = proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        # The client-side timeout fired. --rm makes the daemon reap the
        # container, but we still surface timeout=True so callers can tell a
        # hang apart from a fast failure.
        rc = -1
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        timed_out = True
    except OSError as exc:
        # e.g. the daemon vanished between the check and the run. Fail closed.
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"failed to launch sandbox: {exc}",
            "timeout": False,
            "exit_class": "launch_error",
            "cmd": docker_cmd,
        }

    return {
        "exit_code": rc,
        "stdout": stdout,
        "stderr": stderr,
        "timeout": timed_out,
        "exit_class": classify_exit(rc, timed_out),
        "cmd": docker_cmd,
    }


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


# pytest summary tokens, mapped to the counter they increment.
_SUMMARY_TOKENS = {
    "passed": "passed",
    "failed": "failed",
    "error": "errors",
    "errors": "errors",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
}


def parse_pytest_summary(stdout: str) -> dict[str, Any]:
    """Extract counts and failed node ids from a `pytest -q` run.

    `collected` is derived by summing the outcome counts. It is deliberately
    *not* taken on faith from the caller: a harness that never checks this is
    how a run where pytest collected nothing (exit 5) or errored during
    collection (exit 4) gets mistaken for a passing suite.
    """
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    failed_nodes: list[str] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            node = stripped.split(" ", 1)[1].split(" - ")[0].strip()
            failed_nodes.append(node)
        # The summary line is the one containing " in <time>s".
        if " in " not in stripped:
            continue
        parts = stripped.split()
        for i in range(len(parts) - 1):
            if not parts[i].isdigit():
                continue
            key = _SUMMARY_TOKENS.get(parts[i + 1].strip(","))
            if key:
                counts[key] += int(parts[i])

    collected = sum(counts.values())
    return {**counts, "collected": collected, "failed_nodes": failed_nodes}


def run_pytest_in_sandbox(
    test_paths: list[Path],
    workdir: Path,
    pythonpath: str | None = None,
    timeout: int | None = None,
    config: SandboxConfig | None = None,
    image: str | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run a pytest suite inside the sandbox and return counts plus exit class.

    Paths are passed into the container as absolute `/app`-relative paths so a
    relative-path mistake cannot silently produce "file not found" (exit 4) and
    be mistaken for a test failure.
    """
    cfg = config or SandboxConfig()
    inner: list[str] = ["python", "-m", "pytest"]
    inner += [str(p) for p in test_paths]
    inner += [
        "-p",
        "no:cacheprovider",
        "--override-ini=addopts=",
        "-q",
        "--no-header",
        "--tb=short",
    ]
    if extra_args:
        inner += extra_args
    if pythonpath:
        inner = ["sh", "-c", f"PYTHONPATH={pythonpath} PYTHONDONTWRITEBYTECODE=1 " + " ".join(inner)]

    result = run_in_sandbox(
        inner,
        workdir=workdir,
        timeout=timeout,
        config=cfg,
        image=image,
    )
    summary = parse_pytest_summary(result["stdout"])
    return {**result, **summary}


def classify_exit(rc: int, timed_out: bool = False) -> str:
    """Map a pytest/docker exit code to a semantic class.

    pytest convention: 0 all passed, 1 tests failed, 2 interrupted, 3 internal
    error, 4 usage/collection error, 5 no tests collected.
    """
    if timed_out:
        return "timeout"
    if rc == 0:
        return "passed"
    if rc == 1:
        return "tests_failed"
    if rc == 2:
        return "interrupted"
    if rc == 3:
        return "internal_error"
    if rc == 4:
        return "usage_error"
    if rc == 5:
        return "no_tests_collected"
    if rc == 125:
        return "docker_daemon_error"
    if rc == 126:
        return "container_command_not_executable"
    if rc == 127:
        return "command_not_found"
    if rc < 0 or rc == -1:
        return "launch_error"
    return "other"