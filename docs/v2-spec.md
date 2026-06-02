# coinalyze-receiver v2 Specification

This document defines the implementation contract for the v2 rewrite of `coinalyze-receiver`.
It is intended to be precise enough that an implementation engineer can build the system with minimal ambiguity.

## Scope

- Language: Python
- HTTP client: direct `httpx` usage
- Database: SQLite (`data/coinalyze_v2.db`)
- Runtime model: sequential fetches, 3-minute cycle
- Target data scope: 21 symbols, 5 data types
- Deployment modes:
  - Dev: manual command execution
  - Prod (Termux): `nohup` via `run_loop.sh`

---

## A. API Integration Spec

### A.1 Base URL and authentication

- Base URL: `https://api.coinalyze.net/v1`
- Authentication method: request header
  - Header name: `api_key`
  - Header value: the configured API key string
- Authentication must **not** use query parameters.
- The HTTP client must attach the `api_key` header to every request.

### A.2 API endpoint paths

The receiver uses the following history endpoints:

| Data type | Endpoint path | Interval | Notes |
|---|---|---:|---|
| OHLCV | `/ohlcv-history` | `1min` | Used for all 21 symbols |
| Open Interest | `/open-interest-history` | `1min` | Perp symbols only |
| Funding Rate | `/funding-rate-history` | `1min` | Perp symbols only |
| Liquidation | `/liquidation-history` | `1min` | Perp symbols only |
| Long/Short Ratio | `/long-short-ratio-history` | `15min` | Perp symbols only |

All requests are `GET` requests.

### A.3 Request parameters

Each endpoint accepts the following common parameters:

| Parameter | Type | Required | Meaning |
|---|---|---|---:|---|
| `symbols` | string | yes | Symbol identifier(s) expected by Coinalyze, usually a single symbol in this implementation |
| `from` | integer unix seconds | yes | **Inclusive** start timestamp, aligned to minute boundary (`floor(ts / 60) * 60`) |
| `to` | integer unix seconds | yes | **Exclusive** end timestamp (API returns bars with `t < to`), aligned to minute boundary |
| `interval` | string | yes | `1min` or `15min` depending on data type |

Implementation requirements:

- Requests are issued sequentially, one symbol/data-type combination at a time.
- For each fetch cycle, `to` should be the current UNIX timestamp at the time the request is built.
- For each cycle, the common base window is derived from `now - 3 minutes` and then aligned/floored to the minute boundary.
- `from` is derived per symbol and data type using incremental sync logic (see Section B).

### A.4 Rate limiting

#### A.4.1 Limit definition

- Hard limit: **40 calls per 60-second sliding window**
- The limiter must track request timestamps over a rolling 60-second window.
- The implementation must prevent issuing a new request if doing so would exceed the 40-call ceiling.

#### A.4.2 Enforcement rules

- Rate limiting is enforced in the HTTP client layer.
- The limiter applies to all API calls, regardless of endpoint.
- The fetcher does **not** rely on async concurrency for throughput; requests are sequential and therefore the limiter is a safety guard rather than a throughput mechanism.
- If the client receives a `429` response, the limiter is not considered a substitute for server-side throttling handling; retry logic is still required.

#### A.4.3 Retry-After handling

For `429 Too Many Requests`:

1. Read the `Retry-After` header if present.
2. Sleep for the specified delay.
3. Retry the request **once**.
4. If the retry also fails with `429`, treat the request as failed for that cycle.

If the `Retry-After` header is missing or invalid, the implementation should fall back to a conservative short delay (implementation-defined), but must still obey the one-retry rule.

### A.5 Response format

The API returns JSON arrays of objects.

Typical response shape:

```json
[
  {
    "t": 1710000000,
    "o": 123.4,
    "h": 125.0,
    "l": 122.8,
    "c": 124.1,
    "v": 4567.89,
    "bv": 1234.56,
    "tx": 789,
    "btx": 456,
    "s": "..."
  }
]
```

Important rules:

- An empty array (`[]`) is a valid and expected response for some windows and symbols.
- Empty response is classified as `NODATA`, not as an error.
- Response records may not contain every field; the parser must map available fields and tolerate missing optional ones.

