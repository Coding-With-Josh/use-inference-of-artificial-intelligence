def test_cli_help():
    import subprocess
    import sys

    res = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            "from pilot.cli import app; app(['--help'])",
        ],
        cwd="/Users/joshua/projects/use-inference-of-artificial-intelligence-experiments",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert res.returncode == 0
