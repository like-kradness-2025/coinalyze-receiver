# coinalyze-receiver v2 Design Decisions

> 決定事項の記録。追加・変更があれば追記する。

## 1. Language

**決定**: Python

- 現状の知財（pandas/numpy/matplotlib連携）を活用
- 書き直し範囲を最小化

## 2. HTTP Client

**決定**: httpx 直叩き（`pip coinalyze` 廃止）

- `httpx_retries` の小数 Retry-After パース不能バグを排除
- `pyrate-limiter<4.0` 縛りから解放
- レート制御（40 calls/min）を自前管理
- タイムゾーントラップ排除
- 依存最小化

## 3. Data Scope

**決定**: 現状維持（21 symbols, 5 data types）

| Data Type | Interval | Symbols | Calls/Cycle |
|-----------|----------|---------|-------------|
| OHLCV (bars) | 1min | 21 (all) | 21 |
| Open Interest | 1min | 13 (perp only) | 13 |
| Funding Rate | 1min | 13 (perp only) | 13 |
| Liquidation | 1min | 13 (perp only) | 13 |
| L/S Ratio | 15min | 13 (perp only) | 13 |
| **Total** | | | **73** |

将来的に絞る可能性あり（特にLiquidation/ L/S RatioはAPI側で空データが多い）。

## 4. Fetch Cycle Interval

**決定**: **3分**

- 73 calls/cycle を 180秒に分散 → ~24 calls/min、Rate Limit (40/min) に対して余裕あり
- 単純なループで構成可能（スロットル不要）

### 同期ズレ対策

全symbolの取得範囲を揃えるため、リクエスト `from` 時刻は共通で **`now - 3min`** を使用する。

```python
fetch_from = int(time.time()) - 180  # 全symbol共通
```

- 最初と最後のsymbolで最大~2分の実取得時刻差が生じるが、「どの時刻範囲のデータを要求するか」は揃う
- 3分の鮮度ロスはCoinalyzeの~50sレイテンシに対して十分小さく、実用上問題にならない
- 非同期待ち（asyncio並列fetch）は不要と判断

## 5. DB

**決定**: **SQLite継続**

- WALモード、UPSERT、range query の現状運用で問題なし
- データ量 ~50MB/day max、単一プロセス書き込みで競合リスクなし
- 分析スクリプト（footprint, monitor類）との互換性そのまま
- DuckDBに変えるメリットが薄い（書き込みパターンが合わない）

## 6. Deploy

**決定**: テスト環境=手動実行 / 本番(Termux)=nohup

| 環境 | 方式 | 理由 |
|------|------|------|
| ローカル（開発・テスト） | 手動実行 `python -m coinalyze_receiver.cli` | 頻繁に書き換えるので気軽に起動停止できる |
| Termux（本番） | nohup (`run_loop.sh`) | Termuxにsystemdなし、tmuxは不安定。nohupが実績あり |

常駐ループは CLI の `loop` サブコマンドで提供（signal ハンドラ付き）。

## 7. Architecture

**決定**: 5モジュール構成

```
src/coinalyze_receiver/
├── __init__.py       # package marker + version
├── config.py         # Config dataclass + from_env()
├── client.py         # httpx 直叩き + レートリミッター（40 calls/min）
├── storage.py        # SQLite storage（既存スキーマ踏襲）
├── fetcher.py        # 全symbol×全data type の fetch→store orchestration
├── cli.py            # argparse CLI (fetch / loop / list-markets / show)
```

### モジュール責務

| モジュール | 役割 | v1からの変更 |
|-----------|------|-------------|
| `config.py` | env読み込み、Config提供 | ほぼそのまま |
| `client.py` | httpx直叩き、RateLimit制御 | **新規**（pip coinalyze廃止） |
| `storage.py` | SQLite UPSERT、range query | 既存流用（微修正） |
| `fetcher.py` | 全symbol×全data type取得制御 | selected20.py 統合・簡略化 |
| `cli.py` | `fetch`（一回）/ `loop`（常駐） | 新規 |

### ポイント

- **client.py**: httpx.Client でCoinalyze API直叩き。`api_key` ヘッダのみ認証。自前RateLimiterで40calls/min厳守（スライディングウィンドウ or 単純sleep）。
- **fetcher.py**: 全symbolに `from=now-3min` を共通適用して同期ズレ排除。spot/perpで取得対象data typeを振り分け。
- **cli.py**: `fetch` = 一回実行して終了 / `loop` = 3分ループ + SIGTERM/SIGINT でgraceful shutdown。
