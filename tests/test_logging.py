from pilot.logging import logger


def test_logger_creates_files(tmp_path):
    lg = logger.JsonlLogger("r1", tmp_path)
    lg.log_trial({"task_id": "t01", "condition": "b"})
    assert (tmp_path / "results" / "r1" / "trials.jsonl").exists()
