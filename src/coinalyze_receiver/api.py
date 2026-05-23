from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coinalyze import CoinalyzeClient as SDKCoinalyzeClient
from coinalyze import HistoryEndpoint, Interval

from .config import ReceiverConfig
from .timeutil import iso_from_ts


class CoinalyzeAPIError(RuntimeError):
    pass


def _interval(value: str) -> Interval:
    return Interval(value)


def _date_from_ts(ts: int) -> str:
    # The SDK accepts date-like inputs and converts them to timestamps internally.
    # Keep UTC ISO strings to avoid local timezone ambiguity.
    return iso_from_ts(ts)


@dataclass
class CoinalyzeClient:
    """Thin project wrapper around ivarurdalen/coinalyze SDK.

    The external SDK handles:
    - API key header
    - endpoint enum mapping
    - 40 calls/minute rate limiting
    - retry handling

    This wrapper preserves the receiver-facing method names used by receiver.py.
    """

    config: ReceiverConfig

    def __post_init__(self) -> None:
        self._client = SDKCoinalyzeClient(api_key=self.config.api_key)

    def markets(self) -> Any:
        try:
            return self._client.get_future_markets()
        except Exception as exc:
            raise CoinalyzeAPIError(f"future-markets failed: {exc}") from exc

    def _history(self, endpoint: HistoryEndpoint, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        try:
            return self._client.get_history(
                endpoint=endpoint,
                symbols=symbol,
                interval=_interval(interval),
                start=_date_from_ts(from_ts),
                end=_date_from_ts(to_ts),
            )
        except Exception as exc:
            raise CoinalyzeAPIError(f"{endpoint.value}-history failed: {exc}") from exc

    def ohlcv_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self._history(HistoryEndpoint.OHLCV, symbol, interval, from_ts, to_ts)

    def open_interest_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self._history(HistoryEndpoint.OI, symbol, interval, from_ts, to_ts)

    def liquidation_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self._history(HistoryEndpoint.LIQUIDATION, symbol, interval, from_ts, to_ts)

    def funding_rate_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self._history(HistoryEndpoint.FUNDING_RATE, symbol, interval, from_ts, to_ts)

    def long_short_ratio_history(self, symbol: str, interval: str, from_ts: int, to_ts: int) -> Any:
        return self._history(HistoryEndpoint.LSRATIO, symbol, interval, from_ts, to_ts)
