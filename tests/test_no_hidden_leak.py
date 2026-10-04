import os
from pathlib import Path


def test_no_hidden_content_leaked():
    root = Path(__file__).parent.parent
    hidden_parts = []
    for tid in sorted(os.listdir(root / "tasks")):
        tpath = root / "tasks" / tid
        if not tpath.is_dir():
            continue
        ht = tpath / "hidden_tests"
        if ht.is_dir():
            for f in ht.glob("*.py"):
                hidden_parts.append(f.read_text())

    others = []
    for tid in sorted(os.listdir(root / "tasks")):
        tpath = root / "tasks" / tid
        for d in ["spec", "starter", "visible_tests"]:
            dp = tpath / d
            if dp.is_dir():
                for f in dp.rglob("*"):
                    if f.suffix in (".md", ".py", ".yaml"):
                        try:
                            others.append(f.read_text())
                        except Exception:
                            pass
    # also check prompt templates if any later; but none yet
    for h in hidden_parts:
        for o in others:
            if h and o and h in o:
                raise AssertionError("hidden content leaked")