### A.6 Field mapping to DB columns

The receiver persists raw API fields into normalized SQLite tables. Field mapping must follow the v1 schema conventions.

#### A.6.1 OHLCV mapping

| API field | DB column |
|---|---|
| `t` | `timestamp` |
| `o` | `open` |
| `h` | `high` |
| `l` | `low` |
| `c` | `close` |
| `v` | `volume` |
| `bv` | `buyvolume` |
| `tx` | `trades` |
| `btx` | `buytrades` |

#### A.6.2 Open Interest mapping

| API field | DB column |
|---|---|
| `t` | `timestamp` |
| `o` | `open` |
| `h` | `high` |
| `l` | `low` |
| `c` | `close` |

#### A.6.3 Funding Rate mapping

| API field | DB column |
|---|---|
| `t` | `timestamp` |
| `o` | `open` |
| `h` | `high` |
| `l` | `low` |
| `c` | `close` |

#### A.6.4 Liquidation mapping

| API field | DB column |
|---|---|
| `t` | `timestamp` |
| `l` | `longvolume` |
| `s` | `shortvolume` |

#### A.6.5 Long/Short Ratio mapping

| API field | DB column |
|---|---|
| `t` | `timestamp` |
| `r` | `ratio` |
| `lp` | `longpct` |
| `sp` | `shortpct` |

### A.7 Error handling

#### A.7.1 401 Unauthorized

- If the API returns `401`, the request must abort immediately.
- No retry is performed for `401`.
- The cycle should stop and surface an authentication/configuration failure.

#### A.7.2 429 Too Many Requests

- Handle using the `Retry-After` header if available.
- Retry exactly once after sleeping.
- If retry fails, mark the request as failed.
- Do not loop indefinitely on throttling.

#### A.7.3 5xx server errors

- For any 5xx response, retry once.
- If the retry fails again, surface failure and continue according to the current operation mode:
  - single `fetch`: end with failure result
  - `loop`: continue to the next cycle unless the failure is fatal for the entire process

#### A.7.4 Network and transport errors

- Connection failures, timeouts, TLS errors, and other transport exceptions are treated as network errors.
- In loop mode, network errors are not fatal to the process; they should be recorded and the next cycle should proceed.
- In single fetch mode, the command should return failure.

#### A.7.5 Non-retryable client errors

- Other 4xx responses are treated as hard failures unless explicitly handled.
- They should be surfaced clearly in logs and command output.

---

## B. Data Flow & Architecture

### B.1 Module structure

The v2 package uses exactly five runtime modules plus package metadata:

```text
src/coinalyze_receiver/
├── __init__.py
├── config.py
├── client.py
├── storage.py
├── fetcher.py
└── cli.py
```

#### B.1.1 `config.py`
Responsibilities:

- Load configuration from environment and/or defaults.
- Provide a configuration object containing at minimum:
  - `api_key`
  - `db_path`
  - `log_level`
- Keep configuration parsing simple and deterministic.
- Avoid coupling to business logic.

#### B.1.2 `client.py`
Responsibilities:

- Create and manage the `httpx` client.
- Attach authentication header.
- Enforce the 40 calls/min sliding-window limiter.
- Implement retry behavior for `429` and `5xx`.
- Return parsed JSON payloads or typed failure states.

#### B.1.3 `storage.py`
Responsibilities:

- Own the SQLite connection and schema initialization.
- Persist incoming records with UPSERT semantics.
- Provide range and lookup queries used by CLI/display workflows.
- Keep database operations isolated from HTTP concerns.

#### B.1.4 `fetcher.py`
Responsibilities:

- Coordinate the full fetch cycle across all symbols and data types.
- Decide which endpoints apply to each symbol type.
- Compute `from` timestamps using incremental synchronization rules.
- Convert API payloads into storage-ready records.
- Aggregate per-task results into a cycle summary.

#### B.1.5 `cli.py`
Responsibilities:

- Expose the command-line interface.
- Parse subcommands and arguments.
- Dispatch to fetcher/storage operations.
- Provide human-readable summaries and listings.

