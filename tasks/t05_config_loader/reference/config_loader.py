import json


def load_config(path):
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data.get("host"), str) or not data["host"]:
        raise ValueError("invalid host")
    port = data.get("port")
    if not isinstance(port, int) or port < 0 or port > 65535:
        raise ValueError("invalid port")
    return data
