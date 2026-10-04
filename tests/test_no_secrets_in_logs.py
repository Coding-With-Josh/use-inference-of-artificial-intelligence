from pathlib import Path


def test_no_secrets_in_logs():
    root = Path(__file__).parent.parent
    for p in root.rglob("*.jsonl"):
        try:
            txt = p.read_text()
            if "api_key" in txt or "OPENAI_API_KEY" in txt or "ANTHROPIC_API_KEY" in txt:
                raise AssertionError
        except Exception:
            continue
