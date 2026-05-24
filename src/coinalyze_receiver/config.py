"""Configuration for coinalyze-receiver."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Application configuration from environment variables."""

    api_key: str = ""
    db_path: str = ""
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT_PERP.A"])
    intervals: list[str] = field(default_factory=lambda: ["1hour"])
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.getenv("COINALYZE_API_KEY", "")
        db_path = os.getenv(
            "COINALYZE_DB_PATH",
            str(Path.cwd() / "data" / "coinalyze.db"),
        )
        raw_symbols = os.getenv("COINALYZE_SYMBOLS", "BTCUSDT_PERP.A")
        raw_intervals = os.getenv("COINALYZE_INTERVALS", "1hour")
        return cls(
            api_key=api_key,
            db_path=db_path,
            symbols=[s.strip() for s in raw_symbols.split(",") if s.strip()],
            intervals=[i.strip() for i in raw_intervals.split(",") if i.strip()],
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("COINALYZE_API_KEY is required")
        if not self.symbols:
            errors.append("COINALYZE_SYMBOLS is empty")
        return errors
