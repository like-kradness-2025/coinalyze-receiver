from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .api import CoinalyzeClient
from .config import ReceiverConfig
from .normalize import normalize_generic_history, normalize_ohlcv
from .storage import read_jsonl, rotate_raw_jsonl, upsert_jsonl, write_json
from .timeutil import iso_from_ts, parse_duration_seconds, utc_now_ts


logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    dataset: str
    raw_count: int
    fetched_count: int
    persisted_count: int
    ok: bool
    error: str | None = None

    @property
    def normalized_count(self) -> int:
        return self.fetched_count


class CoinalyzeReceiver:
    def __init__(self, config: ReceiverConfig):
        self.config = config
        self.client = CoinalyzeClient(config)

    def _paths(self, dataset: str):
        raw = self.config.output_dir / "raw" / f"{dataset}.jsonl"
        normalized = self.config.output_dir / "normalized" / f"{dataset}.jsonl"
        return raw, normalized

    def _state_path(self):
        return self.config.runtime_dir / "state.json"

    def _read_state(self) -> dict[str, Any]:
        path = self._state_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("state.json の読み取りに失敗したため、状態をリセットします: %s", path, exc_info=True)
            return {}

    def _write_state(self, payload: dict[str, Any]) -> None:
        write_json(self._state_path(), payload)

    def _interval_overlap_seconds(self) -> int:
        return max(
            parse_duration_seconds(self.config.ohlcv_interval),
            parse_duration_seconds(self.config.position_interval),
        )

    def _fetch_window(self, symbol: str, dataset: str, lookback: str, state: dict[str, Any], now_ts: int) -> tuple[int, int, dict[str, Any]]:
        lookback_from = now_ts - parse_duration_seconds(lookback)
        datasets_state = state.get("datasets", {}) if isinstance(state, dict) else {}
        dataset_state = datasets_state.get(dataset, {}) if isinstance(datasets_state, dict) else {}
        last_ts = dataset_state.get("last_ts")
        interval = self._interval_overlap_seconds()
        if isinstance(last_ts, int):
            from_ts = max(lookback_from, last_ts + interval)
        else:
            from_ts = lookback_from
        meta = {
            "symbol": symbol,
            "dataset": dataset,
            "from": from_ts,
            "to": now_ts,
            "from_iso": iso_from_ts(from_ts),
            "to_iso": iso_from_ts(now_ts),
        }
        return from_ts, now_ts, meta

    def _save(self, dataset: str, raw_payload: Any, normalized_rows: list[dict[str, Any]], meta: dict[str, Any], saved_at: int) -> FetchResult:
        raw_path, normalized_path = self._paths(dataset)
        upsert_jsonl(
            raw_path,
            {
                "dataset": dataset,
                "symbol": meta["symbol"],
                "from": meta["from"],
                "to": meta["to"],
                "meta": meta,
                "payload": raw_payload,
                "_saved_at": saved_at,
            },
            ("dataset", "symbol", "from", "to"),
        )
        raw_count = 1
        for row in normalized_rows:
            upsert_jsonl(normalized_path, row, ("dataset", "symbol", "ts"))
        persisted_count = len(read_jsonl(normalized_path)) if normalized_path.exists() else 0
        fetched_count = len(normalized_rows)
        return FetchResult(dataset=dataset, raw_count=raw_count, fetched_count=fetched_count, persisted_count=persisted_count, ok=True)

    def fetch_once(self, symbol: str | None = None, lookback: str | None = None, from_ts: int | None = None, to_ts: int | None = None) -> list[FetchResult]:
        symbol = symbol or self.config.symbol
        lookback = lookback or self.config.lookback
        state = self._read_state()
        now_ts = utc_now_ts()
        results: list[FetchResult] = []
        next_state = dict(state)
        health_results: list[FetchResult] = []

        jobs = [
            ("ohlcv", lambda start, end: self.client.ohlcv_history(symbol, self.config.ohlcv_interval, start, end), normalize_ohlcv),
            ("open_interest", lambda start, end: self.client.open_interest_history(symbol, self.config.position_interval, start, end), lambda p: normalize_generic_history(p, "open_interest")),
            ("liquidation", lambda start, end: self.client.liquidation_history(symbol, self.config.position_interval, start, end), lambda p: normalize_generic_history(p, "liquidation")),
            ("funding_rate", lambda start, end: self.client.funding_rate_history(symbol, self.config.position_interval, start, end), lambda p: normalize_generic_history(p, "funding_rate")),
            ("long_short_ratio", lambda start, end: self.client.long_short_ratio_history(symbol, self.config.position_interval, start, end), lambda p: normalize_generic_history(p, "long_short_ratio")),
        ]

        enabled = set(self.config.enabled_datasets)
        for dataset, fetcher, normalizer in jobs:
            if dataset not in enabled:
                continue
            try:
                ds_from_ts = from_ts
                ds_to_ts = to_ts if to_ts is not None else now_ts
                if ds_from_ts is None:
                    ds_from_ts, ds_to_ts, meta = self._fetch_window(symbol, dataset, lookback, state, now_ts)
                else:
                    meta = {
                        "symbol": symbol,
                        "dataset": dataset,
                        "from": ds_from_ts,
                        "to": ds_to_ts,
                        "from_iso": iso_from_ts(ds_from_ts),
                        "to_iso": iso_from_ts(ds_to_ts),
                    }
                raw = fetcher(ds_from_ts, ds_to_ts)
                rows = normalizer(raw)
                result = self._save(dataset, raw, rows, meta, now_ts)
                results.append(result)
                normalized_path = self._paths(dataset)[1]
                persisted_count = len(read_jsonl(normalized_path)) if normalized_path.exists() else 0
                health_results.append(FetchResult(dataset=dataset, raw_count=result.raw_count, fetched_count=result.fetched_count, persisted_count=persisted_count, ok=result.ok, error=result.error))
                max_ts = max((int(row["ts"]) for row in rows if "ts" in row), default=None)
                if max_ts is not None:
                    datasets_state = dict(next_state.get("datasets", {}))
                    datasets_state[dataset] = {"last_ts": max_ts, "updated_at": now_ts}
                    next_state["datasets"] = datasets_state
            except Exception as exc:
                error_result = FetchResult(dataset=dataset, raw_count=0, fetched_count=0, persisted_count=0, ok=False, error=str(exc))
                results.append(error_result)
                health_results.append(error_result)

        next_state["symbol"] = symbol
        next_state["updated_at"] = now_ts
        self._write_state(next_state)
        self.write_health(health_results, symbol=symbol, from_ts=0 if from_ts is None else from_ts, to_ts=now_ts if to_ts is None else to_ts, ts=now_ts)
        rotate_raw_jsonl(self.config.output_dir / "raw", days=7)
        return results

    def write_health(self, results: list[FetchResult], symbol: str, from_ts: int, to_ts: int, ts: int | None = None) -> None:
        payload = {
            "ts": iso_from_ts(ts if ts is not None else utc_now_ts()),
            "symbol": symbol,
            "from": iso_from_ts(from_ts),
            "to": iso_from_ts(to_ts),
            "ok": all(r.ok for r in results),
            "results": [r.__dict__ for r in results],
        }
        write_json(self.config.runtime_dir / "health.json", payload)
