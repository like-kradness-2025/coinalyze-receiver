# v1.00 Release Report: Coinalyze Receiver

## 1. 概要

`v1.00` は Coinalyze API 専用 Receiver / Collector の安定化ブランチです。

主目的は、Coinalyze API から取得したデータを raw / normalized JSONL として保存し、後段の pseudo footprint / renderer が利用できる形へ整えることです。

このブランチでは `ivarurdalen/coinalyze` SDK を採用し、自前 HTTP client を廃止しました。

---

## 2. 実装済み

### 2.1 Data Collection

- `COINALYZE_API_KEY` を環境変数から読む
- `ivarurdalen/coinalyze` SDK 経由で API 接続
- Future markets 確認
- OHLCV history 取得
- Open Interest history 取得
- Liquidation history 取得
- Funding Rate history 取得
- Long/Short Ratio history 取得
- raw JSONL 保存
- normalized JSONL 保存
- `runtime/health.json` 出力

### 2.2 CLI

実装済みコマンド:

```bash
python -m coinalyze_receiver.cli markets --query BTCUSDT
python -m coinalyze_receiver.cli run-once --symbol BTCUSDT_PERP.A --lookback 6h
python -m coinalyze_receiver.cli loop --symbol BTCUSDT_PERP.A --lookback 6h --every 15m
python -m coinalyze_receiver.cli render --price-bucket-usd 10
python -m coinalyze_receiver.cli notify
```

### 2.3 Pseudo Footprint Transform

当初仕様に合わせて、以下の方式に修正済みです。

```text
1分足ごとに high-low の価格bucketへ buy/sell を均等配分
→ 15分足へ合算
→ price bucketごとの buy / sell / cvd を生成
```

デフォルト価格bucket:

```text
10 USD
```

### 2.4 Dependencies

`pyproject.toml` に以下を追加済みです。

```toml
coinalyze @ git+https://github.com/ivarurdalen/coinalyze.git
matplotlib>=3.8
numpy>=1.24
requests>=2.31
```

外部SDK都合により Python は `>=3.11` です。

---

## 3. 重要な注意

### 3.1 True Footprintではない

このプロジェクトの出力は true tick-level footprint ではありません。

正しい呼称:

```text
Coinalyze OHLCV-based pseudo footprint
Pseudo Footprint
CVD heatmap proxy
```

誤った呼称:

```text
True footprint
Real bid/ask footprint
Orderbook heatmap
```

### 3.2 ReceiverとRendererは分離する

Receiverの責務:

```text
取得
正規化
保存
health出力
```

Rendererの責務:

```text
pseudo footprint変換
heatmap生成
Discord通知
```

現状は同一パッケージ内に含めていますが、判断ロジックや売買ロジックは入れません。

---

## 4. 検証状況

### 確認済み

- `pyproject.toml` 依存関係を整備
- SDK import方針確認
- pseudo footprint変換ロジックを当初仕様へ修正
- transform test 追加

### 要ローカル確認

この環境からは実APIキーを使った実行確認はできないため、以下はローカル/Termux側で確認してください。

```bash
pip install -e .
pytest
export COINALYZE_API_KEY="..."
python -m coinalyze_receiver.cli markets --query BTCUSDT
python -m coinalyze_receiver.cli run-once --symbol BTCUSDT_PERP.A --lookback 6h
python -m coinalyze_receiver.cli render --price-bucket-usd 10
```

確認対象:

```text
data/raw/*.jsonl
data/normalized/*.jsonl
runtime/health.json
data/cvd_heatmap.png
```

---

## 5. 残課題

- 実APIキーでのスモークテスト
- `BTCUSDT_PERP.A` が最適symbolかの確認
- Coinalyze実レスポンスと normalizer の完全照合
- rendererを横棒 pseudo footprint レイアウトへ発展
- Discord送信の実環境確認
- READMEの最終整備

---

## 6. v1.00 Done Definition

`v1.00` は以下を満たしたら完了です。

- `pip install -e .` が通る
- `pytest` が通る
- `markets` が通る
- `run-once` が raw / normalized JSONL を保存する
- `runtime/health.json` が出る
- `render --price-bucket-usd 10` がPNGを生成する
- APIキーやWebhook URLをログ・ファイルへ保存しない
- 再現性確認として、クリーンな仮想環境で `pip install .` を実行し、依存固定と通常インストールの挙動を確認する

---

## 7. 次フェーズ

`v1.10` 以降:

- 15分ローソク + 横棒 pseudo footprint renderer
- hybrid 98p overflow marker
- OI / liquidation / funding / L/S 補助パネル
- Discord定期配信
- Termux常駐運用
