from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BotConfig:
    portal_url: str
    browser: str
    headless: bool
    timeout_seconds: int
    selectors: dict[str, Any]
    field_selectors: dict[str, dict[str, list[str]]]
    column_aliases: dict[str, list[str]]

    @classmethod
    def load(cls, path: Path) -> "BotConfig":
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return cls(
            portal_url=raw.get("portal_url", "https://eprtyres.cpcb.gov.in/login"),
            browser=raw.get("browser", "chrome"),
            headless=bool(raw.get("headless", False)),
            timeout_seconds=int(raw.get("timeout_seconds", 30)),
            selectors=raw.get("selectors", {}),
            field_selectors=raw.get("field_selectors", {}),
            column_aliases=raw.get("column_aliases", {}),
        )
