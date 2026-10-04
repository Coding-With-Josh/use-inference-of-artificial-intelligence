import json
import tempfile
from pathlib import Path
import pytest
from config_loader import load_config


def test_invalid_port():
    cfg = {"host": "localhost", "port": -1}
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        json.dump(cfg, f)
        p = f.name
    try:
        with pytest.raises((ValueError, TypeError)):
            load_config(p)
    finally:
        Path(p).unlink()


def test_missing_host():
    cfg = {"port": 8080}
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        json.dump(cfg, f)
        p = f.name
    try:
        with pytest.raises((ValueError, TypeError)):
            load_config(p)
    finally:
        Path(p).unlink()
