from pilot.config import config


def test_load_config():
    cfg = config.load_config()
    assert cfg.root.exists()
    assert cfg.experiment.max_cost_usd >= 0