### B.2 Data scope

The implementation operates on 21 symbols from the external symbol map:

- **Source path**: `~/.hermes/data/coinalyze/coinalyze-btc-selected-20-symbol-market-map.json`
- **Format**: JSON array of objects, each with `symbol`, `market_type` (`"spot"`/`"future"`), `exchange_code`, `exchange_name`, `market_name`.
- **Loading rules**:
  - File must exist and be valid JSON array.
  - Each entry must have `symbol` and `market_type` keys.
  - Exactly 21 entries expected (validated at load time).
  - Spot symbols: OHLCV only. Perp symbols: all 5 data types.
- **Failure behavior**: if file is missing, malformed, or has wrong entry count → print error and abort.

Symbol composition:

Per-symbol coverage:

- Spot symbols: OHLCV only
- Perp symbols: all 5 data types

### B.3 Fetch cycle design

#### B.3.1 Cycle interval

- The receiver runs on a **3-minute cycle**.
- A cycle is defined as one complete sequential pass over the configured symbol/data-type matrix.
- The cycle is short enough to keep data fresh while remaining comfortably below the API rate limit.

#### B.3.2 Sequential fetch

- Fetching must be sequential, not async/parallel.
- The order of requests is deterministic.
- Sequential execution is required to simplify rate-limit behavior and database write ordering.

#### B.3.3 Common `from` window

- Each cycle defines a shared base window:
  - `common_from = floor_to_minute(now - 3 minutes)`
- All symbol requests in the cycle derive from the same common base time.
- This prevents symbol-to-symbol skew caused by different request start times.

#### B.3.4 Incremental sync logic

For each symbol and data type, the final request start time is:

```text
fetch_from = max(common_from, last_ts + 60)
```

Where:

- `common_from` is the cycle-wide floor of `now - 3 minutes`
- `last_ts` is the most recently stored timestamp for that symbol/data type in the database
- `+ 60` advances by one minute to avoid overlapping the last stored bar

Rules:

- If no prior data exists, use `common_from`.
- If existing data is newer than `common_from`, start from `last_ts + 60`.
- This logic must be applied independently per symbol/data-type table.

### B.4 Storage design

#### B.4.1 Database file

- SQLite database file: `data/coinalyze_v2.db`
- The file is separate from v1 and must not overwrite v1 data.

#### B.4.2 Tables

The SQLite schema contains exactly **five market-data tables**, matching the retained v1 storage model (v1 modules `receiver.py` and `selected20.py` are deleted from v2):

1. `ohlcv_bars`
2. `open_interest`
3. `liquidations`
4. `funding_rates`
5. `ls_ratios`

Schema rules:

- Each table uses `(symbol, timestamp)` as the composite primary key.
- There is no additional symbol-metadata table in SQLite for v2; the symbol map is sourced from the external JSON market map.
- The schema must remain compatible with the existing v1 table structure and UPSERT behavior.

#### B.4.3 UPSERT semantics

- Inserts must be idempotent via `INSERT ... ON CONFLICT(symbol, timestamp) DO UPDATE SET ...`.
- The composite primary key is `(symbol, timestamp)` for all tables — no additional identity fields.
- On conflict, existing rows must be updated with the latest values rather than duplicated.
- Re-fetching overlapping windows must not create duplicates.

#### B.4.4 SQLite operational behavior

- Use WAL mode if available.
- Use parameterized statements for all writes.
- Commit per batch or per symbol/data-type unit as appropriate for reliability.
- Database schema creation must be safe to run repeatedly.

### B.5 CLI commands

The CLI must expose the following subcommands:

#### B.5.1 `fetch`

- Executes one complete fetch cycle.
- Prints a summary of successes, no-data cases, and failures.
- Exits after one cycle.

#### B.5.2 `loop`

- Runs indefinitely in 3-minute cycles.
- Performs graceful shutdown on signal.
- Emits progress and cycle summaries.

#### B.5.3 `show`

