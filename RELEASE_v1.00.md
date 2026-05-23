# v1.00 Release Report: Coinalyze Receiver Stabilization & Visualization

## 1. 概要
Coinalyze API専用Receiverの安定化および、1分足OHLCVデータから15分足CVDヒートマップを生成・通知するパイプラインを実装しました。

## 2. 実装済み機能
### 2.1 Data Collection (Stability)
- **実API連携**: `COINALYZE_API_KEY` を用いた認証およびデータ取得。
- **Dataset**: OHLCV, Open Interest, Liquidation, Funding Rate, Long/Short Ratio の5種をサポート。
- **保存形式**: Raw JSONL および Normalized JSONL による保存。
- **ヘルスチェック**: `runtime/health.json` による取得成功/失敗の記録。

### 2.2 Transformation (Pseudo Footprint)
- **15m Resampling**: 1分足データを15分足に集計。
- **Pseudo Footprint**: 15分足のDelta値を価格レンジに線形分配し、価格レベルごとのCVDを擬似的に構築。

### 2.3 Visualization (Hybrid 98p Scale)
- **Hybrid Scale**: 全データCVD値の98パーセンタイルを算出し、カラーマップ上限に固定。外れ値による色の飽和を防止。
- **Heatmap**: `matplotlib` を使用し、X軸(時間) x Y軸(価格) のCVDヒートマップをPNG出力。

### 2.4 Notification
- **Discord Webhook**: 生成したPNGをDiscordへ自動送信。

## 3. 検証結果 (Smoke Test)
### 3.1 API取得テスト
- Symbol: `BTCUSDT_PERP.A`
- 取得結果: 全データセットにおいて正常に取得・保存を確認。

### 3.2 ユニットテスト
```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0 -- /home/weed420/coinalyze-receiver/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/weed420/coinalyze-receiver
configfile: pyproject.toml
collecting ... collected 1 item

tests/test_normalize.py::test_normalize_ohlcv_delta_fields PASSED        [100%]

============================== 1 passed in 0.00s ===============================
```

### 3.3 成果物確認
- `data/cvd_heatmap.png` の正常生成およびDiscordへの送信を確認済み。

## 4. 運用コマンド
- 取得: `python -m coinalyze_receiver.cli run-once --symbol BTCUSDT_PERP.A --lookback 6h`
- 描画: `python -m coinalyze_receiver.cli render`
- 通知: `python -m coinalyze_receiver.cli notify`
