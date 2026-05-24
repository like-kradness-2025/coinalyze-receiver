from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from coinalyze_receiver import cli


@pytest.fixture()
def smoke_config(tmp_path: Path):
    output_dir = tmp_path / "data"
    runtime_dir = tmp_path / "runtime"
    output_dir.mkdir()
    runtime_dir.mkdir()
    return SimpleNamespace(
        symbol="BTCUSDT_PERP.A",
        lookback="6h",
        output_dir=output_dir,
        runtime_dir=runtime_dir,
    )


@pytest.fixture()
def sample_ohlcv_rows() -> list[dict[str, object]]:
    return [
        {"dataset": "ohlcv", "symbol": "BTCUSDT_PERP.A", "ts": 1_700_000_000, "low": 100.0, "high": 110.0, "bv": 6.0, "volume": 10.0},
        {"dataset": "ohlcv", "symbol": "BTCUSDT_PERP.A", "ts": 1_700_000_900, "low": 120.0, "high": 130.0, "bv": 4.0, "volume": 8.0},
    ]


def _write_ohlcv_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_smoke_run_once(monkeypatch: pytest.MonkeyPatch, smoke_config):
    called: dict[str, object] = {}

    class FakeReceiver:
        def __init__(self, config):
            self.config = config

        def fetch_once(self, symbol=None, lookback=None, from_ts=None, to_ts=None):
            called.update({"symbol": symbol, "lookback": lookback, "from_ts": from_ts, "to_ts": to_ts})
            return [SimpleNamespace(dataset="ohlcv", raw_count=1, normalized_count=1, ok=True, error=None)]

    monkeypatch.setattr(cli, "load_config", lambda _path: smoke_config)
    monkeypatch.setattr(cli, "CoinalyzeReceiver", FakeReceiver)

    assert cli.main(["run-once", "--symbol", "BTCUSDT_PERP.A", "--lookback", "1h"]) == 0
    assert called["symbol"] == "BTCUSDT_PERP.A"
    assert called["lookback"] == "1h"


def test_smoke_render(monkeypatch: pytest.MonkeyPatch, smoke_config, sample_ohlcv_rows):
    ohlcv_path = smoke_config.output_dir / "normalized" / "ohlcv.jsonl"
    ohlcv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_ohlcv_jsonl(ohlcv_path, sample_ohlcv_rows)

    monkeypatch.setattr(cli, "load_config", lambda _path: smoke_config)
    monkeypatch.setattr(cli.time, "time", lambda: 1_700_001_800)

    assert cli.main(["render", "--price-bucket-usd", "10"]) == 0
    assert (smoke_config.output_dir / "cvd_heatmap.png").exists()


def test_smoke_notify(monkeypatch: pytest.MonkeyPatch, smoke_config):
    image_path = smoke_config.output_dir / "cvd_heatmap.png"
    image_path.write_bytes(b"fake-png")
    sent: dict[str, object] = {}

    def fake_send_discord_notification(webhook_url, message, path):
        sent.update({"webhook_url": webhook_url, "message": message, "path": path})
        return True

    monkeypatch.setattr(cli, "load_config", lambda _path: smoke_config)
    monkeypatch.setattr(cli, "send_discord_notification", fake_send_discord_notification)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")

    assert cli.main(["notify"]) == 0
    assert sent["webhook_url"] == "https://discord.invalid/webhook"
    assert sent["path"] == image_path


def test_smoke_full_pipeline(monkeypatch: pytest.MonkeyPatch, smoke_config, sample_ohlcv_rows):
    class FakeReceiver:
        def __init__(self, config):
            self.config = config

        def fetch_once(self, symbol=None, lookback=None, from_ts=None, to_ts=None):
            raw_dir = smoke_config.output_dir / "raw"
            normalized_dir = smoke_config.output_dir / "normalized"
            raw_dir.mkdir(parents=True, exist_ok=True)
            normalized_dir.mkdir(parents=True, exist_ok=True)
            _write_ohlcv_jsonl(raw_dir / "ohlcv.jsonl", [{"dataset": "ohlcv", "payload": sample_ohlcv_rows}])
            _write_ohlcv_jsonl(normalized_dir / "ohlcv.jsonl", sample_ohlcv_rows)
            return [SimpleNamespace(dataset="ohlcv", raw_count=1, normalized_count=2, ok=True, error=None)]

    monkeypatch.setattr(cli, "load_config", lambda _path: smoke_config)
    monkeypatch.setattr(cli, "CoinalyzeReceiver", FakeReceiver)
    monkeypatch.setattr(cli.time, "time", lambda: 1_700_001_800)

    assert cli.main(["run-once", "--symbol", "BTCUSDT_PERP.A", "--lookback", "1h"]) == 0
    assert cli.main(["render", "--price-bucket-usd", "10"]) == 0
    assert (smoke_config.output_dir / "cvd_heatmap.png").exists()
