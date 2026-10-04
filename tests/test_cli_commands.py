"""CLI tests, including a real `demo-mock` run.

`demo-mock` is the repo's proof that the pipeline works end to end, so its test
asserts on artefacts on disk: a watermarked report, a manifest, and figures. A
smoke test that only checks the exit code would pass even if the report were
empty -- which is the failure this repo already shipped once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pilot.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"

runner = CliRunner()


@pytest.fixture
def isolated_results(monkeypatch, tmp_path):
    """Point the CLI at a scratch results directory and a two-task corpus.

    Running demo-mock over all ten tasks takes minutes because condition C drives
    the sandbox; the demo's contract is the same on a two-task corpus. The real
    ten-task run is verified by `make demo-mock`, not by a unit test.
    """
    monkeypatch.setattr("pilot.runner.run.REPO_ROOT", tmp_path)
    monkeypatch.setattr("pilot.cli.REPO_ROOT", tmp_path)

    tasks = tmp_path / "tasks"
    for name in ("t01_alpha", "t02_beta"):
        task = tasks / name
        for sub in ("starter", "reference", "visible_tests", "hidden_tests"):
            (task / sub).mkdir(parents=True)
        (task / "spec.md").write_text(f"# {name}\n\nDo the thing.\n", encoding="utf-8")
        (task / "meta.yaml").write_text("category: core\ndifficulty: 1\n", encoding="utf-8")
        (task / "starter" / "mod.py").write_text("def f():\n    raise NotImplementedError\n")
        # A real hidden suite, so trials are actually graded. An empty
        # hidden_tests/ dir collects nothing, every trial comes back ungraded,
        # and the report correctly renders no figures -- which would make this
        # fixture assert on data that was never measured.
        (task / "hidden_tests" / "test_hidden.py").write_text(
            "from mod import f\n\n\ndef test_calls_into_the_entrypoint():\n"
            "    assert f() == 'expected'\n",
            encoding="utf-8",
        )
    monkeypatch.setattr("pilot.runner.run.TASKS_DIR", tasks)
    return tmp_path


def test_help_lists_the_study_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("study1-plan", "study1-run", "study1-analyze", "tasks-validate", "demo-mock"):
        assert command in result.stdout


def test_study1_plan_prints_counts_and_budget():
    result = runner.invoke(app, ["study1-plan"])
    assert result.exit_code == 0
    assert "trials=" in result.stdout
    assert "cost_estimate_usd=" in result.stdout
    assert "within_budget=" in result.stdout


def test_study1_run_dry_run_makes_no_model_call():
    result = runner.invoke(app, ["study1-run", "--run-id", "cli-dry", "--dry-run"])
    assert result.exit_code == 0
    assert "dry_run=True" in result.stdout
    assert "executed=" in result.stdout


def test_study1_run_refuses_an_impossible_budget(monkeypatch):
    from pilot.config.config import load_config

    cfg = load_config()
    cfg.experiment.max_cost_usd = 0.0
    monkeypatch.setattr("pilot.cli.runner.load_config", lambda *a, **k: cfg)

    result = runner.invoke(app, ["study1-run", "--run-id", "cli-budget"])
    assert result.exit_code == 3
    assert "budget guard" in result.output


def test_study1_analyze_of_a_missing_run_reports_no_data():
    result = runner.invoke(
        app, ["study1-analyze", "--run-id", "cli-absent", "--no-figures"]
    )
    assert result.exit_code == 0
    assert "trials=0" in result.stdout


def test_tasks_validate_exits_zero_on_the_real_corpus():
    result = runner.invoke(app, ["tasks-validate"])
    if result.exit_code == 2:
        pytest.skip("sandbox unavailable")
    assert result.exit_code == 0, result.output


def test_tasks_validate_exits_two_without_a_sandbox(monkeypatch):
    from pilot.sandbox import docker_runner

    def unavailable(*args, **kwargs):
        raise docker_runner.SandboxUnavailable("no daemon")

    monkeypatch.setattr("pilot.cli.tasks_validate.validate", unavailable)
    result = runner.invoke(app, ["tasks-validate"])
    assert result.exit_code == 2
    assert "sandbox unavailable" in result.output


def test_demo_alias_points_at_demo_mock(monkeypatch):
    called = []
    monkeypatch.setattr("pilot.cli.demo_mock", lambda: called.append(True))
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "deprecated" in result.output
    assert called == [True]


# ---------------------------------------------------------------------------
# demo-mock, end to end
# ---------------------------------------------------------------------------


def test_demo_mock_produces_a_watermarked_report(isolated_results):
    result = runner.invoke(app, ["demo-mock"])
    assert result.exit_code == 0, result.output

    report = isolated_results / "results" / "demo-mock" / "report.md"
    assert report.exists(), "demo-mock did not write a report"

    body = report.read_text(encoding="utf-8")
    assert "synthetic data, pipeline test only" in body
    assert "measurements of any real model" in body


def test_demo_mock_writes_a_manifest_that_declares_itself_synthetic(isolated_results):
    runner.invoke(app, ["demo-mock"])
    manifest_path = isolated_results / "results" / "demo-mock" / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["watermark"] == "synthetic data, pipeline test only"
    assert manifest["n_trials"] > 0, "the demo recorded no trials"
    assert manifest["run"]["executed"] > 0


def test_demo_mock_writes_figures(isolated_results):
    runner.invoke(app, ["demo-mock"])
    figures = list((isolated_results / "results" / "demo-mock").glob("*.png"))
    assert figures, "demo-mock produced no figures"
    assert all(f.stat().st_size > 0 for f in figures)


def test_demo_mock_never_contacts_a_provider(isolated_results):
    """The demo must run on the mock model; a network call would be a defect."""
    import socket

    original = socket.socket

    class NoNetwork(socket.socket):
        def connect(self, *args, **kwargs):
            raise AssertionError("demo-mock attempted a network connection")

        def connect_ex(self, *args, **kwargs):
            raise AssertionError("demo-mock attempted a network connection")

    socket.socket = NoNetwork  # type: ignore[misc]
    try:
        result = runner.invoke(app, ["demo-mock"])
        assert result.exit_code == 0, result.output
    finally:
        socket.socket = original  # type: ignore[misc]


def test_demo_mock_is_resumable(isolated_results):
    """A second demo-mock must skip the trials already on disk."""
    first = runner.invoke(app, ["demo-mock"])
    assert first.exit_code == 0
    second = runner.invoke(app, ["demo-mock"])
    assert second.exit_code == 0
    manifest = json.loads(
        (isolated_results / "results" / "demo-mock" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["run"]["skipped"] > 0, "a second demo-mock re-billed completed trials"


def test_repo_demo_mock_target_has_run(isolated_results):
    """`make demo-mock` is wired to the same command."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "demo-mock:" in makefile
    assert "pilot demo-mock" in makefile


