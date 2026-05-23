from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .transform import FootprintLevel


def _parse_ts_bound(value: int | str | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except ValueError:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())


def filter_footprint_by_ts(
    footprint_data: dict[int, list[FootprintLevel]],
    from_ts: int | str | None = None,
    to_ts: int | str | None = None,
) -> dict[int, list[FootprintLevel]]:
    """Filter footprint data by timestamp range."""
    start = _parse_ts_bound(from_ts)
    end = _parse_ts_bound(to_ts)
    if start is None and end is None:
        return footprint_data
    filtered: dict[int, list[FootprintLevel]] = {}
    for ts, levels in footprint_data.items():
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        filtered[ts] = levels
    return dict(sorted(filtered.items()))


def calculate_hybrid_scale(cvd_values: np.ndarray) -> tuple[float, float]:
    if cvd_values.size == 0:
        return -1.0, 1.0
    abs_cvd = np.abs(cvd_values)
    v98 = np.percentile(abs_cvd, 98)
    if v98 == 0:
        v98 = 1.0
    return -v98, v98


def render_cvd_heatmap(
    footprint_data: dict[int, list[FootprintLevel]],
    output_path: Path,
    symbol: str = "BTCUSDT_PERP.A",
    title: str = "CVD Pseudo Footprint Heatmap",
    from_ts: int | str | None = None,
    to_ts: int | str | None = None,
) -> None:
    """FootprintデータをCVDヒートマップとしてPNG保存する。"""
    footprint_data = filter_footprint_by_ts(footprint_data, from_ts=from_ts, to_ts=to_ts)
    if not footprint_data:
        print("No data to render.")
        return

    sorted_ts = sorted(footprint_data.keys())
    all_prices = set()
    for levels in footprint_data.values():
        for lv in levels:
            all_prices.add(lv.price)

    sorted_prices = sorted(list(all_prices))
    price_map = {p: i for i, p in enumerate(sorted_prices)}

    grid = np.zeros((len(sorted_prices), len(sorted_ts)))

    all_cvds = []
    for j, ts in enumerate(sorted_ts):
        for lv in footprint_data[ts]:
            i = price_map[lv.price]
            grid[i, j] = lv.cvd
            all_cvds.append(lv.cvd)

    vmin, vmax = calculate_hybrid_scale(np.array(all_cvds))

    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(grid, aspect="auto", cmap="RdYlGn", vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_title(f"{symbol} - {title} (Scale: 98p = {vmax:.2f})")
    ax.set_xlabel("Time (Bars)")
    ax.set_ylabel("Price")

    tick_step = max(1, len(sorted_prices) // 10)
    ax.set_yticks(range(0, len(sorted_prices), tick_step))
    ax.set_yticklabels([f"{p:.1f}" for p in sorted_prices[::tick_step]])

    fig.colorbar(im, label="CVD")
    plt.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
