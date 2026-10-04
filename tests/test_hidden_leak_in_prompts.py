from pathlib import Path


def test_hidden_leak_in_prompts():
    root = Path(__file__).parent.parent
    hidden = []
    for p in (root / "tasks").rglob("hidden_tests/*.py"):
        hidden.append(p.read_text())
    others = []
    for p in (root).rglob("prompt*"):
        try:
            others.append(p.read_text())
        except Exception:
            continue
    for h in hidden:
        for o in others:
            if h and o and h in o:
                raise AssertionError
