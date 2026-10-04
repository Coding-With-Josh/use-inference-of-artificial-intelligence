import os
import subprocess
from pathlib import Path

import pytest


FIXTURES = [
    ("t06_user_lookup", ["../hidden_tests/test_hidden.py"]),
    ("t07_file_serving", ["../hidden_tests/test_hidden.py"]),
    ("t08_password_hash", ["../hidden_tests/test_hidden.py"]),
    ("t09_url_fetch", ["../hidden_tests/test_hidden.py"]),
    ("t10_signup_validation", ["../hidden_tests/test_hidden.py"]),
]


@pytest.mark.parametrize("task,tests", FIXTURES)
def test_unsafe_fails_hidden(task, tests):
    root = Path(__file__).parent.parent / "tasks" / task
    unsafe_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "unsafe"
    env = os.environ.copy()
    # put unsafe dir first so task module resolves to unsafe
    env["PYTHONPATH"] = str(unsafe_dir) + ":" + str(root)
    res = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", *tests, "--override-ini=addopts="],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # unsafe implementation should fail at least one test
    assert res.returncode != 0, f"{task} unsafe unexpectedly passed:\n{res.stdout}"
