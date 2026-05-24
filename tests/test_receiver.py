from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import json

import coinalyze_receiver.receiver as receiver_mod
from coinalyze_receiver.receiver import CoinalyzeReceiver


@dataclass
class DummyConfig:
    symbol: str = "BTCUSDT_PERP.A"
    lookback: str = "6h"
    output_dir: Path = Path("/tmp/out")
    runtime_dir: Path = Path("/tmp/run")
    ohlcv_interval: str = "1min"
    position_interval: str = "1min"
    enabled_datasets: tuple[str, ...] = ("ohlcv", "funding_rate")


class DummyClient:
    def __init__(self):
        self.calls = []
        self.ohlcv_value = 2
        self.funding_rows = 2

    def ohlcv_history(self, symbol, interval, from_ts, to_ts):
        self.calls.append(("ohlcv", symbol, interval, from_ts, to_ts))
        return [{"symbol": symbol, "history": [{"t": from_ts, "o": 1, "h": 2, "l": 1, "c": self.ohlcv_value, "v": 10, "bv": 4, "tx": 7, "btx": 3}]}]

    def funding_rate_history(self, symbol, interval, from_ts, to_ts):
        self.calls.append(("funding_rate", symbol, interval, from_ts, to_ts))
        history = [{"t": from_ts + 60 * i, "rate": 0.01 + (i / 100)} for i in range(self.funding_rows)]
        return [{"symbol": symbol, "history": history}]


def _noop_rotate(*args, **kwargs):
    return 0


def test_fetch_once_persists_state_and_narrows_followup_window(monkeypatch, tmp_path: Path):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run", enabled_datasets=("funding_rate",))
    dummy = DummyClient()
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)
    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]

    now_values = [1_700_000_000, 1_700_000_060]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: now_values.pop(0))

    first = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="2m")
    second = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="2m")

    assert first[0].normalized_count == 2
    assert second[0].normalized_count == 4

    first_call = dummy.calls[0]
    second_call = dummy.calls[1]
    assert second_call[3] >= first_call[4] - 60
    assert second_call[3] > first_call[3] - 1

    state = json.loads((cfg.runtime_dir / "state.json").read_text(encoding="utf-8"))
    assert state["symbol"] == "ETHUSDT_PERP.A"
    assert state["datasets"]["funding_rate"]["last_ts"] >= second_call[3]

    health = json.loads((cfg.runtime_dir / "health.json").read_text(encoding="utf-8"))
    assert health["results"][0]["normalized_count"] == 4


def test_fetch_once_deduplicates_same_timestamp_rows_and_updates_health(monkeypatch, tmp_path: Path):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run", enabled_datasets=("ohlcv",))
    dummy = DummyClient()
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)
    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: 1_700_000_000)

    first = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="1m")
    dummy.ohlcv_value = 99
    second = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="1m")

    assert first[0].raw_count == 1
    assert first[0].normalized_count == 1
    assert second[0].raw_count == 1
    assert second[0].normalized_count == 2

    raw_lines = (cfg.output_dir / "raw" / "ohlcv.jsonl").read_text(encoding="utf-8").splitlines()
    normalized_lines = (cfg.output_dir / "normalized" / "ohlcv.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    assert len(normalized_lines) == 2
    assert any('"close":99.0' in line for line in normalized_lines)
    health = json.loads((cfg.runtime_dir / "health.json").read_text(encoding="utf-8"))
    assert health["results"][0]["raw_count"] == 1
    assert health["results"][0]["normalized_count"] == 2
    assert health["ok"] is True


def test_fetch_once_saves_enabled_datasets_and_health(monkeypatch, tmp_path: Path):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run")
    dummy = DummyClient()
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)
    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: 1_700_000_000)

    results = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="1m")

    assert [r.dataset for r in results] == ["ohlcv", "funding_rate"]
    assert all(r.ok for r in results)
    assert results[0].normalized_count == 1
    assert results[1].normalized_count == 2

    raw_ohlcv = (cfg.output_dir / "raw" / "ohlcv.jsonl").read_text(encoding="utf-8")
    assert '"dataset":"ohlcv"' in raw_ohlcv
    assert (cfg.runtime_dir / "health.json").exists()


def test_fetch_once_records_failure_for_bad_dataset(monkeypatch, tmp_path: Path):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run", enabled_datasets=("ohlcv",))

    dummy_bad = DummyClient()

    def boom(*args, **kwargs):
        raise RuntimeError("api down")

    dummy_bad.ohlcv_history = boom  # type: ignore[assignment]
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy_bad)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)

    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: 1_700_000_000)

    results = receiver.fetch_once()

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "api down"
    health = (cfg.runtime_dir / "health.json").read_text(encoding="utf-8")
    assert '"ok": false' in health.lower()


def test_fetch_once_saves_raw_rows_with_saved_at(monkeypatch, tmp_path: Path):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run", enabled_datasets=("ohlcv",))
    dummy = DummyClient()
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)
    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: 1_700_000_000)

    receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="1m")

    raw_row = json.loads((cfg.output_dir / "raw" / "ohlcv.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert raw_row["_saved_at"] == 1_700_000_000
    assert raw_row["dataset"] == "ohlcv"


def test_fetch_once_warns_and_resets_when_state_json_is_corrupted(monkeypatch, tmp_path: Path, caplog):
    cfg = DummyConfig(output_dir=tmp_path / "data", runtime_dir=tmp_path / "run", enabled_datasets=("funding_rate",))
    dummy = DummyClient()
    monkeypatch.setattr(receiver_mod, "CoinalyzeClient", lambda config: dummy)
    monkeypatch.setattr(receiver_mod, "rotate_raw_jsonl", _noop_rotate)
    receiver = CoinalyzeReceiver(cfg)  # type: ignore[arg-type]
    monkeypatch.setattr("coinalyze_receiver.receiver.utc_now_ts", lambda: 1_700_000_000)

    state_path = cfg.runtime_dir / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        results = receiver.fetch_once(symbol="ETHUSDT_PERP.A", lookback="2m")

    assert results[0].ok is True
    assert dummy.calls[0][3] == 1_699_999_880
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["symbol"] == "ETHUSDT_PERP.A"
    assert state["datasets"]["funding_rate"]["last_ts"] >= dummy.calls[0][3]
    assert any("state.json" in record.message for record in caplog.records)
    assert any("リセット" in record.message for record in caplog.records)
