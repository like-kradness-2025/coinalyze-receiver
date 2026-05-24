from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from coinalyze_receiver import cli
from coinalyze_receiver.config import ReceiverConfig
from coinalyze_receiver.renderer import filter_footprint_by_ts


@pytest.fixture()
def sample_ohlcv_rows() -> list[dict[str, object]]:
    return [
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700000000, "low": 100.0, "high": 110.0, "bv": 6.0, "volume": 10.0},
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700000000, "low": 100.0, "high": 110.0, "bv": 6.0, "volume": 10.0},
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700000900, "low": 120.0, "high": 130.0, "bv": 4.0, "volume": 8.0},
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700001800, "low": 140.0, "high": 150.0, "bv": 3.0, "volume": 7.0},
    ]


@pytest.fixture()
def config_with_data(tmp_path: Path) -> ReceiverConfig:
    output_dir = tmp_path / "data"
    normalized_dir = output_dir / "normalized"
    normalized_dir.mkdir(parents=True)
    return ReceiverConfig(symbol="TEST", output_dir=output_dir)


def _write_ohlcv_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_cmd_render_passes_default_window_and_dedupes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_with_data: ReceiverConfig, sample_ohlcv_rows: list[dict[str, object]]):
    ohlcv_path = config_with_data.output_dir / "normalized" / "ohlcv.jsonl"
    _write_ohlcv_jsonl(ohlcv_path, sample_ohlcv_rows)

    captured: dict[str, Any] = {}
    monkeypatch.setattr(cli.time, "time", lambda: 1700002000)

    def fake_render(footprint, output_path, symbol, from_ts=None, to_ts=None):
        captured["footprint"] = footprint
        captured["output_path"] = output_path
        captured["symbol"] = symbol
        captured["from_ts"] = from_ts
        captured["to_ts"] = to_ts

    monkeypatch.setattr(cli, "load_config", lambda _path: config_with_data)
    monkeypatch.setattr(cli, "render_cvd_heatmap", fake_render)

    assert cli.main(["render"]) == 0

    assert captured["symbol"] == "TEST"
    assert captured["from_ts"] == 1700002000 - 6 * 60 * 60
    assert captured["to_ts"] is None
    assert captured["output_path"] == config_with_data.output_dir / "cvd_heatmap.png"
    footprint = cast(dict[int, list], captured["footprint"])
    assert sorted(footprint.keys()) == [1699999200, 1700000100, 1700001000]
    assert len(footprint[1699999200]) == 2


@pytest.mark.parametrize(
    "since,to,expected_keys",
    [
        ("2023-11-14T22:13:20+00:00", "2023-11-14T22:28:20+00:00", [1700000100]),
        ("1700000900", "1700001800", [1700001000]),
    ],
)
def test_cmd_render_forwards_time_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_with_data: ReceiverConfig, sample_ohlcv_rows: list[dict[str, object]], since, to, expected_keys):
    ohlcv_path = config_with_data.output_dir / "normalized" / "ohlcv.jsonl"
    _write_ohlcv_jsonl(ohlcv_path, sample_ohlcv_rows)

    captured: dict[str, Any] = {}

    def fake_render(footprint, output_path, symbol, from_ts=None, to_ts=None):
        captured["footprint"] = footprint
        captured["from_ts"] = from_ts
        captured["to_ts"] = to_ts
        captured["filtered_keys"] = sorted(filter_footprint_by_ts(footprint, from_ts=from_ts, to_ts=to_ts).keys())

    monkeypatch.setattr(cli, "load_config", lambda _path: config_with_data)
    monkeypatch.setattr(cli, "render_cvd_heatmap", fake_render)

    assert cli.main(["render", "--since", str(since), "--to", str(to), "--price-bucket-usd", "5.0"]) == 0

    assert captured["from_ts"] == 1700000000 if since.startswith("2023") else 1700000900
    assert captured["to_ts"] == (1700000900 if since.startswith("2023") else 1700001800)
    assert captured["filtered_keys"] == expected_keys


def test_cmd_render_filters_duplicates_before_rendering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_with_data: ReceiverConfig):
    rows = [
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700000000, "low": 100.0, "high": 110.0, "bv": 6.0, "volume": 10.0},
        {"dataset": "ohlcv", "symbol": "TEST", "ts": 1700000000, "low": 100.0, "high": 110.0, "bv": 100.0, "volume": 999.0},
    ]
    ohlcv_path = config_with_data.output_dir / "normalized" / "ohlcv.jsonl"
    _write_ohlcv_jsonl(ohlcv_path, rows)

    captured: dict[str, Any] = {}

    def fake_render(footprint, output_path, symbol, from_ts=None, to_ts=None):
        captured["footprint"] = footprint

    monkeypatch.setattr(cli, "load_config", lambda _path: config_with_data)
    monkeypatch.setattr(cli, "render_cvd_heatmap", fake_render)
    monkeypatch.setattr(cli.time, "time", lambda: 1700002000)

    assert cli.main(["render"]) == 0

    footprint = cast(dict[int, list], captured["footprint"])
    assert len(footprint) == 1
    levels = footprint[1699999200]
    assert len(levels) == 2
    assert levels[0].buy_volume == pytest.approx(3.0)
    assert levels[1].buy_volume == pytest.approx(3.0)
