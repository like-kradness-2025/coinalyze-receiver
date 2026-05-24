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
- raw JSONL は履歴として追記保存し、`_saved_at` による保存時刻ベースのローテーションで 7日超の行を削除する
- `run-once` / `loop` で実行する

描画・Discord送信・疑似Footprint変換は次フェーズです。

## Setup

### 前提条件

- Python 3.11 以上

### 開発用導入（editable install）

ローカル開発では `pip install -e .` を使います。これはソースツリーを直接参照するため、コード変更をすぐ反映できますが、厳密な再現性を確認する用途では `pip install .` を使ってください。

```bash
# 1. 仮想環境の作成
python -m venv .venv

# 2. 仮想環境の有効化
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. 開発用インストール
pip install -e .

# 4. 環境変数設定ファイルのコピー
cp .env.example .env
```

`.env` かシェルに API key を設定します。

```bash
export COINALYZE_API_KEY="your_api_key_here"
```

### 再現性のある導入手順

完全に固定された依存関係で再現性を重視する場合は、ビルド環境も含めて `pyproject.toml` の固定値に従う必要があります。

固定されている主なバージョン:

| パッケージ | バージョン |
|-----------|----------|
| matplotlib | 3.10.9 |
| numpy | 2.4.6 |
| requests | 2.34.2 |
| coinalyze | 0.1.1 |
| pyrate-limiter | 3.9.0 |
| setuptools | 79.0.1 |

再現性を重視する場合は、クリーンな仮想環境で通常インストールを行い、ビルド時の `setuptools` も固定値を使ってください。

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

すべての依存パッケージの完全なリストは `pyproject.toml` を確認してください。

### バージョンの確認

インストール後に以下のコマンドでインストールされたバージョンを確認できます。

```bash
pip list
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
- CLI の件数表示は `raw` / `fetched` / `persisted` を分けている
- render は読み込み時にも `symbol + ts` で重複排除する

## Next phase

- 1m OHLCV/bv -> 15m pseudo footprint transform
- hybrid 98p scale
- PNG renderer
- Discord webhook sender