- Prints the symbol list from the external JSON market map.
- Source path: `~/.hermes/data/coinalyze/coinalyze-btc-selected-20-symbol-market-map.json`.
- Output: tabular format with columns Symbol, Type (spot/perp), Exchange, Market Name.
- Sorted by the JSON array order (same as fetch order).
- On missing or malformed file: print error and exit with code 1.
- This command does **not** call the Coinalyze API — it reads the local JSON file only.

#### B.5.4 `list-markets [keyword]`

- Queries the Coinalyze **future-markets** and **spot-markets** endpoints (`/v1/future-markets`, `/v1/spot-markets`).
- Uses the same `api_key` header auth and respects the shared rate limiter.
- Response: JSON array of market objects. Filters to entries whose `symbol` or `base_asset` contains the keyword (case-insensitive). If no keyword, prints all markets (capped at 50).
- Output: tabular format with columns Symbol, Exchange, Base Asset, Perpetual? (✓/ ), OHLCV? (✓/ ), LS Ratio? (✓/ ).
- This is a read-only diagnostic command — does not write to DB.

#### B.5.5 `search <keyword>`

- Alias for `list-markets`.
- Must behave identically to `list-markets` with the same keyword.

### B.6 Result-state model

Fetch results are classified into three states:

| State | Code | Meaning |
|---|---:|---|
| data | `n >= 0` | Rows stored successfully |
| no_data | `n == -2` | API returned an empty array; expected gap |
| error | `n == -1` | HTTP error, network error, or other failure |

This result model must be used consistently by fetcher and CLI summary output.

#### B.6.1 CLI summary aggregation rules

Per-symbol reporting shows the most severe state:
- If any data-type for a symbol is `error`, the symbol is `❌ failed`
- If all data-types are `no_data`, the symbol is `◦ no-data`
- Otherwise the symbol is `✓ ok`

Per-type aggregation:
```
ohlcv               :       41 new rows  ◦ 3 no-data  ❌ 1 errors
open_interest       :       26 new rows  ✅
```

Exit codes:
- `fetch`: exit 0 if all requests succeeded; exit 1 if any single request failed.
- `loop`: never exits on individual request failures; only exits on signal or fatal condition (401, uncaught exception).

---

## C. Operations Design

### C.1 Loop design

#### C.1.1 Start-time-based cycle scheduling

- The loop must be scheduled using the cycle start time, not by sleeping a fixed duration after the fetch completes.
- After each cycle, compute the next target start time as the previous start time plus 180 seconds.
- Sleep only for the difference between `next_start` and `now`.
- If the fetch overruns the scheduled window, begin the next cycle immediately without negative sleep.

This design keeps cycle cadence stable and prevents drift.

#### C.1.2 Signal handling

The loop must handle:

- `SIGINT`
- `SIGTERM`

Behavior:

- On signal, set a shutdown flag.
- Allow the **current in-flight single API request** to complete, but **do not start new requests**.
- Once the in-flight request finishes (or times out), flush and close storage resources.
- Exit with code 0 on clean shutdown; exit with code 1 if shutdown is caused by an uncaught exception.

### C.2 Error recovery rules

#### C.2.1 429 handling in operations

Operational sequence for `429`:

1. Read `Retry-After`.
2. Sleep that duration.
3. Retry once.
4. If the retry fails again, fail the request/cycle.

No second retry is allowed.

#### C.2.2 401 handling in operations

- `401` is a fatal authentication problem.
- Abort immediately.
- Do not continue to later symbols or later cycles.

#### C.2.3 Network failure handling in operations

- Network and transport failures should not permanently stop the long-running loop.
- A failed request or cycle due to network issues should be logged.
- The loop should continue with the next cycle.

#### C.2.4 5xx handling in operations

- Retry once for 5xx responses.
- If the retry fails, mark the request as failed.
- In loop mode, continue to the next cycle unless the application state is otherwise unrecoverable.

### C.3 No-data handling

- Empty JSON response (`[]`) must be treated as `NODATA`.
- `NODATA` is not a failure.
- `NODATA` should be counted and reported separately from errors.
- The system must not log empty responses as exceptions unless there is an accompanying protocol or parsing issue.

