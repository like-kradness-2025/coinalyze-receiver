import json
import subprocess
import sys
from pathlib import Path

import pytest

from coinalyze_receiver.config import Config
from coinalyze_receiver.receiver import Receiver
from coinalyze_receiver.selected20 import Selected20Fetcher, load_selected20
from coinalyze_receiver.storage import Storage


def _entry(i: int, market_type: str) -> dict:
    return {
        "symbol": f"BTC{i:02d}.T",
        "market_type": market_type,
        "exchange_name": "TestEx",
        "market_name": f"BTC Test {i}",
    }


def test_load_selected20_accepts_current_21_symbol_map(tmp_path: Path):
    data = [_entry(i, "future" if i < 13 else "spot") for i in range(21)]
    path = tmp_path / "selected20.json"
    path.write_text(json.dumps(data))

    assert len(load_selected20(str(path))) == 21


def test_selected20_cli_show_uses_current_home_map():
    result = subprocess.run(
        [sys.executable, "-m", "coinalyze_receiver.cli", "selected20", "--show"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Total: 21 symbols" in result.stdout


def test_cli_help_describes_21_current_symbols():
    result = subprocess.run(
        [sys.executable, "-m", "coinalyze_receiver.cli", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "21 BTC markets" in result.stdout
    assert "20 BTC markets" not in result.stdout


def test_storage_has_no_dead_get_data_helper():
    assert not hasattr(Storage(":memory:"), "get_data")


def test_selected20_fetcher_closes_client_if_symbol_load_fails(monkeypatch, tmp_path: Path):
    closed = {"value": False}

    class FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def close(self):
            closed["value"] = True

    def boom():
        raise ValueError("bad symbol map")

    monkeypatch.setattr("coinalyze_receiver.selected20.CoinalyzeClient", FakeClient)
    monkeypatch.setattr("coinalyze_receiver.selected20.load_selected20", boom)

    with pytest.raises(ValueError, match="bad symbol map"):
        Selected20Fetcher(Config(api_key="x", db_path=str(tmp_path / "db.sqlite")))

    assert closed["value"] is True


def test_receiver_closes_client_if_storage_init_fails(monkeypatch):
    closed = {"value": False}

    class FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def close(self):
            closed["value"] = True

    class BrokenStorage:
        def __init__(self, db_path: str):
            raise RuntimeError("storage init failed")

    monkeypatch.setattr("coinalyze_receiver.receiver.CoinalyzeClient", FakeClient)
    monkeypatch.setattr("coinalyze_receiver.receiver.Storage", BrokenStorage)

    with pytest.raises(RuntimeError, match="storage init failed"):
        Receiver(Config(api_key="x", db_path=":memory:"))

    assert closed["value"] is True
