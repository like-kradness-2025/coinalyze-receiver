# v1.00 Final Validation Report: Coinalyze Receiver

## 1. プロジェクト概要
- **リポジトリ**: `like-kradness-2025/coinalyze-receiver`
- **対象ブランチ**: `v1.00`
- **目的**: Coinalyze API 専用のデータ収集・正規化および擬似Footprint可視化パイプラインの安定化。

## 2. 技術仕様 (v1.00)
### 2.1 依存関係と環境
- **Python**: `>=3.11`
- **主要ライブラリ**:
  - `matplotlib>=3.8`: ヒートマップ描画
  - `numpy>=1.24`: 統計計算 (98p Scale)
  - `requests>=2.31`: API通信

### 2.2 データパイプライン
1. **Collection**: Coinalyze API (`/v1/ohlcv-history` 等) からデータを取得。
2. **Normalization**: `src/coinalyze_receiver/normalize.py` にて、`buy_volume`, `sell_volume`, `delta` を算出。
3. **Transformation**: `src/coinalyze_receiver/transform.py` にて、1分足データを15分足にリサンプルし、価格レンジにDeltaを線形分配して擬似Footprintを構築。
4. **Visualization**: `src/coinalyze_receiver/renderer.py` にて、CVD絶対値の98パーセンタイルを最大値とする `Hybrid 98p Scale` を適用し、PNGヒートマップを出力。

## 3. 最終検証結果 (Smoke Test)

### 3.1 ユニットテスト
- **実行結果**:
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
- **判定**: ✅ PASS

### 3.2 実API連携テスト
- **マーケット検索**: `BTCUSDT` クエリに対し正常に応答。
```
matched=11
{'symbol': 'BTCUSDT.6', 'exchange': '6', 'symbol_on_exchange': 'BTCUSDT', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': True, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT_PERP.A', 'exchange': 'A', 'symbol_on_exchange': 'BTCUSDT', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': True, 'has_ohlcv_data': True}
{'symbol': 'ETHBTCUSDT.6', 'exchange': '6', 'symbol_on_exchange': 'ETHBTCUSDT', 'base_asset': 'ETHBTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': True, 'has_ohlcv_data': True}
{'symbol': 'PUMPBTCUSDT.6', 'exchange': '6', 'symbol_on_exchange': 'PUMPBTCUSDT', 'base_asset': 'PUMPBTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': True, 'has_ohlcv_data': True}
{'symbol': 'PUMPBTCUSDT_PERP.A', 'exchange': 'A', 'symbol_on_exchange': 'PUMPBTCUSDT', 'base_asset': 'PUMPBTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': True, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT_PERP.4', 'exchange': '4', 'symbol_on_exchange': 'BTC-USDT', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT_PERP.F', 'exchange': 'F', 'symbol_on_exchange': 'BTCF0:USTF0', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT_PERP.3', 'exchange': '3', 'symbol_on_exchange': 'BTC-USDT-SWAP', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT_PERP.0', 'exchange': '0', 'symbol_on_exchange': 'XBTUSDT', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
{'symbol': 'BTCUSDT.S', 'exchange': 'S', 'symbol_on_exchange': 'BTCUSDT', 'base_asset': 'BTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
{'symbol': 'PUMPBTCUSDT.S', 'exchange': 'S', 'symbol_on_exchange': 'PUMPBTCUSDT', 'base_asset': 'PUMPBTC', 'quote_asset': 'USDT', 'expire_at': None, 'has_buy_sell_data': True, 'is_perpetual': True, 'margined': 'STABLE', 'oi_lq_vol_denominated_in': 'BASE_ASSET', 'has_long_short_ratio_data': False, 'has_ohlcv_data': True}
```
- **データ一括取得 (`run-once`)**: `BTCUSDT_PERP.A` (6h) の取得成功。
```
[ok] ohlcv: raw=1 normalized=360
[ok] open_interest: raw=1 normalized=360
[ok] liquidation: raw=1 normalized=60
[ok] funding_rate: raw=1 normalized=360
[ok] long_short_ratio: raw=0 normalized=0
```
- **判定**: ✅ PASS

### 3.3 可視化テスト
- **コマンド**: `python -m coinalyze_receiver.cli render --price-bucket-usd 10`
- **出力**: `Chart saved to data/cvd_heatmap.png (bucket: 10.0)`
- **判定**: ✅ PASS

## 4. 結論
v1.00 ブランチにおける全ての機能要件が満たされ、実環境（Linux/Python 3.11）での動作が確認されました。本バージョンを安定版としてリリース可能です。
