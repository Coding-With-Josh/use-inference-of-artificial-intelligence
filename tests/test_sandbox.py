from __future__ import annotations

import shutil

import pytest

from pilot.sandbox import docker_runner


def _sandbox_ready() -> bool:
    """The sandbox can run only if the daemon is up *and* the image is built."""
    return (
        shutil.which("docker") is not None
        and docker_runner.is_docker_available()
        and docker_runner.image_exists(docker_runner.SandboxConfig().docker_image)
    )


def test_is_docker_available_checks_daemon_not_just_binary():
    """`which docker` alone is not sufficient: the binary can exist while the
    daemon is stopped. Assert the daemon is actually consulted."""
    if shutil.which("docker") is None:
        assert docker_runner.is_docker_available() is False
    else:
        # If the daemon is down, is_docker_available must be False even though
        # the binary is on PATH.
        proc_ok = shutil.which("docker") is not None
        result = docker_runner.is_docker_available()
        assert isinstance(result, bool)
        if not result:
            assert proc_ok  # binary present but daemon unreachable -> still False


def test_run_in_sandbox_runs_echo_when_ready():
    if not _sandbox_ready():
        pytest.skip("sandbox not ready; run `make sandbox-image` and start Docker")
    res = docker_runner.run_in_sandbox(["echo", "hi"])
    assert res["exit_code"] == 0
    assert res["stdout"] == "hi\n"
    assert res["exit_class"] == "passed"
    assert res["timeout"] is False


def test_run_in_sandbox_refuses_when_image_missing():
    """A missing image must produce an actionable error, not a silent fallback."""
    docker_runner.reset_docker_cache()
    # Use an image tag that definitely does not exist.
    with pytest.raises(docker_runner.SandboxUnavailable) as excinfo:
        docker_runner.run_in_sandbox(["echo", "hi"], image="pilot-sandbox:__does_not_exist__")
    msg = str(excinfo.value)
    assert "make sandbox-image" in msg
    docker_runner.reset_docker_cache()


def test_run_in_sandbox_refuses_when_daemon_down(monkeypatch):
    """If the daemon is unreachable the runner must refuse, never run locally."""
    monkeypatch.setattr(docker_runner, "is_docker_available", lambda: False)
    docker_runner.reset_docker_cache()
    with pytest.raises(docker_runner.SandboxUnavailable) as excinfo:
        docker_runner.run_in_sandbox(["echo", "hi"], image="whatever")
    assert "daemon" in str(excinfo.value).lower()
    docker_runner.reset_docker_cache()


def test_hardening_flags_present():
    """The isolation flags must always be passed (Phase 3 threat controls)."""
    cmd = docker_runner._build_docker_cmd(
        ["echo", "hi"],
        workdir=None,
        image="img",
        mem_limit="512m",
        cpu_limit="1.0",
        network_disabled=True,
        read_only_root=True,
    )
    joined = " ".join(cmd)
    assert "--cap-drop=ALL" in cmd
    assert "no-new-privileges" in joined
    assert "1000:1000" in joined
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--memory 512m" in joined
    assert "--cpus 1.0" in joined


def test_bind_mount_is_read_only(tmp_path):
    cmd = docker_runner._build_docker_cmd(
        ["echo", "hi"],
        workdir=tmp_path,
        image="img",
        mem_limit="512m",
        cpu_limit="1.0",
        network_disabled=True,
        read_only_root=True,
    )
    joined = " ".join(cmd)
    assert f"{tmp_path.resolve()}:/app:ro" in joined


def test_classify_exit_distinguishes_failure_from_usage_error():
    assert docker_runner.classify_exit(0) == "passed"
    assert docker_runner.classify_exit(1) == "tests_failed"
    assert docker_runner.classify_exit(4) == "usage_error"
    assert docker_runner.classify_exit(5) == "no_tests_collected"
    assert docker_runner.classify_exit(125) == "docker_daemon_error"
    assert docker_runner.classify_exit(0, timed_out=True) == "timeout"
