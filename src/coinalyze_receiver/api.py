from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import ReceiverConfig


class CoinalyzeAPIError(RuntimeError):
    pass


@dataclass
class CoinalyzeClient:
    config: ReceiverConfig

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = urllib.parse.urlencode(params or {}, doseq=True)
        base = f"{self.config.base_url}/{path.lstrip('/')}"
        return f"{base}?{query}" if query else base

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._url(path, params)
        req = urllib.request.Request(
            url,
            headers={
                "api_key": self.config.api_key,
                "accept": "application/json",
                "user-agent": "coinalyze-receiver/0.1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.request_timeout_sec) as res:
                body = res.read().decode("utf-8")
                if not body:
                    return None
                return json.loads(body)
        except Exception as exc:
            raise CoinalyzeAPIError(f"GET {path} failed: {exc}") from exc
        finally:
            time.sleep(max(self.config.rate_limit_sleep_sec, 0.0))

    def markets(self) -> Any:
        return self.get("future-markets")

    def ohlcv_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self.get("ohlcv-history", {
            "symbols": symbol,
            "interval": interval,
            "from": from_ts,
            "to": to_ts,
        })

    def open_interest_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self.get("open-interest-history", {
            "symbols": symbol,
            "interval": interval,
            "from": from_ts,
            "to": to_ts,
        })

    def liquidation_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self.get("liquidation-history", {
            "symbols": symbol,
            "interval": interval,
            "from": from_ts,
            "to": to_ts,
        })

    def funding_rate_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self.get("funding-rate-history", {
            "symbols": symbol,
            "interval": interval,
            "from": from_ts,
            "to": to_ts,
        })

    def long_short_ratio_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self.get("long-short-ratio-history", {
            "symbols": symbol,
            "interval": interval,
            "from": from_ts,
            "to": to_ts,
        })
