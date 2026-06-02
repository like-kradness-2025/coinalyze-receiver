# Coinalyze Receiver v2 — Wiring Diagram & Interface Consistency Check

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Interfaces](#module-interfaces)
3. [Data Flow: One Fetch Cycle](#data-flow-one-fetch-cycle)
4. [Result Model (3-State Sentinel Codes)](#result-model)
5. [Rate Limiter Path](#rate-limiter-path)
6. [429 Retry Path](#429-retry-path)
7. [401 Abort Path](#401-abort-path)
8. [Backfill vs Incremental Sync Logic](#backfill-vs-incremental-sync-logic)
9. [Exception Matrix](#exception-matrix)
10. [Interface Consistency Checks](#interface-consistency-checks)
11. [Unused/Dead Code Notes](#unused-dead-code-notes)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         cli.py (entry point)                        │
│  argparse → main() → dispatch to subcommand functions               │
└────────────────────┬──────────────┬──────────────┬──────────────────┘
                     │              │              │
          cmd_fetch/loop  cmd_show    cmd_list-markets
                     │              │              │
                     ▼              ▼              ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │ fetcher  │   │ fetcher  │   │ client  │
              │ .py      │   │ .py      │   │ .py     │
              │ Fetcher  │   │load_sym- │   │Coinalyze│
              │ class    │   │bols()    │   │Client   │
              └────┬─────┘   └──────────┘   └─────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
   ┌──────────┐     ┌──────────┐
   │ client.py│     │ storage  │
   │Coinalyze │     │ .py      │
   │Client    │     │ Storage  │
   └──────────┘     └────┬─────┘
                         │
                         ▼
                   ┌──────────┐
                   │ SQLite DB │
                   │ coinalyze │
                   │ _v2.db   │
                   │ (5 tables)│
                   └──────────┘
```

### Module Dependency Graph

```
cli.py ──→ config.py (Config.from_env, Config.validate)
cli.py ──→ fetcher.py (Fetcher, FatalError, load_symbols, sentinels, constants)
cli.py ──→ client.py (CoinalyzeClient for cmd_list_markets)

fetcher.py ──→ config.py (Config dataclass)
fetcher.py ──→ client.py (CoinalyzeClient)
fetcher.py ──→ storage.py (Storage, normalize_timestamps)
fetcher.py ──→ httpx (exception handling)

storage.py ──→ sqlite3, pandas (no internal module deps)
client.py ──→ httpx (no internal module deps)
config.py ──→ os, dataclasses, pathlib (no internal module deps)
```

No circular dependencies. Each module imports only from modules listed above it.

---

## Module Interfaces

### 1. `config.py` — Configuration

| Symbol | Type | Description |
|--------|------|-------------|
| `Config` | `@dataclass` | Application config |
| `.api_key` | `str` | From `COINALYZE_API_KEY` env var |
| `.db_path` | `str` | From `COINALYZE_DB_PATH` env var (default: `cwd/data/coinalyze_v2.db`) |
| `.log_level` | `str` | From `LOG_LEVEL` env var (default: `"INFO"`) |
| `Config.from_env()` | `@classmethod → Config` | Factory: reads env vars |
| `Config.validate()` | `→ list[str]` | Returns error strings; empty if valid |

**Exceptions raised**: None.

---

### 2. `client.py` — Coinalyze API Client

| Symbol | Type | Description |
|--------|------|-------------|
| `BASE_URL` | `str` | `"https://api.coinalyze.net/v1"` |
| `RATE_LIMIT` | `int=40` | Max calls per window |
| `RATE_WINDOW` | `int=60` | Window in seconds |
| `ENDPOINTS` | `dict[str,str]` | Maps endpoint key → API path |
| `INTERVAL_PARAM` | `dict[str,str]` | Maps human interval → API param |
| `ENDPOINT_INTERVALS` | `dict[str,str]` | Per-endpoint default intervals |
| `RateLimitExceeded` | `Exception` | **Defined but never raised** (dead code) |
| `Client(api_key: str)` | class | HTTP client with rate limiting |
| `Client.__init__(api_key)` | `→ None` | Creates `httpx.Client(timeout=30.0)` with `api_key` header, initializes `deque[float]` for sliding window |
| `Client.close()` | `→ None` | Calls `self._http.close()` |
| `Client._wait_for_capacity()` | `→ None` | Blocks until rate limit has capacity; recursive via `time.sleep()` |
| `Client._record_call()` | `→ None` | Appends `time.time()` to deque |
| `Client._request(endpoint, params)` | `→ list[dict[str,Any]]` | Core: rate-limited GET, 429→retry-once, 401→raise, 400+→raise |
| `Client.get_history(endpoint, symbol, from_ts, to_ts, interval=None)` | `→ list[dict[str,Any]]` | Builds params dict, delegates to `_request` |
| `Client.search_markets(query)` | `→ list[dict[str,Any]]` | Hits `/future-markets` + `/spot-markets`, filters by query |

**Exceptions raised**:

| Exception | Where | Condition |
|-----------|-------|-----------|
| `ValueError` | `_request` | Unknown endpoint key |
| `httpx.HTTPStatusError` | `_request` | 401 status (`resp.raise_for_status()`) |
| `httpx.HTTPStatusError` | `_request` | 400+ status (`resp.raise_for_status()`) |

---

### 3. `fetcher.py` — Fetcher (Orchestrator)

| Symbol | Type | Description |
|--------|------|-------------|
| `SYMBOL_MAP_PATH` | `Path` | `~/.hermes/data/coinalyze/coinalyze-btc-selected-20-symbol-market-map.json` |
| `FatalError` | `Exception` | Raised on 401; caught in `cli.py` → `sys.exit(1)` |
| `OK` | `int=0` | Success sentinel |
| `ERROR` | `int=-1` | API/network failure sentinel |
| `NODATA` | `int=-2` | Empty API response sentinel |
| `ENDPOINT_CONFIGS` | `list[tuple[str,str,str]]` | `[(endpoint, interval, table_name), ...]` — 5 tuples |
| `_PERP_ONLY_ENDPOINTS` | `set[str]` | 4 endpoints that only apply to perp symbols |
| `LOOKBACK_DAYS_DEFAULT` | `int=7` | Default lookback window in days |
| `LOOKBACK_SECONDS_DEFAULT` | `int=604800` | Default lookback window in seconds |
| `_FIELD_MAPS` | `dict[str,dict[str,str]]` | Maps API response field → DataFrame column per endpoint |
| `load_symbols(symbol_map_path: str)` | `→ tuple[list[str],list[str],list[str]]` | Loads & validates JSON → `(spot, perp, all)` |
| `Fetcher(config: Config)` | class | Orchestrator |
| `Fetcher.__init__(config)` | `→ None` | Calls `load_symbols`, creates `CoinalyzeClient`, `Storage` |
| `Fetcher.close()` | `→ None` | Calls `self.client.close()` |
| `Fetcher.build_timestamps()` | `@staticmethod → tuple[int,int]` | Returns `(common_from, to)` minute-aligned UNIX seconds |
| `Fetcher._fetch_range(endpoint, symbol, fetch_from, fetch_to, interval, table)` | `→ tuple[int,str]` | Single range: API call → map to DataFrame → upsert → return `(count|code, detail)` |
| `Fetcher.fetch_one(endpoint, symbol, from_ts, to_ts, interval, table, lookback_seconds=0)` | `→ tuple[int,str]` | Phase 1 (backfill) + Phase 2 (incremental) |
| `Fetcher.fetch_cycle(lookback_seconds=604800)` | `→ dict[str, dict[str, tuple[int,str]]]` | Full cycle: iterate all endpoint/symbol combos |
| `Fetcher.format_summary(results, spot_symbols, perp_symbols)` | `@staticmethod → str` | Human-readable summary |

**Exceptions raised**:

| Exception | Where | Condition |
|-----------|-------|-----------|
| `FatalError` | `_fetch_range` | 401 HTTP status from API |
| `ValueError` | `load_symbols` | Invalid JSON structure, wrong count, bad market_type, duplicates, empty categories |
| `FileNotFoundError` | `load_symbols` | Symbol map file missing |
| `json.JSONDecodeError` | `load_symbols` | Invalid JSON syntax |

---

### 4. `storage.py` — SQLite Storage

| Symbol | Type | Description |
|--------|------|-------------|
| `normalize_timestamps(df)` | `→ pd.DataFrame` | Ensures timestamp column is UNIX int64 |
| `SCHEMA_SQL` | `str` | `CREATE TABLE IF NOT EXISTS` for 5 tables |
| `ENDPOINT_TABLE_MAP` | `dict[str,str]` | Maps endpoint → table name (**unused** — dead code) |
| `Storage(db_path: str)` | class | SQLite storage |
| `Storage.__init__(db_path)` | `→ None` | Mkdir, init schema |
| `Storage._init_schema()` | `→ None` | Executes `SCHEMA_SQL` |
| `Storage._conn()` | `→ sqlite3.Connection` | Creates connection with WAL mode |
| `Storage.get_existing_range(table, symbol)` | `→ tuple[Optional[int],Optional[int]]` | Returns `(MIN(timestamp), MAX(timestamp))` or `(None, None)` |
| `Storage.upsert_dataframe(table, df)` | `→ int` | `INSERT ... ON CONFLICT(symbol, timestamp) DO UPDATE SET ...` — returns row count |
| `Storage.count_rows(table, symbol=None)` | `→ int` | `COUNT(*)` with optional `WHERE symbol = ?` |

**Exceptions raised**: None explicitly (relies on `sqlite3` exceptions).

---

### 5. `cli.py` — CLI Entry Point

| Symbol | Type | Description |
|--------|------|-------------|
| `setup_logging(verbose, default_level)` | `→ None` | Configures root logger |
| `cmd_fetch(config, verbose, lookback_seconds)` | `→ None` | One fetch cycle; exits 0 (ok) or 1 (error) |
| `cmd_loop(config, verbose, lookback_seconds)` | `→ None` | Infinite 3-min cycles; `SIGINT`/`SIGTERM` graceful shutdown |
| `cmd_show(config, verbose)` | `→ None` | Print symbol map table (no API call) |
| `cmd_list_markets(config, verbose, keyword)` | `→ None` | Search markets via API |
| `_col_width(header, ncols)` | `→ int` | Column width lookup |
| `main()` | `→ None` | Argparse dispatch to subcommands |

**Subcommands**:

| Command | Function | Args | API call? | DB access? |
|---------|----------|------|-----------|------------|
| `fetch` | `cmd_fetch` | `--verbose`, `--lookback` days | Yes | Yes |
| `loop` | `cmd_loop` | `--verbose`, `--lookback` days | Yes (repeating) | Yes |
| `show` | `cmd_show` | `--verbose` | No | No |
| `list-markets` | `cmd_list_markets` | `keyword`, `--verbose` | Yes | No |
| `search` | `cmd_list_markets` | `keyword`, `--verbose` | Yes (alias) | No |

---

## Data Flow: One Fetch Cycle

### Call Sequence (numbered steps)

```
User CLI input
  ↓
1. main()
   ├── argparse.parse_args() → args
   ├── Config.from_env() → config           [config.py]
   ├── config.validate() (for fetch/loop/list-markets/search)
   └── dispatch to cmd_fetch(config, verbose, lookback_seconds)
       ↓
2. cmd_fetch()
   ├── setup_logging(verbose, INFO)
   ├── Fetcher(config) → fetcher            [fetcher.py]
   │    ├── load_symbols(SYMBOL_MAP_PATH)    [fetcher.py: l.105]
   │    │    ├── open JSON file
   │    │    ├── validate: list of 21 dicts, each with symbol+market_type
   │    │    ├── no duplicates
   │    │    ├── both spot & perp non-empty
   │    │    └── return (spot_symbols, perp_symbols, all_symbols)
   │    ├── CoinalyzeClient(config.api_key)  [client.py: l.62]
   │    │    └── httpx.Client(headers={"api_key": ...}, timeout=30.0)
   │    │    └── self._call_times = deque()  # sliding window
   │    └── Storage(config.db_path)          [storage.py: l.92]
   │         ├── Path(db_path).parent.mkdir(parents=True)
   │         └── _init_schema()
   │              └── executescript(SCHEMA_SQL)  # 5 CREATE TABLE IF NOT EXISTS
   │
   ├── fetcher.build_timestamps() → (common_from, to)  [fetcher.py: l.209]
   │    ├── now = time.time()
   │    ├── to = floor(now, minute)
   │    └── common_from = floor(now - 180, minute)
   │
   ├── fetcher.fetch_cycle(lookback_seconds=604800) → results  [fetcher.py: l.395]
   │    │
   │    │  For each (endpoint, interval, table) in ENDPOINT_CONFIGS:
   │    │  │
   │    │  │  symbols = perp_symbols if endpoint in _PERP_ONLY_ENDPOINTS
   │    │  │           else all_symbols
   │    │  │
   │    │  │  For each symbol in symbols:
   │    │  │  │
   │    │  │  │  fetcher.fetch_one(endpoint, symbol, common_from, to,
   │    │  │  │  │                 interval, table, lookback_seconds)
   │    │  │  │  │
   │    │  │  │  │  ┌── RETURN: (code, detail)  ──┐
   │    │  │  │  │  │  code >= 0  → inserted count │
   │    │  │  │  │  │  code ==  0 → "up-to-date"   │
   │    │  │  │  │  │  code == -1 → ERROR          │
   │    │  │  │  │  │  code == -2 → NODATA         │
   │    │  │  │  │  └──────────────────────────────┘
   │    │  │  │  │
   │    │  │  │  │  ┌── fetch_one() INTERNALS:  [fetcher.py: l.314]
   │    │  │  │  │  │
   │    │  │  │  │  │  storage.get_existing_range(table, symbol)
   │    │  │  │  │  │    → (min_ts, max_ts) | (None, None)
   │    │  │  │  │  │
   │    │  │  │  │  │  PHASE 1 — Backfill/Gap-fill:
   │    │  │  │  │  │    if lookback_seconds > 0 AND min_ts is not None:
   │    │  │  │  │  │      backfill_target = to_ts - lookback_seconds
   │    │  │  │  │  │      if min_ts > backfill_target:
   │    │  │  │  │  │        backfill_from = backfill_target
   │    │  │  │  │  │        backfill_to = min_ts - 60
   │    │  │  │  │  │        if backfill_from < backfill_to:
   │    │  │  │  │  │          _fetch_range(endpoint, symbol,
   │    │  │  │  │  │            backfill_from, backfill_to, interval, table)
   │    │  │  │  │  │
   │    │  │  │  │  │  PHASE 2 — Incremental:
   │    │  │  │  │  │    if min_ts is None (empty DB):
   │    │  │  │  │  │      fetch_from = to_ts - lookback_seconds
   │    │  │  │  │  │    elif max_ts is not None:
   │    │  │  │  │  │      fetch_from = max(from_ts, max_ts + 60)
   │    │  │  │  │  │    else:
   │    │  │  │  │  │      fetch_from = from_ts
   │    │  │  │  │  │    if fetch_from < to_ts:
   │    │  │  │  │  │      _fetch_range(endpoint, symbol,
   │    │  │  │  │  │        fetch_from, to_ts, interval, table)
   │    │  │  │  │  │
   │    │  │  │  │  │  return (total_inserted, detail)
   │    │  │  │  │  │
   │    │  │  │  │  └──────────────────────────────────────
   │    │  │  │  │
   │    │  │  │  │  ┌── _fetch_range() INTERNALS:  [fetcher.py: l.225]
   │    │  │  │  │  │
   │    │  │  │  │  │  if fetch_from >= fetch_to → (OK, "up-to-date")
   │    │  │  │  │  │
   │    │  │  │  │  │  try:
   │    │  │  │  │  │    client.get_history(endpoint, symbol,
   │    │  │  │  │  │      fetch_from, fetch_to, interval)
   │    │  │  │  │  │      │
   │    │  │  │  │  │      │  ┌── client.py get_history()
   │    │  │  │  │  │      │  │  params = {
   │    │  │  │  │  │      │  │    "symbols": symbol,
   │    │  │  │  │  │      │  │    "interval": INTERVAL_PARAM[interval],
   │    │  │  │  │  │      │  │    "from": str(from_ts),
   │    │  │  │  │  │      │  │    "to": str(to_ts),
   │    │  │  │  │  │      │  │  }
   │    │  │  │  │  │      │  │  return _request(endpoint, params)
   │    │  │  │  │  │      │  │    │
   │    │  │  │  │  │      │  │    │  _wait_for_capacity()
   │    │  │  │  │  │      │  │    │  HTTP GET url
   │    │  │  │  │  │      │  │    │  _record_call()
   │    │  │  │  │  │      │  │    │
   │    │  │  │  │  │      │  │    │  if 429: sleep(Retry-After), retry once
   │    │  │  │  │  │      │  │    │  if 401: raise_for_status()
   │    │  │  │  │  │      │  │    │  if 400+: raise_for_status()
   │    │  │  │  │  │      │  │    │
   │    │  │  │  │  │      │  │    │  return resp.json()  (must be list)
   │    │  │  │  │  │      │  │    └── list[dict[str,Any]]
   │    │  │  │  │  │      │  └── return list[dict[str,Any]]
   │    │  │  │  │  │      │
   │    │  │  │  │  │      response = list[dict[str,Any]]
   │    │  │  │  │  │
   │    │  │  │  │  │  except httpx.HTTPStatusError:
   │    │  │  │  │  │    if 401 → raise FatalError
   │    │  │  │  │  │    else → return (ERROR, "status reason")
   │    │  │  │  │  │  except httpx.RequestError:
   │    │  │  │  │  │    return (ERROR, "Network error: ...")
   │    │  │  │  │  │  except Exception:
   │    │  │  │  │  │    return (ERROR, "Unexpected error: ...")
   │    │  │  │  │  │
   │    │  │  │  │  │  if empty response → (NODATA, "no data")
   │    │  │  │  │  │
   │    │  │  │  │  │  Map API response to DataFrame:
   │    │  │  │  │  │    Response format:
   │    │  │  │  │  │      [{"symbol": "X", "history": [{"t": ..., ...}, ...]}, ...]
   │    │  │  │  │  │    For each entry:
   │    │  │  │  │  │      For each bar in entry["history"]:
   │    │  │  │  │  │        row = {"symbol": symbol}
   │    │  │  │  │  │        For api_key, col_name in _FIELD_MAPS[endpoint]:
   │    │  │  │  │  │          if api_key in bar: row[col_name] = bar[api_key]
   │    │  │  │  │  │        rows.append(row)
   │    │  │  │  │  │    df = pd.DataFrame(rows, columns=ordered_cols)
   │    │  │  │  │  │    df = normalize_timestamps(df)  # ensure UNIX int
   │    │  │  │  │  │
   │    │  │  │  │  │  before = storage.count_rows(table, symbol)
   │    │  │  │  │  │  storage.upsert_dataframe(table, df)
   │    │  │  │  │  │  after = storage.count_rows(table, symbol)
   │    │  │  │  │  │
   │    │  │  │  │  │  return (inserted, "N new rows")
   │    │  │  │  │  │
   │    │  │  │  │  └──────────────────────────────────────
   │    │  │  │  │
   │    │  │  │  │  results[symbol][endpoint] = (code, detail)
   │    │  │  │  │
   │    │  │  │  └─────────────────────────────────────────
   │    │  │
   │    │  return results
   │    │
   │    └── results = {symbol: {endpoint: (code, detail)}}
   │
   ├── fetcher.format_summary(results,
   │     fetcher.spot_symbols, fetcher.perp_symbols) → str
   │    └── print(str)
   │
   ├── Check: any code == ERROR across all results?
   │    YES → sys.exit(1)
   │    NO  → sys.exit(0)
   │
   └── finally: fetcher.close()
                   └── client.close()
```

---

## Result Model

### 3-State Sentinel Codes

| Constant | Value | Meaning | Produced where | Consumed where |
|----------|-------|---------|----------------|----------------|
| `OK` | `0` | Success (up-to-date or 0 new rows) | `_fetch_range` (lines 243, 378), `fetch_one` (line 378) | `fetch_one` (line 359: if code < 0 → early return), `format_summary` (line 468-473), `cmd_fetch`/`cmd_loop` error check (line 69) |
| `ERROR` | `-1` | API/network failure | `_fetch_range` (lines 257, 261, 265) — catches `httpx.HTTPStatusError`, `httpx.RequestError`, generic `Exception` | Same as above |
| `NODATA` | `-2` | Empty API response | `_fetch_range` (lines 270, 293) — empty list or no rows after mapping | Same as above |
| `inserted` | `>0` | Actual inserted row count | `_fetch_range` (line 312) — `after - before` | `fetch_one` accumulates into `total_inserted` |

### How codes propagate

```
_fetch_range → (int, str)
    │
    ▼
fetch_one accumulates total_inserted
    │  if code < 0 → early return (code, detail)
    │  else → total_inserted += code
    ▼
fetch_cycle → dict[symbol][endpoint] = (code, detail)
    │
    ▼
format_summary display logic:
    code == ERROR → "❌"
    code == NODATA → "◦"
    code >= 0 → "✓" (including 0 = up-to-date)
    │
    ▼
cmd_fetch / cmd_loop exit logic:
    any code == ERROR → sys.exit(1)
    else → sys.exit(0)
```

---

## Rate Limiter Path

```
Client._request(endpoint, params)
  │
  ├── Client._wait_for_capacity()
  │     │
  │     ├── Remove timestamps older than now - RATE_WINDOW
  │     │     while call_times[0] < now - 60: call_times.popleft()
  │     │
  │     ├── if len(call_times) >= RATE_LIMIT (40):
  │     │     wait = call_times[0] + 60 - now
  │     │     if wait > 0:
  │     │       time.sleep(wait)
  │     │       _wait_for_capacity()  # recursive retry
  │     │
  │     └── return (capacity available)
  │
  ├── HTTP GET url
  │
  └── Client._record_call()
        call_times.append(time.time())
```

**Properties**:
- Sliding window (not fixed clock-aligned)
- Deque stores up to 40 timestamps
- Recursive on re-check (potential edge: deep recursion on very long stalls, but practically max 1-2 recursions)
- No threading concerns (single-threaded)

---

## 429 Retry Path

```
Client._request(endpoint, params)
  │
  ├── HTTP GET → status 429
  │
  ├── retry_after = resp.headers.get("Retry-After", "60")
  │     Try: float(retry_after)
  │     Catch ValueError: wait = 60.0
  │
  ├── logger.warning("429 rate limited, waiting %.1fs before retry", wait)
  │
  ├── time.sleep(wait)
  │
  ├── _wait_for_capacity()       # another rate-limit check before retry
  │
  ├── HTTP GET (retry)           # exactly ONE retry
  │
  │   NOTE: If the retry ALSO returns 429, it falls through to the
  │   400+ check and raises httpx.HTTPStatusError, which propagates
  │   up to _fetch_range → returns (ERROR, "429 Too Many Requests").
  │   Only the first 429 gets a retry.
  │
  └── _record_call()             # records the retry call
```

**Key detail**: The retry path does NOT loop — it's a single retry attempt. If the retry also 429s, `resp.raise_for_status()` at line 129 fires and the error propagates upward.

---

## 401 Abort Path

```
Client._request(endpoint, params)
  │
  ├── HTTP GET → status 401
  │
  ├── logger.error("401 Unauthorized — check COINALYZE_API_KEY")
  │
  └── resp.raise_for_status() → raises httpx.HTTPStatusError
        │
        ▼
Fetcher._fetch_range()
  │
  ├── except httpx.HTTPStatusError as exc:
  │     if status == 401:
  │       raise FatalError("Authentication failed (401)...") from exc
        │
        ▼
cmd_fetch() / cmd_loop()
  │
  ├── except FatalError as e:
  │     print(f"FATAL: {e}", file=sys.stderr)
  │     sys.exit(1)
  │
  └── finally: fetcher.close()
```

**Note**: The `_fetch_range` method only promotes 401 to `FatalError`. All other 4xx/5xx status codes return `(ERROR, detail)` and continue the cycle.

---

## Backfill vs Incremental Sync Logic

### Decision Tree in `fetch_one()` (lines 314-389)

```
storage.get_existing_range(table, symbol)
  → (min_ts, max_ts) or (None, None)

                    ┌─────────────────────────────────────┐
                    │        PHASE 1: BACKFILL            │
                    │                                     │
                    │  lookback_seconds > 0               │
                    │  AND min_ts is not None?            │
                    └─────────┬───────────────────────────┘
                              │
                    YES ──────┤
                              ▼
              backfill_target = to_ts - lookback_seconds
                              
              if min_ts > backfill_target:
                  backfill_from = backfill_target
                  backfill_to = min_ts - 60
                  
                  if backfill_from < backfill_to:
                      _fetch_range(backfill_from → backfill_to)
                      # This fills the gap between the lookback
                      # boundary and the oldest stored data
                              
                    ┌─────────────────────────────────────┐
                    │        PHASE 2: INCREMENTAL          │
                    │                                     │
                    │  Determine fetch_from:              │
                    └─────────┬───────────────────────────┘
                              │
              ┌───────────────┼──────────────────┐
              │               │                  │
              ▼               ▼                  ▼
        min_ts is None   max_ts is not None   else
        (empty DB)       (normal case)
              │               │                  │
              ▼               ▼                  ▼
     fetch_from =        fetch_from =        fetch_from =
     to_ts -              max(from_ts,        from_ts
     lookback_seconds     max_ts + 60)
              │               │                  │
              └───────────────┼──────────────────┘
                              │
                              ▼
                    if fetch_from >= to_ts:
                        return (OK, "up-to-date")
                              │
                              ▼
                    _fetch_range(fetch_from → to_ts)
```

### Visual timeline

```
Scenario A: Empty DB
─────────────────────────────────────────────────────────────
   ←──── lookback window ────→│
                               to (now)
                               │
   fetch_from                  to
   (to - lookback)             
   └───────── _fetch_range() ──┘

Scenario B: Partial data exists, no gap
─────────────────────────────────────────────────────────────
   │←─── existing data ───→│               │
   min_ts                  max_ts          to
                                           │
                                fetch_from = max(from_ts, max_ts+60)
                                           │
                                └── _fetch_range() ──┘

Scenario C: Gap between lookback window and oldest data
─────────────────────────────────────────────────────────────
   backfill_target            min_ts        max_ts          to
   (to - lookback)            │             │               │
   │                          │             │               │
   └── BACKFILL ──┘          └─ existing ──┘               │
                                                    ┌──────┘
                                                    │
                                              fetch_from = max(from_ts, max_ts+60)
                                                    │
                                              └─ INCREMENTAL ┘
```

---

## Exception Matrix

| Exception | Raised by | Caught by | Effect |
|-----------|-----------|-----------|--------|
| `FatalError` | `fetcher.py:_fetch_range` (on 401) | `cli.py:cmd_fetch`/`cmd_loop` | `sys.exit(1)` |
| `httpx.HTTPStatusError` | `client.py:_request` (400+, 401) | `fetcher.py:_fetch_range` | 401→FatalError; else→`(ERROR, detail)` |
| `httpx.RequestError` | `client.py:_request` (network failure) | `fetcher.py:_fetch_range` | `(ERROR, detail)` |
| `ValueError` | `client.py:_request` (unknown endpoint) | Not caught in `_fetch_range` → propagates | Unhandled → crashes that symbol |
| `ValueError` | `fetcher.py:load_symbols` (bad format) | `Fetcher.__init__` → `close()` + re-raise | Crashes init → caught by caller |
| `FileNotFoundError` | `fetcher.py:load_symbols` | Not caught | Crashes Fetcher init |
| `json.JSONDecodeError` | `fetcher.py:load_symbols` | Not caught | Crashes Fetcher init |
| `Exception` | `client.py:search_markets` (any) | Caught internally → `logger.warning` | Continues, returns partial results |
| `Exception` (generic) | `Fetcher.__init__` (any during init) | `__init__` → `close()` + re-raise | Crashes init |
| `Exception` (generic) | `fetcher.py:_fetch_range` (unexpected) | `_fetch_range` | `(ERROR, "Unexpected error: ...")` |

**Notable gap**: `ValueError` from `client.py:_request` (unknown endpoint) is NOT caught by `_fetch_range`'s generic `except Exception` because it's not wrapped — only `httpx.HTTPStatusError`, `httpx.RequestError`, and bare `Exception` are caught. If an invalid endpoint key were somehow passed, it would propagate unhandled. In practice this can't happen because `ENDPOINT_CONFIGS` only uses keys present in `Client.ENDPOINTS`.

---

## Interface Consistency Checks

### 1. `cli.py` ↔ `fetcher.py`

| Check | Status | Detail |
|-------|--------|--------|
| `cmd_fetch` calls `Fetcher(config)` | ✅ | `Fetcher.__init__` accepts `Config` dataclass |
| `cmd_fetch` calls `fetcher.fetch_cycle(lookback_seconds=int)` | ✅ | Signature: `fetch_cycle(self, lookback_seconds: int = 604800)` |
| `cmd_fetch` calls `fetcher.format_summary(results, spot, perp)` | ✅ | `@staticmethod format_summary(results: dict, spot_symbols: list[str], perp_symbols: list[str])` |
| `cmd_fetch` catches `FatalError` | ✅ | Imports and catches |
| `cmd_fetch` calls `fetcher.close()` in `finally` | ✅ | Guarded by `if fetcher is not None` |
| `cmd_loop` same patterns | ✅ | Same call structure as `cmd_fetch` |
| `cmd_show` calls `load_symbols(str)` | ✅ | `load_symbols(symbol_map_path: str)` returns 3-tuple |
| Constants imported correctly | ✅ | `ERROR`, `OK`, `FatalError`, `Fetcher`, `LOADBACK_DAYS_DEFAULT`, `LOADBACK_SECONDS_DEFAULT`, `SYMBOL_MAP_PATH`, `load_symbols` all imported |
| `--lookback` passed as days, multiplied by 86400 | ✅ | `args.lookback * 86400` → seconds |

### 2. `cli.py` ↔ `client.py`

| Check | Status | Detail |
|-------|--------|--------|
| `cmd_list_markets` creates `CoinalyzeClient(config.api_key)` | ✅ | `Client.__init__(api_key: str)` |
| `cmd_list_markets` calls `client.search_markets(query)` | ✅ | `search_markets(self, query: str) → list[dict]` |
| `cmd_list_markets` calls `client.close()` in `finally` | ✅ | Guarded |
| Return type consumed correctly | ✅ | Iterates over returned list, accesses `.get("symbol", "")`, etc. |

### 3. `fetcher.py` ↔ `client.py`

| Check | Status | Detail |
|-------|--------|--------|
| `Fetcher.__init__` creates `CoinalyzeClient(config.api_key)` | ✅ | `Client(api_key: str)` |
| `_fetch_range` calls `client.get_history(endpoint, symbol, fetch_from, fetch_to, interval)` | ✅ | `get_history(self, endpoint, symbol, from_ts, to_ts, interval=None)` |
| Argument types match | ✅ | All positional; `endpoint: str`, `symbol: str`, `from_ts: int`, `to_ts: int`, `interval: str` |
| Return type consumed correctly | ✅ | Returns `list[dict[str,Any]]`; iterated as `response` |
| Exception types handled | ✅ | `httpx.HTTPStatusError`, `httpx.RequestError` caught |

### 4. `fetcher.py` ↔ `storage.py`

| Check | Status | Detail |
|-------|--------|--------|
| `Fetcher.__init__` creates `Storage(config.db_path)` | ✅ | `Storage(db_path: str)` |
| `fetch_one` calls `storage.get_existing_range(table, symbol)` | ✅ | Returns `tuple[Optional[int], Optional[int]]` → destructured as `min_ts, max_ts` |
| `_fetch_range` calls `storage.upsert_dataframe(table, df)` | ✅ | `upsert_dataframe(self, table: str, df: pd.DataFrame) → int` |
| `_fetch_range` calls `storage.count_rows(table, symbol)` | ✅ | `count_rows(self, table: str, symbol: Optional[str] = None) → int` |
| `normalize_timestamps` imported and used | ✅ | Import: `from coinalyze_receiver.storage import Storage, normalize_timestamps` |

### 5. `fetcher.py` ↔ API Response Spec (Field Mappings)

The API returns: `[{"symbol": "...", "history": [{"t": ..., "o": ..., ...}]}]`

| Endpoint | API fields | Mapped columns | SQL table columns | Match? |
|----------|-----------|----------------|-------------------|--------|
| `ohlcv` | `t, o, h, l, c, v, bv, tx, btx` | `timestamp, open, high, low, close, volume, buyvolume, trades, buytrades` | same + `symbol` PK | ✅ |
| `open-interest` | `t, o, h, l, c` | `timestamp, open, high, low, close` | same + `symbol` PK | ✅ |
| `funding-rate` | `t, o, h, l, c` | `timestamp, open, high, low, close` | same + `symbol` PK | ✅ |
| `liquidation` | `t, l, s` | `timestamp, longvolume, shortvolume` | same + `symbol` PK | ✅ |
| `long-short-ratio` | `t, r, lp, sp` | `timestamp, ratio, longpct, shortpct` | same + `symbol` PK | ✅ |

All field mappings are consistent with the `{history: [...]}` nested response structure (parsed at fetcher.py lines 276-290).

### 6. `storage.py` ↔ SQLite Schema

| Table | Columns (from SCHEMA_SQL) | Columns inserted by upsert_dataframe | Match? |
|-------|--------------------------|---------------------------------------|--------|
| `ohlcv_bars` | symbol, timestamp, open, high, low, close, volume, buyvolume, trades, buytrades | same (via `_FIELD_MAPS["ohlcv"]` + "symbol") | ✅ |
| `open_interest` | symbol, timestamp, open, high, low, close | same (via `_FIELD_MAPS["open-interest"]` + "symbol") | ✅ |
| `liquidations` | symbol, timestamp, longvolume, shortvolume | same (via `_FIELD_MAPS["liquidation"]` + "symbol") | ✅ |
| `funding_rates` | symbol, timestamp, open, high, low, close | same (via `_FIELD_MAPS["funding-rate"]` + "symbol") | ✅ |
| `ls_ratios` | symbol, timestamp, ratio, longpct, shortpct | same (via `_FIELD_MAPS["long-short-ratio"]` + "symbol") | ✅ |

Table names in `ENDPOINT_CONFIGS` (fetcher.py) match table names in `SCHEMA_SQL` (storage.py):

| `ENDPOINT_CONFIGS` `table` | `SCHEMA_SQL` table name | Match? |
|---------------------------|------------------------|--------|
| `"ohlcv_bars"` | `ohlcv_bars` | ✅ |
| `"open_interest"` | `open_interest` | ✅ |
| `"funding_rates"` | `funding_rates` | ✅ |
| `"liquidations"` | `liquidations` | ✅ |
| `"ls_ratios"` | `ls_ratios` | ✅ |

PK constraint `(symbol, timestamp)` is consistent across all upsert operations (`ON CONFLICT(symbol, timestamp)` in `upsert_dataframe`).

### Overall Consistency Verdict

**All checked interface pairs are consistent.** No mismatches found in:
- Function signatures (argument names, types, order)
- Return types and their consumption
- Exception handling chains
- Column/field name mappings
- Table name references
- Symbol filtering logic (perp-only endpoints)

---

## Unused / Dead Code Notes

| Symbol | Location | Why dead |
|--------|----------|----------|
| `RateLimitExceeded` | `client.py:51` | Exception class defined but never raised anywhere |
| `ENDPOINT_TABLE_MAP` | `storage.py:80-86` | Dict mapping endpoint→table name; never referenced in any module. All table lookups use `ENDPOINT_CONFIGS` from `fetcher.py` |
| `setup_logging()` second param `default_level` | `cli.py:31` | Used, but every caller passes a literal; `cmd_show` and `cmd_list_markets` pass `logging.WARNING` while `cmd_fetch`/`cmd_loop` pass `logging.INFO` — functionally fine, just worth noting |

---

## Compile Verification

```bash
$ python -m compileall -q /home/weed420/coinalyze-receiver/src/coinalyze_receiver/
```

All modules compile without errors.
