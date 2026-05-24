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

# BTC Selected 20 の 1分足OHLCV を取得（20銘柄すべて対象）
coinalyze-receiver selected20

# 取得対象の20銘柄を確認
coinalyze-receiver selected20 --show
```

### selected20 サブコマンド

`selected20` は BTC Selected 20 のスポット/パーペチュアル両方を対象に、`ohlcv_bars` テーブルへ 1分足OHLCV を保存します。
- 初回同期: 指定した `--days`（既定 1 日）分を取得
- 差分同期: 既存データの最終 `timestamp + 1分` から再取得
- レート制限: 2秒間隔で API を呼び出し、40 calls/min の制約に対して余裕を持って実行
- DB: `--db` で保存先を指定可能（省略時は `./data/coinalyze_1min.db`）
