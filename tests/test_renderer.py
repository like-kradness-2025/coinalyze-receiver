from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from coinalyze_receiver.renderer import calculate_hybrid_scale, render_cvd_heatmap
from coinalyze_receiver.transform import FootprintLevel


def test_calculate_hybrid_scale_handles_empty_array():
    assert calculate_hybrid_scale(np.array([])) == (-1.0, 1.0)


def test_calculate_hybrid_scale_returns_symmetric_98p_range():
    values = np.array([-1000.0, -500.0, 100.0, 200.0, 4000.0])
    vmin, vmax = calculate_hybrid_scale(values)

    assert vmin < 0 < vmax
    assert close_to(vmax, -vmin)


def test_render_cvd_heatmap_creates_png_and_clears_figure(tmp_path: Path):
    data = {
        1700000000: [
            FootprintLevel(price=1000.0, buy_volume=10.0, sell_volume=5.0, cvd=5.0),
            FootprintLevel(price=1010.0, buy_volume=2.0, sell_volume=8.0, cvd=-6.0),
        ],
        1700000900: [
            FootprintLevel(price=1000.0, buy_volume=7.0, sell_volume=3.0, cvd=4.0),
        ],
    }

    out = tmp_path / "test.png"
    render_cvd_heatmap(data, output_path=out, symbol="TEST")

    assert out.exists()
    assert out.stat().st_size > 0


def close_to(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b))
