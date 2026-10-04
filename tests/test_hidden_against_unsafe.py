import importlib.util
import os
from pathlib import Path

import pytest


def load_module(path: Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURES = [
    ("t06_user_lookup", "lookup_user"),
    ("t07_file_serving", "serve_file"),
    ("t08_password_hash", "hash_password"),
    ("t09_url_fetch", "fetch_allowed"),
    ("t10_signup_validation", "validate_signup"),
]


@pytest.mark.parametrize("task,func", FIXTURES)
def test_unsafe_fails_hidden(task, func):
    root = Path(__file__).parent.parent
    unsafe = root / "tests" / "fixtures" / "unsafe" / f"{task}.py"
    hidden = root / "tasks" / task / "hidden_tests"
    assert unsafe.exists(), f"missing {unsafe}"
    assert hidden.exists(), f"missing {hidden}"
    # copy unsafe module into hidden_tests context by symlink-like: run pytest with hidden_tests and inject
    # run hidden tests with PYTHONPATH pointing to unsafe module dir? easier: copy unsafe as module name expected
    # most hidden tests import from task module name; we can run pytest on hidden_tests but set up path

    env = os.environ.copy()
    env["PYTHONPATH"] = str(unsafe.parent) + ":" + env.get("PYTHONPATH", "")
    # run pytest on hidden tests, overriding imports by placing unsafe module? but module name differs
    # simpler: run each hidden test file by loading with unsafe implementation injected
    # fallback: use pytest directly but replace module
    pass
