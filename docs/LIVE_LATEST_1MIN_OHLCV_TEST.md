# Live Latest 1min OHLCV Test 指示書

## 目的

Coinalyze の OHLCV history API について、**最新の確定1分足がどの程度の遅延で取得できるか**を確認する。

特に以下を切り分ける。

- 本当に約9時間遅延しているのか
- UTC/JST表示差によって9時間ズレて見えているだけなのか
- 数分程度の通常更新遅延なのか

## 対象テスト

```text
tests/test_live_latest_1min_ohlcv.py
```

このテストは実APIを叩く live smoke test である。
`COINALYZE_API_KEY` が設定されていない場合は skip される。

## 前提

- Python環境に依存関係が入っていること
- Coinalyze API key を持っていること
- ネットワーク接続があること

セットアップ例:

```bash
pip install -e .
pip install pytest
```

## 実行方法

### デフォルト3symbolで実行

```bash
COINALYZE_API_KEY=あなたのAPIキー \
pytest -q -s tests/test_live_latest_1min_ohlcv.py
```

デフォルト対象:

```text
BTCUSDT_PERP.A
ETHUSDT_PERP.A
SOLUSDT_PERP.A
```

### symbolを指定して実行

```bash
COINALYZE_LIVE_TEST_SYMBOLS=BTCUSDT_PERP.A,ETHUSDT_PERP.A,SOLUSDT_PERP.A \
COINALYZE_API_KEY=あなたのAPIキー \
pytest -q -s tests/test_live_latest_1min_ohlcv.py
```

指定できるsymbolは最大3つ。

## 出力例

```text
Coinalyze latest closed 1m OHLCV smoke test
request_window_utc: 2026-05-24T00:30:00+00:00 -> 2026-05-24T00:31:00+00:00
symbol,last_t_utc,last_t_jst,lag_sec,open,high,low,close,volume,buy_volume
BTCUSDT_PERP.A,2026-05-24T00:30:00+00:00,2026-05-24T09:30:00+09:00,75,xxxxx,xxxxx,xxxxx,xxxxx,123.45,67.89
```

## 見るポイント

最重要は `lag_sec`。

| lag_sec | 解釈 |
|---:|---|
| 0〜300秒程度 | ほぼリアルタイム、または数分遅延 |
| 300〜1800秒 | やや遅いが監視用途では許容検討 |
| 約32400秒 | 約9時間遅延の可能性が高い |
| UTCが9時間前に見えるがJSTが現在に近い | タイムゾーン表示問題 |

## 合格条件

テスト内では以下を暫定合格条件にしている。

```text
lag_sec < 30 * 60
```

つまり、最新1分足が30分以上古ければ失敗する。

## 失敗時の読み方

### `COINALYZE_API_KEY is not set` でskip

APIキー未設定。

```bash
export COINALYZE_API_KEY=あなたのAPIキー
```

またはコマンド先頭に付けて実行する。

### `no OHLCV rows returned`

考えられる原因:

- symbolがCoinalyze上で存在しない
- そのsymbolにOHLCV historyがない
- 最新1分足がまだ生成されていない
- API側の一時的な遅延

対処:

```bash
COINALYZE_LIVE_TEST_SYMBOLS=BTCUSDT_PERP.A,ETHUSDT_PERP.A,SOLUSDT_PERP.A \
COINALYZE_API_KEY=あなたのAPIキー \
pytest -q -s tests/test_live_latest_1min_ohlcv.py
```

### `latest 1m OHLCV looks stale`

`lag_sec` が30分以上。

この場合は次を確認する。

1. `last_t_utc` と `last_t_jst` を見る
2. `last_t_jst` が現在時刻に近いなら、UTC/JSTの見え方問題
3. `last_t_jst` も古いなら、Coinalyze側の実データ遅延の可能性

## 注意

このテストは実APIを使うため、通常CIで常時実行しない。
ローカル検証または手動確認用として使う。

pytest marker warning が気になる場合は、将来的に `pyproject.toml` に以下を追加する。

```toml
[tool.pytest.ini_options]
markers = [
    "live: tests that call external live APIs",
]
```

## 運用判断

このテストで `lag_sec` が常に小さい場合:

- Coinalyze polling receiver は短期監視補助として使える
- 1分足の遅延確認用途にも使える

このテストで `lag_sec` が大きい場合:

- Coinalyzeはリアルタイム監視の主軸にしない
- 取引所WebSocketで1分足を自前生成する
- Coinalyzeは欠損補完・後追い検証・クロスチェック用に回す
