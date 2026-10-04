from pilot.logging import logger


def test_logger_stores_prompts_responses(tmp_path):
    lg = logger.JsonlLogger("r2", tmp_path)
    lg.log_trial({"full_prompts": "hello", "full_responses": "world"})
    trials = (tmp_path / "results" / "r2" / "trials.jsonl").read_text()
    assert "full_prompts_hash" in trials or "full_responses_hash" in trials
