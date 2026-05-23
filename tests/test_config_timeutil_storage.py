from __future__ import annotations

import json
from pathlib import Path

import pytest

from coinalyze_receiver.config import ReceiverConfig, load_config
from coinalyze_receiver.storage import append_jsonl, rotate_raw_jsonl, upsert_jsonl, write_json


def test_write_json_uses_atomic_replace(monkeypatch, tmp_path: Path):
    path = tmp_path / "state.json"
    calls: list[tuple[Path, Path]] = []

    def fake_replace(src, dst):
        calls.append((Path(src), Path(dst)))
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr("coinalyze_receiver.storage.os.replace", fake_replace)

    write_json(path, {"last_ts": 123, "symbol": "BTC"})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"last_ts": 123, "symbol": "BTC"}
    assert len(calls) == 1
    assert calls[0][1] == path

from coinalyze_receiver.timeutil import iso_from_ts, parse_duration_seconds, utc_now_ts


def test_parse_duration_seconds_supports_minute_hour_day_and_plain_seconds():
    assert parse_duration_seconds("15m") == 900
    assert parse_duration_seconds("1.5h") == 5400
    assert parse_duration_seconds("2d") == 172800
    assert parse_duration_seconds("60") == 60


def test_iso_from_ts_uses_utc_isoformat():
    assert iso_from_ts(1700000000) == "2023-11-14T22:13:20+00:00"


def test_load_config_applies_nested_defaults_and_strips_trailing_slash(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "symbol": "ETHUSDT_PERP.A",
                "lookback": "12h",
                "output_dir": "out",
                "runtime_dir": "run",
                "coinalyze": {"base_url": "https://api.example/v1/"},
                "fetch": {"enabled_datasets": ["ohlcv", "funding_rate"]},
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.symbol == "ETHUSDT_PERP.A"
    assert cfg.lookback == "12h"
    assert cfg.output_dir == Path("out")
    assert cfg.runtime_dir == Path("run")
    assert cfg.base_url == "https://api.example/v1"
    assert cfg.enabled_datasets == ("ohlcv", "funding_rate")


def test_upsert_jsonl_overwrites_same_key_and_keeps_single_row(tmp_path: Path):
    path = tmp_path / "nested" / "rows.jsonl"

    count1 = upsert_jsonl(path, {"dataset": "ohlcv", "symbol": "BTC", "ts": 1, "value": 10}, ("dataset", "symbol", "ts"))
    count2 = upsert_jsonl(path, {"dataset": "ohlcv", "symbol": "BTC", "ts": 1, "value": 99}, ("dataset", "symbol", "ts"))

    assert count1 == 1
    assert count2 == 1
    assert path.read_text(encoding="utf-8") == '{"dataset":"ohlcv","symbol":"BTC","ts":1,"value":99}\n'


def test_rotate_raw_jsonl_deletes_rows_older_than_seven_days(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    path = raw_dir / "rows.jsonl"
    import time

    now = int(time.time())
    append_jsonl(path, {"dataset": "ohlcv", "_saved_at": now - (8 * 24 * 60 * 60), "value": "old"})
    append_jsonl(path, {"dataset": "ohlcv", "_saved_at": now - (6 * 24 * 60 * 60), "value": "kept"})
    append_jsonl(path, {"dataset": "ohlcv", "value": "missing_saved_at_kept"})

    deleted = rotate_raw_jsonl(raw_dir, days=7)

    assert deleted == 1
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert "old" not in path.read_text(encoding="utf-8")
    assert "kept" in path.read_text(encoding="utf-8")
    assert "missing_saved_at_kept" in path.read_text(encoding="utf-8")
