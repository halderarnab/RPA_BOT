from __future__ import annotations

import json
from pathlib import Path


class BotState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2)

    def is_done(self, dataset: str, row_id: str) -> bool:
        return self.data.get(dataset, {}).get(row_id) == "done"

    def mark_done(self, dataset: str, row_id: str) -> None:
        self.data.setdefault(dataset, {})[row_id] = "done"
        self.save()

    def mark_failed(self, dataset: str, row_id: str) -> None:
        self.data.setdefault(dataset, {})[row_id] = "failed"
        self.save()
