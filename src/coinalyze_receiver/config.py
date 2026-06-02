"""Configuration for coinalyze-receiver."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Application configuration from environment variables."""

    api_key: str = ""
    db_path: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.getenv("COINALYZE_API_KEY", "")
        db_path = os.getenv(
            "COINALYZE_DB_PATH",
            str(Path.cwd() / "data" / "coinalyze_v2.db"),
        )
        return cls(
            api_key=api_key,
            db_path=db_path,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("COINALYZE_API_KEY is required")
        return errors
