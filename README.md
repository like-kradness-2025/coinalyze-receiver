# coinalyze-receiver

Coinalyze API から仮想通貨デリバティブ市場データを受信し、SQLite に保存する CLI ツール。

## 収集データ

| エンドポイント | テーブル | 内容 |
|--------------|---------|------|
| OHLCV | `ohlcv_bars` | 価格・出来高・買い出来高・トレード数 |
| Open Interest | `open_interest` | OI 始値・高値・安値・終値 |
| Liquidation | `liquidations` | ロング/ショート liquidation 量 |
| Funding Rate | `funding_rates` | 資金調達率 |
| Long/Short Ratio | `ls_ratios` | L/S 比率・割合 |

## セットアップ

```bash
# 環境変数
cp .env.example .env
# .env に COINALYZE_API_KEY を設定

# インストール
pip install -e .
```

## 使い方

```bash
# 全データ取得（デフォルト: BTCUSDT_PERP.A, 1h, 7日遡り）
coinalyze-receiver

# 特定シンボル・間隔
coinalyze-receiver -s ETHUSDT_PERP.A,BTCUSDT_PERP.A -i 1hour,4hour -d 30

# 市場一覧
coinalyze-receiver --list-markets

# 検索
coinalyze-receiver --search BTC
```
