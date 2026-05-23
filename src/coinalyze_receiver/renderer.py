from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Any
from .transform import FootprintLevel

def calculate_hybrid_scale(cvd_values: np.ndarray) -> tuple[float, float]:
    """
    CVD値の98パーセンタイルに基づいたスケールを計算する。
    外れ値による色の飽和を防ぎ、主要な分布のコントラストを最大化する。
    """
    if cvd_values.size == 0:
        return -1.0, 1.0
    
    # 絶対値の98パーセンタイルを算出
    abs_cvd = np.abs(cvd_values)
    v98 = np.percentile(abs_cvd, 98)
    
    # 0に近い場合は最小値を設定してゼロ除算を避ける
    if v98 == 0:
        v98 = 1.0
        
    return -v98, v98


def render_cvd_heatmap(
    footprint_data: dict[int, list[FootprintLevel]],
    output_path: Path,
    symbol: str = "BTCUSDT_PERP.A",
    title: str = "CVD Pseudo Footprint Heatmap"
) -> None:
    """
    FootprintデータをCVDヒートマップとしてPNG保存する。
    """
    if not footprint_data:
        print("No data to render.")
        return

    # データを行列形式に変換
    # X: 時間 (ts), Y: 価格 (price)
    sorted_ts = sorted(footprint_data.keys())
    all_prices = set()
    for levels in footprint_data.values():
        for lv in levels:
            all_prices.add(lv.price)
    
    sorted_prices = sorted(list(all_prices))
    price_map = {p: i for i, p in enumerate(sorted_prices)}
    
    # 行列の初期化 (Price x Time)
    grid = np.zeros((len(sorted_prices), len(sorted_ts)))
    
    all_cvds = []
    for j, ts in enumerate(sorted_ts):
        for lv in footprint_data[ts]:
            i = price_map[lv.price]
            grid[i, j] = lv.cvd
            all_cvds.append(lv.cvd)
    
    # Hybrid 98p Scale の適用
    vmin, vmax = calculate_hybrid_scale(np.array(all_cvds))
    
    # 描画
    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(
        grid, 
        aspect="auto", 
        cmap="RdYlGn", 
        vmin=vmin, 
        vmax=vmax, 
        interpolation="nearest"
    )
    
    # 軸設定
    ax.set_title(f"{symbol} - {title} (Scale: 98p = {vmax:.2f})")
    ax.set_xlabel("Time (Bars)")
    ax.set_ylabel("Price")
    
    # Y軸の目盛りを実際の価格にする (間引いて表示)
    tick_step = max(1, len(sorted_prices) // 10)
    ax.set_yticks(range(0, len(sorted_prices), tick_step))
    ax.set_yticklabels([f"{p:.1f}" for p in sorted_prices[::tick_step]])
    
    fig.colorbar(im, label="CVD")
    
    plt.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
