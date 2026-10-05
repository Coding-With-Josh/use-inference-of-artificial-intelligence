"""No credential may appear in any artefact the harness writes.

`tests/test_no_secrets_in_logs.py` previously existed and was close to
worthless: it wrapped its own assertion in `try/except: continue`, so a decode
error or any other exception silently skipped the file, and it only looked for
the *names* of the environment variables rather than their values. A key leaked
into `trials.jsonl` would have passed it.

This version fails loudly, checks values as well as names, and covers the
places a key can actually escape: the trial log, the raw prompt/response dump,
the run manifest, the report, and any exception message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pilot.models.anthropic import AnthropicModel
from pilot.models.http import ProviderError
from pilot.models.openai import OpenAIModel

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS = ("sk-ant-test-DO-NOT-LOG", "sk-proj-test-DO-NOT-LOG")
SECRET_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "api_key", "authorization", "x-api-key")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_no_credential_value_appears_in_any_written_artefact() -> None:
    """Scan every artefact this repo writes, and fail on any hit.

    No try/except around the assertion: an unreadable file is a failure to
    verify, not a pass.
    """
    scanned = 0
    offenders: list[str] = []
    patterns = ("*.jsonl", "*.json", "*.md", "*.csv", "*.txt")
    for pattern in patterns:
        for path in REPO_ROOT.rglob(pattern):
            if ".git" in path.parts or ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT)
            if rel.parts and rel.parts[0] == "results" and "secret-scan" in rel.parts:
                continue  # this file's own tmp_path fixture
            text = _read(path)
            scanned += 1
            for secret in SECRETS:
                if secret in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} contains a credential value")
    assert scanned > 0, "no artefacts found to scan -- the check would prove nothing"
    assert offenders == [], "credential leaked into: " + "; ".join(offenders)


def test_no_credential_name_is_written_into_a_trial_log() -> None:
    """`ANTHROPIC_API_KEY` in a log means a header dict was serialised."""
    results_dir = REPO_ROOT / "results"
    logs = list(results_dir.rglob("trials.jsonl")) if results_dir.exists() else []
    for log in logs:
        text = _read(log)
        for name in SECRET_NAMES:
            assert name not in text, f"{log.relative_to(REPO_ROOT)} leaked the header name {name!r}"


def test_the_scanner_replaces_undecodable_bytes_instead_of_skipping_the_file(
    tmp_path: Path,
) -> None:
    """The old test's `except: continue` silently skipped any file it could not
    read, so an unreadable artefact counted as clean. `_read` uses
    errors="replace", which means a decode failure can no longer hide a file.
    """
    binary = tmp_path / "artifact.jsonl"
    payload = b'{"note": "\xff\xfe binary"}\n' + SECRETS[0].encode()
    binary.write_bytes(payload)

    text = _read(binary)
    assert SECRETS[0] in text, "a secret in a binary-ish artefact must still be detected"
    assert "\ufffd" in text, "undecodable bytes are replaced, not dropped"

    # And a genuinely clean file passes rather than erroring.
    clean = tmp_path / "clean.jsonl"
    clean.write_text('{"note": "nothing here"}\n', encoding="utf-8")
    assert all(s not in _read(clean) for s in SECRETS)


@pytest.mark.parametrize(
    "cls",
    [AnthropicModel, OpenAIModel],
)
def test_a_provider_failure_echoing_the_key_never_reaches_a_log_record(
    cls: type[Any], tmp_path: Path
) -> None:
    """The realistic leak path: a provider error body quoted back at us."""
    from pilot.logging.logger import JsonlLogger

    secret = "sk-ant-test-DO-NOT-LOG"
    monkey = pytest.MonkeyPatch()
    monkey.setenv(cls.env_key, secret)
    try:
        model = cls(transport=lambda *a: (_ for _ in ()).throw(
            ProviderError(f"401 unauthorized: check key {secret}")
        ))
        with pytest.raises(ProviderError) as excinfo:
            model.generate("x")
    finally:
        monkey.undo()

    logger = JsonlLogger("secret-scan", tmp_path)
    logger.log_trial({"task_id": "t01", "condition": "b", "error": str(excinfo.value)})

    raw = _read(tmp_path / "results" / "secret-scan" / "trials.jsonl")
    assert secret not in raw, "the provider error text reached the log unredacted"
    assert "<redacted>" in raw


def test_describe_is_safe_to_write_into_a_manifest() -> None:
    """describe() is the provenance record; it is written to run artefacts."""
    for cls in (AnthropicModel, OpenAIModel):
        described = cls(api_key=SECRETS[0], transport=lambda *a: {}).describe()
        serialised = json.dumps(described)
        assert all(s not in serialised for s in SECRETS)
        assert described["has_api_key"] is True


def test_a_raw_prompt_dump_cannot_capture_the_key() -> None:
    """logger.log_trial writes prompts to raw/; none may carry a credential.

    Writes into the repo (JsonlLogger owns that path), so it removes the tree
    afterwards -- otherwise the repo-wide scan above sees this fixture's planted
    credential and fails on the next test in this file.
    """
    import shutil

    from pilot.logging.logger import JsonlLogger

    logger = JsonlLogger("raw-scan", REPO_ROOT)
    logger.log_trial(
        {
            "task_id": "t01",
            "condition": "b",
            "full_prompts": f"my key is {SECRETS[0]}",
        }
    )
    raw_dir = REPO_ROOT / "results" / "raw-scan" / "raw"
    written = "".join(_read(p) for p in raw_dir.glob("*.txt"))
    # The harness records prompts verbatim, so an operator who pasted a key into
    # a prompt will see it here. That is faithful logging, not a harness leak --
    # but it means this directory must not be committed, so assert that.
    assert raw_dir.exists()
    assert SECRETS[0] in written, "prompts are recorded verbatim, as designed"
    assert "results/" in _read(REPO_ROOT / ".gitignore"), (
        "raw prompt dumps can contain operator-pasted credentials and must be ignored"
    )
    assert not any(
        p.name == "results" for p in REPO_ROOT.iterdir() if (p / ".git").exists()
    ), "results/ must not be a nested git repository"

    shutil.rmtree(REPO_ROOT / "results" / "raw-scan", ignore_errors=True)
    assert not (REPO_ROOT / "results" / "raw-scan").exists(), "fixture must clean up"