### C.4 Test acceptance criteria

The implementation is acceptable only if the following conditions are met:

1. **API correctness**
   - Requests use the correct base URL and header auth.
   - Each endpoint path and interval match the spec.

2. **Rate limit correctness**
   - The client never exceeds 40 calls in any 60-second sliding window under normal execution.
   - `429` is handled with `Retry-After` and exactly one retry.

3. **Fetch correctness**
   - The system fetches all 21 symbols with the correct data-type coverage.
   - Spot symbols receive OHLCV only.
   - Perp symbols receive all 5 data types.

4. **Incremental sync correctness**
   - `from` is derived as `max(common_from, last_ts + 60)`.
   - Re-running fetches does not duplicate rows.

5. **Storage correctness**
   - SQLite tables are created successfully.
   - UPSERT behavior preserves data integrity on overlapping windows.

6. **CLI correctness**
   - `fetch`, `loop`, `show`, `list-markets`, and `search` all function as specified.
   - `search` behaves as an alias of `list-markets`.

7. **Operations correctness**
   - The loop uses start-time-based 3-minute cadence.
   - `SIGINT`/`SIGTERM` trigger graceful shutdown.
   - Empty responses are classified as `NODATA`.

8. **Deployment correctness**
   - Development can be run manually.
   - Termux production uses `nohup` with `run_loop.sh`.

### C.5 Deployment design

#### C.5.1 Development mode

- Development and testing are performed manually.
- The primary entry point is the CLI.
- Recommended invocation pattern:
  - `python -m coinalyze_receiver.cli fetch`
  - `python -m coinalyze_receiver.cli loop`

#### C.5.2 Production mode on Termux

- Production runtime is `nohup`-based.
- A wrapper script `run_loop.sh` is used to start the loop.
- `nohup` is preferred because Termux does not provide systemd and tmux has been unreliable in this environment.
- Logs should be captured to a stable file location.

### C.6 Implementation notes and invariants

- The system must keep v2 storage isolated from v1.
- All request timing decisions should be based on UNIX seconds.
- Minute-resolution data must be aligned to minute boundaries before persistence decisions are made.
- The architecture should remain simple and sequential to reduce failure modes.
- The CLI should always return actionable summaries for each run.

---

## Appendix: Intended behavior summary

- One cycle = one sequential pass through all required symbol/data-type fetches.
- `common_from = now - 3 minutes`, floored to the minute.
- Per symbol/data type: `fetch_from = max(common_from, last_ts + 60)`.
- API auth uses `api_key` header.
- Rate limit = 40 calls/min sliding window.
- `401` aborts.
- `429` uses `Retry-After`, then one retry.
- `5xx` gets one retry.
- Empty response is `NODATA`.
- Persistence uses SQLite and UPSERTs.
- Dev = manual; Termux prod = `nohup` + `run_loop.sh`.

---

## D. Implementation Details

### D.1 Project Root Structure

```text
coinalyze-receiver/
├── pyproject.toml          # deps: httpx>=0.27, pandas>=2.0
├── src/coinalyze_receiver/
│   ├── __init__.py         # __version__ = "0.2.0"
│   ├── config.py           # Config dataclass
│   ├── client.py           # CoinalyzeClient httpx wrapper
│   ├── storage.py          # SQLite storage
│   ├── fetcher.py          # Fetch orchestration
│   └── cli.py              # CLI entry point
├── data/                   # coinalyze_v2.db created here
├── scripts/
│   └── run_loop.sh         # nohup wrapper for Termux
├── runtime/                # pids/, logs/ for loop operation
├── tests/                  # pytest tests
└── docs/
    ├── v2-spec.md          # this document
    └── v2-spec-review.md   # review results
```

### D.2 client.py API (already exists, document it)

Class `CoinalyzeClient`:

