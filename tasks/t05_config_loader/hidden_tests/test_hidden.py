"""Hidden tests for t05: json config loader with schema validation.

Behaviors from docs/tasks.md item 5: host must be a non-empty string, port must
be an integer in range, and malformed JSON is an error rather than a silent
empty config.
"""

import json

import pytest
from config_loader import load_config


def _write(tmp_path, payload):
    p = tmp_path / "cfg.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return str(p)


def test_valid_config_round_trips(tmp_path):
    cfg = {"host": "example.com", "port": 443}
    assert load_config(_write(tmp_path, cfg)) == cfg


def test_missing_host_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"port": 80}))


def test_empty_host_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"host": "", "port": 80}))


def test_non_string_host_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"host": 1234, "port": 80}))


def test_negative_port_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"host": "h", "port": -1}))


def test_port_above_range_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"host": "h", "port": 70000}))


def test_non_integer_port_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"host": "h", "port": "80"}))


def test_malformed_json_raises(tmp_path):
    # json.JSONDecodeError is a ValueError; either satisfies the contract, but a
    # blind `except Exception` would not.
    with pytest.raises((ValueError, json.JSONDecodeError)):
        load_config(_write(tmp_path, "{not json"))


def test_missing_file_raises(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        load_config(str(tmp_path / "does_not_exist.json"))


def test_boundary_ports_are_accepted(tmp_path):
    for port in (0, 65535):
        cfg = {"host": "h", "port": port}
        assert load_config(_write(tmp_path, cfg)) == cfg
