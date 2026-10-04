from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlLogger:
    def __init__(self, run_id: str, root: Path) -> None:
        self.run_id = run_id
        self.root = Path(root) / "results" / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.trials_path = self.root / "trials.jsonl"

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def log_trial(self, record: dict[str, Any]) -> None:
        # store full prompts/responses as raw files to avoid huge lines
        prompts = record.get("full_prompts")
        if isinstance(prompts, str):
            h = self._hash_text(prompts)
            p = self.raw_dir / f"prompts_{len(os.listdir(self.raw_dir))}_{h[:8]}.txt"
            p.write_text(prompts, encoding="utf-8")
            record["full_prompts_hash"] = h
            record["full_prompts_path"] = str(p.relative_to(self.root.parent.parent))  # rough
            record.pop("full_prompts", None)

        resp = record.get("full_responses")
        if isinstance(resp, str):
            h = self._hash_text(resp)
            p = self.raw_dir / f"responses_{len(os.listdir(self.raw_dir))}_{h[:8]}.txt"
            p.write_text(resp, encoding="utf-8")
            record["full_responses_hash"] = h
            record.pop("full_responses", None)

        record.setdefault("timestamp", datetime.now(UTC).isoformat())
        record.setdefault("run_id", self.run_id)
        with self.trials_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