```python
class CoinalyzeClient:
    def __init__(self, api_key: str) -> None:
        # Creates httpx.Client with {"api_key": api_key} header
        # Initializes sliding window rate limiter (deque)

    def close(self) -> None:
        # Closes httpx.Client

    def get_history(
        self,
        endpoint: str,
        symbol: str,
        from_ts: int,
        to_ts: int,
        interval: str = "1min",
    ) -> list[dict[str, Any]]:
        # Returns parsed JSON list from API
        # Raises httpx.HTTPStatusError on 4xx/5xx after retries
        # Returns [] on empty response (NODATA)

    def search_markets(self, query: str) -> list[dict[str, Any]]:
        # Queries /v1/future-markets and /v1/spot-markets
        # Returns filtered list
```

### D.3 storage.py (to be written)

```python
class Storage:
    def __init__(self, db_path: str) -> None:
        # Creates DB dir if needed, connects, WAL mode, creates tables

    def get_existing_range(self, table: str, symbol: str) -> tuple[int | None, int | None]:
        # Returns (min_ts, max_ts) or (None, None)

    def upsert_dataframe(self, table: str, df: pd.DataFrame) -> int:
        # Converts df to list of tuples, INSERT ... ON CONFLICT DO UPDATE
        # Returns number of rows passed (not actual inserts)

    def count_rows(self, table: str, symbol: str | None = None) -> int:
        # Returns row count
```

#### SQL Schema (5 tables)

```sql
CREATE TABLE IF NOT EXISTS ohlcv_bars (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    buyvolume   REAL,
    trades      INTEGER,
    buytrades   INTEGER,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS open_interest (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS liquidations (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    longvolume  REAL,
    shortvolume REAL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS funding_rates (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS ls_ratios (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    ratio       REAL,
    longpct     REAL,
    shortpct    REAL,
    PRIMARY KEY (symbol, timestamp)
);
```

### D.4 fetcher.py (to be written)

```python
class Fetcher:
    def __init__(self, config: Config) -> None:
        # Loads symbol map, creates CoinalyzeClient and Storage
        # Separates spot/perp symbols

    def fetch_one(
        self,
        endpoint: str,
        symbol: str,
        from_ts: int,
        to_ts: int,
        interval: str,
        table: str,
    ) -> int:
        # Returns: n >= 0 (rows), -1 (error), -2 (NODATA)

    def fetch_cycle(self, from_ts: int, to_ts: int) -> dict[str, dict[str, int]]:
        # Orchestrates all symbols × all applicable data types
        # Returns {symbol: {endpoint: result}}

    def build_timestamps(self) -> tuple[int, int]:
        # Returns (common_from, to) = (floor((now-180)/60)*60, floor(now/60)*60)

    def summary(self, results: dict) -> str:
        # Formats the cycle summary output

    def close(self) -> None:
        # Closes client
```

### D.5 cli.py (to be written)

Function `main()`:
- argparse with subcommands: fetch, loop, show, list-markets, search
- `fetch`: one cycle, print summary, exit
- `loop`: infinite 3-min cycle with signal handler (SIGINT/SIGTERM)
- `show`: read symbol map, print table
- `list-markets [keyword]`: call client.search_markets(), print results
- `search <keyword>`: alias for list-markets

### D.6 run_loop.sh

```bash
#!/usr/bin/env bash
# Termux: shebang = #!/data/data/com.termux/files/usr/bin/bash
# Linux: shebang = #!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p runtime/logs runtime/pids
PID_FILE="runtime/pids/v2.pid"
LOG_FILE="runtime/logs/v2.log"

echo $$ > "$PID_FILE"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
log "=== coinalyze-receiver v2 loop started (PID: $$) ==="

while true; do
    log "--- cycle start ---"
    python3 -m coinalyze_receiver.cli fetch 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}
    if [ "$EXIT_CODE" -eq 1 ]; then
        log "--- cycle ended with errors (exit $EXIT_CODE) ---"
    else
        log "--- cycle OK (exit $EXIT_CODE) ---"
    fi
    sleep 180
done
```

### D.7 Error code reference

| Code | Meaning | Where |
|------|---------|-------|
| 0 | success | fetch exit |
| 1 | any request failed | fetch exit |
| -1 | error (4xx/5xx/network) | per-request result |
| -2 | NODATA (empty response) | per-request result |
