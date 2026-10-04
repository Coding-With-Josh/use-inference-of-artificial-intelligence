import json
import tempfile
from pathlib import Path
from config_loader import load_config


def test_valid():
    cfg = {"host": "localhost", "port": 8080}
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        json.dump(cfg, f)
        p = f.name
    try:
        assert load_config(p) == cfg
    finally:
        Path(p).unlink()
