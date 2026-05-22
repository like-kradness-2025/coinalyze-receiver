# coinalyze-receiver

Coinalyze API 専用の軽量 Receiver / Collector です。

目的は、Coinalyze の履歴APIから BTCUSDT 系のデータを定期取得し、後段の `Coinalyze Pseudo Footprint + Position Flow` 描画に使える形で保存することです。

このリポは `btc-receiver` とは別ラインです。Binance WebSocket、板、ローカル orderbook、`live_book_bucketed` には依存しません。

## MVP の範囲

- Coinalyze API key を環境変数から読む
- OHLCV 1min を取得する
- Open Interest history を取得する
- Liquidation history を取得する
- Funding Rate history を取得する
- Long/Short Ratio history を取得する
- raw JSONL と normalized JSONL を保存する
- `run-once` / `loop` で実行する

描画・Discord送信・疑似Footprint変換は次フェーズです。

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

`.env` かシェルに API key を設定します。

```bash
export COINALYZE_API_KEY="your_api_key_here"
```

## Usage

### 1回取得

```bash
python -m coinalyze_receiver.cli run-once --symbol BTCUSDT_PERP.A --lookback 6h
```

### 15分ごとに取得

```bash
python -m coinalyze_receiver.cli loop --symbol BTCUSDT_PERP.A --lookback 6h --every 15m
```

### 保存先

```text
data/raw/*.jsonl
data/normalized/*.jsonl
runtime/health.json
```

## Symbol note

Coinalyze の symbol は `BTCUSDT_PERP.A` のように exchange suffix を含む形式です。まず `future-markets` で対象symbolを確認してください。

```bash
python -m coinalyze_receiver.cli markets --query BTCUSDT
```

## Design policy

- Receiver は判断しない
- Receiver は取得・正規化・保存に集中する
- 欠損やAPI失敗は health に残す
- raw response を保存し、後から再正規化できるようにする

## Next phase

- 1m OHLCV/bv -> 15m pseudo footprint transform
- hybrid 98p scale
- PNG renderer
- Discord webhook sender
