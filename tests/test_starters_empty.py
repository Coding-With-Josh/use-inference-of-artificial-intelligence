import os
from pathlib import Path


def test_starters_are_minimal():
    root = Path(__file__).parent.parent
    for tid in sorted(os.listdir(root / "tasks")):
        tpath = root / "tasks" / tid
        sp = tpath / "starter"
        if not sp.is_dir():
            continue
        for f in sp.glob("*.py"):
            content = f.read_text()
            if "md5(" in content or "' OR '" in content or '../' in content:
                raise AssertionError(f"{tid} starter looks unsafe")