def test_demo_mock_with_no_gradable_trials_reports_no_data_not_zeroes(
    monkeypatch, tmp_path
):
    """A run where nothing could be measured must not render outcome statistics.

    Every trial here is ungraded, so `hidden_pass_rate` is 0.0 for all of them.
    Averaging those in would report a confident 0.000 result for a pipeline that
    never measured anything.
    """
    monkeypatch.setattr("pilot.runner.run.REPO_ROOT", tmp_path)
    monkeypatch.setattr("pilot.cli.REPO_ROOT", tmp_path)

    tasks = tmp_path / "tasks"
    task = tasks / "t01_alpha"
    for sub in ("starter", "reference", "visible_tests", "hidden_tests"):
        (task / sub).mkdir(parents=True)
    (task / "spec.md").write_text("# t\n", encoding="utf-8")
    (task / "meta.yaml").write_text("category: core\ndifficulty: 1\n", encoding="utf-8")
    (task / "starter" / "mod.py").write_text("def f():\n    raise NotImplementedError\n")
    # hidden_tests/ is intentionally empty: nothing will be collected.
    monkeypatch.setattr("pilot.runner.run.TASKS_DIR", tasks)

    result = runner.invoke(app, ["demo-mock"])
    assert result.exit_code == 0, result.output

    out_dir = tmp_path / "results" / "demo-mock"
    body = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "could not be graded" in body
    assert "## no graded data" in body
    assert "| condition |" not in body, "an ungraded run must not render a results table"
    assert "trials graded: 0" in body
    assert list(out_dir.glob("*.png")) == [], "no figures may be drawn from no data"


def test_demo_mock_records_that_trials_were_graded(isolated_results):
    """The manifest must reflect measurement, not just execution."""
    runner.invoke(app, ["demo-mock"])
    manifest = json.loads(
        (isolated_results / "results" / "demo-mock" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["n_graded"] == manifest["n_trials"] > 0
    assert manifest["ungraded_reasons"] == []
