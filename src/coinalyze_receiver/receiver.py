from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api import CoinalyzeClient
from .config import ReceiverConfig
from .normalize import normalize_generic_history, normalize_ohlcv
from .storage import append_jsonl, write_json
from .timeutil import iso_from_ts, parse_duration_seconds, utc_now_ts


@dataclass
class FetchResult:
    dataset: str
    raw_count: int
    normalized_count: int
    ok: bool
    error: str | None = None


class CoinalyzeReceiver:
    def __init__(self, config: ReceiverConfig):
        self.config = config
        self.client = CoinalyzeClient(config)

    def _paths(self, dataset: str):
        raw = self.config.output_dir / "raw" / f"{dataset}.jsonl"
        normalized = self.config.output_dir / "normalized" / f"{dataset}.jsonl"
        return raw, normalized

    def _save(self, dataset: str, raw_payload: Any, normalized_rows: list[dict[str, Any]], meta: dict[str, Any]) -> FetchResult:
        raw_path, normalized_path = self._paths(dataset)
        append_jsonl(raw_path, {"dataset": dataset, "meta": meta, "payload": raw_payload})
        for row in normalized_rows:
            append_jsonl(normalized_path, row)
        raw_count = len(raw_payload) if isinstance(raw_payload, list) else 1
        return FetchResult(dataset=dataset, raw_count=raw_count, normalized_count=len(normalized_rows), ok=True)

    def fetch_once(self, symbol: str | None = None, lookback: str | None = None) -> list[FetchResult]:
        symbol = symbol or self.config.symbol
        lookback = lookback or self.config.lookback
        to_ts = utc_now_ts()
        from_ts = to_ts - parse_duration_seconds(lookback)
        meta = {
            "symbol": symbol,
            "from": from_ts,
            "to": to_ts,
            "from_iso": iso_from_ts(from_ts),
            "to_iso": iso_from_ts(to_ts),
        }
        results: list[FetchResult] = []

        jobs = [
            (
                "ohlcv",
                lambda: self.client.ohlcv_history(symbol, self.config.ohlcv_interval, from_ts, to_ts),
                normalize_ohlcv,
            ),
            (
                "open_interest",
                lambda: self.client.open_interest_history(symbol, self.config.position_interval, from_ts, to_ts),
                lambda p: normalize_generic_history(p, "open_interest"),
            ),
            (
                "liquidation",
                lambda: self.client.liquidation_history(symbol, self.config.position_interval, from_ts, to_ts),
                lambda p: normalize_generic_history(p, "liquidation"),
            ),
            (
                "funding_rate",
                lambda: self.client.funding_rate_history(symbol, self.config.position_interval, from_ts, to_ts),
                lambda p: normalize_generic_history(p, "funding_rate"),
            ),
            (
                "long_short_ratio",
                lambda: self.client.long_short_ratio_history(symbol, self.config.position_interval, from_ts, to_ts),
                lambda p: normalize_generic_history(p, "long_short_ratio"),
            ),
        ]

        enabled = set(self.config.enabled_datasets)
        for dataset, fetcher, normalizer in jobs:
            if dataset not in enabled:
                continue
            try:
                raw = fetcher()
                rows = normalizer(raw)
                results.append(self._save(dataset, raw, rows, meta))
            except Exception as exc:
                results.append(FetchResult(dataset=dataset, raw_count=0, normalized_count=0, ok=False, error=str(exc)))

        self.write_health(results, symbol=symbol, from_ts=from_ts, to_ts=to_ts)
        return results

    def write_health(self, results: list[FetchResult], symbol: str, from_ts: int, to_ts: int) -> None:
        payload = {
            "ts": iso_from_ts(utc_now_ts()),
            "symbol": symbol,
            "from": iso_from_ts(from_ts),
            "to": iso_from_ts(to_ts),
            "ok": all(r.ok for r in results),
            "results": [r.__dict__ for r in results],
        }
        write_json(self.config.runtime_dir / "health.json", payload)
