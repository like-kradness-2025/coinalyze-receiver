from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReceiverConfig:
    symbol: str = "BTCUSDT_PERP.A"
    lookback: str = "6h"
    output_dir: Path = Path("data")
    runtime_dir: Path = Path("runtime")
    api_key_env: str = "COINALYZE_API_KEY"
    base_url: str = "https://api.coinalyze.net/v1"
    request_timeout_sec: int = 30
    rate_limit_sleep_sec: float = 1.6
    ohlcv_interval: str = "1min"
    position_interval: str = "1min"
    enabled_datasets: tuple[str, ...] = (
        "ohlcv",
        "open_interest",
        "liquidation",
        "funding_rate",
        "long_short_ratio",
    )

    @property
    def api_key(self) -> str:
        value = os.environ.get(self.api_key_env, "").strip()
        if not value:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")
        return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(path: str | Path | None = None) -> ReceiverConfig:
    raw = _read_json(Path(path or "config/default.json"))
    coinalyze = raw.get("coinalyze", {})
    fetch = raw.get("fetch", {})
    return ReceiverConfig(
        symbol=str(raw.get("symbol", ReceiverConfig.symbol)),
        lookback=str(raw.get("lookback", ReceiverConfig.lookback)),
        output_dir=Path(raw.get("output_dir", "data")),
        runtime_dir=Path(raw.get("runtime_dir", "runtime")),
        api_key_env=str(coinalyze.get("api_key_env", "COINALYZE_API_KEY")),
        base_url=str(coinalyze.get("base_url", "https://api.coinalyze.net/v1")).rstrip("/"),
        request_timeout_sec=int(coinalyze.get("request_timeout_sec", 30)),
        rate_limit_sleep_sec=float(coinalyze.get("rate_limit_sleep_sec", 1.6)),
        ohlcv_interval=str(fetch.get("ohlcv_interval", "1min")),
        position_interval=str(fetch.get("position_interval", "1min")),
        enabled_datasets=tuple(fetch.get("enabled_datasets", ReceiverConfig.enabled_datasets)),
    )
