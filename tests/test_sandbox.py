import os

import pytest

from pilot.sandbox import docker_runner


def test_sandbox_skips_locally_when_docker_absent():
    if docker_runner.is_docker_available():
        pytest.skip("docker available, skip local absence test")
    else:
        with pytest.raises(RuntimeError):
            docker_runner.run_in_sandbox(["echo", "hi"])


def test_sandbox_runs_when_docker_present():
    if not docker_runner.is_docker_available():
        pytest.skip("docker not available")
    else:
        res = docker_runner.run_in_sandbox(["echo", "hi"])
        assert res["exit_code"] == 0
