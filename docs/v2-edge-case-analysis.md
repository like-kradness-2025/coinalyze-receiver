# Coinalyze-Receiver v2 — Edge Case Analysis

**Date:** 2026-06-02  
**Analyzed by:** debugger profile agent  
**Sources:** config.py, client.py, fetcher.py, storage.py, cli.py (5 modules, ~1,209 LOC)  
**DB:** data/coinalyze_v2.db (SQLite WAL mode, 5 tables)  
**API:** Coinalyze v1 (40 calls/min, `api_key` header auth)

---

## 1. Startup Conditions

### 1.1 Symbol map JSON is missing (FileNotFoundError)

**What happens:**  
`load_symbols(str(SYMBOL_MAP_PATH))` opens the file via `open(symbol_map_path)`. If the file doesn't exist, `FileNotFoundError` is raised inside `Fetcher.__init__`. The init's `except Exception: self.close(); raise` catches it, calls `self.close()` (no-op since `self.client` is still `None`), and re-raises. In `cmd_fetch`, this exception falls through the `try/except FatalError` block into the `finally` (no-op since `fetcher` is `None`), then propagates out of `cmd_fetch` → `main()` → raw traceback to the user.

**Correct or bug?** ❌ **Bug (usability).**  
The user sees an unsightly Python traceback instead of a friendly message.

**Fix:** Wrap `Fetcher(config)` in `cmd_fetch` and `cmd_loop` with a broader `except Exception` that prints a human-readable error and calls `sys.exit(1)`.

---

### 1.2 Symbol map has wrong entry count (<21 or >21)

**What happens:**  
`load_symbols` checks `len(data) != 21` and raises `ValueError("Symbol map must have exactly 21 entries, got N")`. Propagation path is identical to 1.1 — raw traceback.

**Correct or bug?** ❌ **Bug (usability).** Same fix as 1.1 applies.

**Fix:** Same as 1.1 — catch non-`FatalError` exceptions in CLI commands and print a friendly message.

---

### 1.3 Symbol map has duplicate symbols

**What happens:**  
`load_symbols` checks `if symbol in seen` and raises `ValueError(f"Duplicate symbol in market map: {symbol}")`. Same propagation — raw traceback.

**Correct or bug?** ❌ **Bug (usability).** Same issue — no user-friendly error.

**Fix:** Same as 1.1.

---

### 1.4 COINALYZE_API_KEY is empty

**What happens:**  
`Config.from_env()` sets `api_key = os.getenv("COINALYZE_API_KEY", "")`. `Config.validate()` returns `["COINALYZE_API_KEY is required"]`. `main()` checks `if args.command in ("fetch", "loop", "list-markets", "search")`, calls `config.validate()`, and if errors exist, prints `ERROR: COINALYZE_API_KEY is required` and exits with `sys.exit(1)`. The `show` command does NOT validate the API key (correct — it doesn't call the API).

**Correct or bug?** ✅ **Correct.**

---

### 1.5 First run with empty DB

**What happens:**  
`get_existing_range()` returns `(None, None)` because `row = (None, None)` and `row and row[0]` evaluates to `True and False = False` → the fallback `(None, None)` is returned. In `fetch_one()`, `min_ts is None` triggers the empty-DB path: `fetch_from = to_ts - lookback_seconds`. Full backfill is performed.

**Correct or bug?** ✅ **Correct.** The empty-DB detection is sound.

---

## 2. Runtime API Errors

### 2.1 API returns 401 on first call — traced through to cli.py exit?

**What happens:**  
1. `client._request()`: `resp.status_code == 401` → `logger.error("401 Unauthorized — check COINALYZE_API_KEY")` → `resp.raise_for_status()` raises `httpx.HTTPStatusError`.  
2. `fetcher._fetch_range()` catches `httpx.HTTPStatusError`, checks `status == 401`, and raises `FatalError("Authentication failed (401): check COINALYZE_API_KEY")`.  
3. `cmd_fetch` catches `FatalError`, prints `FATAL: Authentication failed (401): check COINALYZE_API_KEY`, calls `sys.exit(1)`.  
4. `finally` block closes the fetcher (which exists because `Fetcher.__init__` completed).  

**Correct or bug?** ✅ **Correct.** Full chain is properly traced and handled.

---

### 2.2 API returns 429, Retry-After header is MISSING — what default?

**What happens:**  
`resp.headers.get("Retry-After", "60")` defaults to `"60"`. If parsing as float fails, the `except ValueError` fallback also defaults to `60.0`. After sleeping 60s, the request is retried once.

**Correct or bug?** ✅ **Correct.** 60s is a reasonable default for rate-limit backoff.

---

### 2.3 API returns 429, retry ALSO returns 429 — what happens?

**What happens:**  
After the first 429, the code sleeps for `Retry-After` seconds (default 60), calls `_wait_for_capacity` again, then retries. If the retry ALSO returns 429, the 429-specific code has already been executed and is skipped (it's not in a loop). The code falls through to `if resp.status_code >= 400:` → logs the error → `resp.raise_for_status()` raises `httpx.HTTPStatusError`. In `_fetch_range`, `status` is 429 (not 401), so no `FatalError` — just `return (ERROR, "429 Too Many Requests")`. The cycle continues to the next symbol.

**Correct or bug?** ✅ **Correct.** One retry is sufficient for transient rate limits. A persistent 429 correctly becomes an ERROR sentinel.

---

### 2.4 API returns 500, retry also returns 500 — what happens?

**What happens:**  
500 is not 401 or 429, so it falls directly to `if resp.status_code >= 400:` → `resp.raise_for_status()` raises `httpx.HTTPStatusError`. No retry occurs. In `_fetch_range`, returns `(ERROR, "500 Internal Server Error")`.

**Correct or bug?** ✅ **Correct.** Server-side errors are not retried (avoiding thundering herd). The error is reported and the cycle continues.

---

### 2.5 API returns non-JSON response

**What happens:**  
`resp.json()` at `client.py:131` raises `json.JSONDecodeError`. This propagates to `_fetch_range()`, caught by `except Exception as exc:` → `return (ERROR, "Unexpected error: ...")`.

**Correct or bug?** ✅ **Correct.** Gracefully handled — returns ERROR without crashing.

---

### 2.6 API returns unexpected response format (not `{symbol, history}`)

**What happens:**  
`resp.json()` returns a list (so `isinstance(data, list)` passes). In `_fetch_range()`, the code iterates over the list and for each entry calls `entry.get("history", [])`. If entries don't have `"history"` keys, `bar_list` is `[]`, the `continue` skips them, and `rows` ends up empty. Returns `(NODATA, "no data")`.

**Correct or bug?** ⚠️ **Minor issue.** The behavior is safe (no crash, returns NODATA), but there is no warning logged when entries are silently skipped. A format change by the API could go undetected.

**Fix:** Add a debug-level log when entries are skipped due to missing `"history"` key.

---

### 2.7 API returns JSON array of empty objects `[{}, {}, {}]`

**What happens:**  
Each `{}` passes `isinstance(entry, dict)` → `entry.get("history", [])` returns `[]` → `continue`. `rows` stays empty → returns `(NODATA, "no data")`.

**Correct or bug?** ✅ **Correct.** Gracefully handled.

---

## 3. Data Anomalies

### 3.1 One symbol returns data, next symbol returns 429 — does the cycle continue?

**What happens:**  
`fetch_cycle()` iterates through all symbols via nested loops. Each `fetch_one()` call accumulates results in a dict. A 429 (returning ERROR) for one symbol does not break the loop — processing continues to the next symbol/endpoint.

**Correct or bug?** ✅ **Correct.** The cycle is resilient to individual symbol failures.

---

### 3.2 All symbols return NODATA — summary output?

**What happens:**  
`format_summary()` handles NODATA gracefully: per-symbol lines show `◦ {ep} (no data)`, per-type totals show `◦ {count} no-data`, per-symbol status shows `◦ {sym}` when all endpoints are NODATA.

**Correct or bug?** ✅ **Correct.**

---

### 3.3 Liquidation API returns `{"t":..., "l":..., "s":...}` but field map expects `lv`/`sv`

**What happens:**  
The field map `_FIELD_MAPS["liquidation"]` is:
```python
{
    "t": "timestamp",
    "l": "longvolume",
    "s": "shortvolume",
}
```
This correctly maps the API fields `l` → `longvolume` and `s` → `shortvolume`. The issue description mentions "this was already fixed" — indeed the current code has the correct mapping.

**Correct or bug?** ✅ **Correct.** The fix was applied. No `lv`/`sv` in the field map.

---

### 3.4 Symbol has data in DB, then symbol removed from symbol map

**What happens:**  
The symbol map JSON file is replaced with a new 21-entry set excluding the old symbol. `load_symbols` returns only the new symbols. Old data remains in the DB (no cleanup). `fetch_cycle` does not fetch the removed symbol. `format_summary` only shows symbols from the current symbol map, so the removed symbol doesn't appear in output. The DB continues to grow with orphan data.

**Correct or bug?** ✅ **Correct.** There is no requirement to purge stale data. Orphan rows cause no functional issues (they sit unused). If the user wants to reclaim space, they can run `VACUUM` or manually delete.

---

## 4. Resource Lifecycle

### 4.1 Fetcher.__init__ fails mid-way — is close() called?

**What happens:**  
`self.client` and `self.storage` are initialized to `None` at the top of `__init__`. The `try` block proceeds in order: `load_symbols` → `CoinalyzeClient` → `Storage`. If `load_symbols` fails, `self.client` is still `None`; `self.close()` (which checks `if self.client is not None`) is a no-op. If `CoinalyzeClient` fails, `self.client` was never assigned (Python assignment only completes on success), so `self.close()` is a no-op. If `Storage` fails, `self.client` was set, and `self.close()` properly closes the HTTP client.

**Correct or bug?** ✅ **Correct.** Proper sentinel pattern with `None` initialization guarantees safe partial cleanup.

---

### 4.2 KeyboardInterrupt during fetch — resources cleaned up?

**What happens:**  
`KeyboardInterrupt` inherits from `BaseException`, NOT `Exception`. So `Fetcher.__init__`'s `except Exception` does NOT catch it — the init fails in a partially constructed state. However, in `cmd_fetch`, `KeyboardInterrupt` during `Fetcher(config)` means `fetcher` is still `None` (assignment never completed), so the `finally: if fetcher is not None: fetcher.close()` is a no-op. Once `cmd_fetch` propagates `KeyboardInterrupt` upward, Python's GC handles any open file handles.

If `KeyboardInterrupt` happens during `fetch_cycle()` (after construction), the `try: fetcher = Fetcher(config); ... finally:` ensures `fetcher.close()` is called. `KeyboardInterrupt` IS caught by the `finally` block (which always runs on exception exit from the `try`).

**Correct or bug?** ✅ **Acceptable.** Signal delivery during `__init__` is vanishingly rare. During `fetch_cycle`, cleanup is guaranteed by `finally`.

---

### 4.3 Storage.__init__ succeeds but client creation fails

**What happens:**  
If `CoinalyzeClient(config.api_key)` raises, `self.client` is still `None`. `self.storage` was not yet assigned (we never got past the client creation line). `self.close()` does nothing. No leak — the Storage object hasn't been created yet.

Wait — re-checking the code order:
```python
self.client = CoinalyzeClient(config.api_key)
self.storage = Storage(config.db_path)
```
If `CoinalyzeClient` fails, `self.storage` is still `None` (the line never executed). `close()` is a no-op. ✓

**Correct or bug?** ✅ **Correct.** No resource leak.

---

### 4.4 DB file is on a read-only filesystem

**What happens:**  
`Storage.__init__` calls `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` which raises `PermissionError` if the parent directory is read-only. Even if `mkdir` succeeds (dir writable but file read-only), `_init_schema()` calls `conn.executescript(SCHEMA_SQL)` which tries to CREATE TABLE on a read-only database — raises `sqlite3.OperationalError: attempt to write a readonly database`. This propagates through `Fetcher.__init__` (caught by `except Exception`, `self.close()`, re-raised) to `cmd_fetch`, which gives a raw traceback.

**Correct or bug?** ❌ **Bug (usability).** A read-only filesystem is a common deployment mistake. The user gets a raw traceback instead of a clear error.

**Fix:** Catch `PermissionError`/`sqlite3.OperationalError` in `Storage.__init__` and wrap it in a friendlier message, or catch it in the CLI handlers.

---

## 5. CLI Edge Cases

### 5.1 `fetch` with --lookback 0 — no backfill, incremental only?

**What happens:**  
`args.lookback * 86400 = 0`. `lookback_seconds=0` flows through to `fetch_one()`. The conditions `lookback_seconds > 0 and min_ts is not None` (backfill) and `lookback_seconds > 0 and min_ts is None` (empty-DB full fetch) are both False because `0 > 0` is False. So execution falls to `elif max_ts is not None: fetch_from = max(from_ts, max_ts + 60)` or `else: fetch_from = from_ts`. The system fetches only the latest 3-minute window (from `common_from` to `to`).

**Correct or bug?** ✅ **Correct.** `--lookback 0` means "no historical backfill, incremental only."

---

### 5.2 `loop` with SIGTERM during backfill phase — clean shutdown?

**What happens:**  
A custom `SIGTERM` handler sets `shutdown_flag[0] = True` but does NOT interrupt running code. The backfill/fetch completes normally. After the current `fetch_cycle()` returns, the loop checks `shutdown_flag[0]` at line 118 (after the finally block) and at line 102 (loop condition). The `finally` block ensures `fetcher.close()` is called before the loop exits.

**Correct or bug?** ✅ **Correct.** Clean shutdown with no resource leaks. The signal handler is also non-reentrant-safe (uses a simple list as a mutable flag), which is fine for CPython's GIL.

---

### 5.3 `show` on a fresh clone with no symbol map — graceful error?

**What happens:**  
`cmd_show` checks `if not map_path.exists(): print("Error: symbol map not found at {map_path}"); sys.exit(1)` **before** attempting to load. No API calls are made.

**Correct or bug?** ✅ **Correct.** Graceful error with a clear message.

---

### 5.4 `search` with empty API key — caught by validate() before API call?

**What happens:**  
`main()` includes `"search"` in the validation set at line 289: `if args.command in ("fetch", "loop", "list-markets", "search")`. If the key is empty, `config.validate()` returns an error, it's printed, and `sys.exit(1)` is called before dispatch to `cmd_list_markets`.

**Correct or bug?** ✅ **Correct.** The API call is never made with an empty key.

---

### 5.5 What if `cmd_fetch` calls `sys.exit(1)` before `finally` block runs?

**What happens:**  
`sys.exit(1)` raises `SystemExit`. Python's exception handling semantics guarantee that `finally` clauses execute even when `SystemExit` is raised within the `try` block. So `fetcher.close()` IS called.

**Correct or bug?** ✅ **Correct.** `finally` always runs on the way out, even for `sys.exit()`.

---

## 6. Concurrency / Overlap

### 6.1 Two `fetch` processes run simultaneously — DB locked?

**What happens:**  
`Storage._conn()` sets `PRAGMA journal_mode=WAL`. SQLite WAL mode supports concurrent readers + one writer. Two processes reading simultaneously works fine. Two processes writing simultaneously: one succeeds, the other gets `SQLITE_BUSY`. The code does NOT handle `SQLITE_BUSY` retries. If `upsert_dataframe` or `count_rows` hits `SQLITE_BUSY`, a `sqlite3.OperationalError` propagates up as an unhandled exception → traceback.

Additionally, `count_rows` is called before and after `upsert_dataframe` to compute "inserted" count. If another process inserts concurrently, the diff is wrong (cosmetic issue only).

**Correct or bug?** ❌ **Bug (resilience).** Concurrent writes can cause hard failures. The count-diff issue is cosmetic but the `SQLITE_BUSY` crash is a real problem.

**Fix:** Add a retry loop (e.g., 3 retries with exponential backoff) in `Storage._conn()` or `upsert_dataframe` for `SQLITE_BUSY`. Alternatively, use a file-lock (e.g., `fcntl.flock` or `portalocker`) to serialize accesses.

---

### 6.2 Backfill range overlaps with incremental range — duplicate rows?

**What happens:**  
`upsert_dataframe` uses `INSERT INTO {table} (...) VALUES (...) ON CONFLICT(symbol, timestamp) DO UPDATE SET ...`. If backfill and incremental ranges overlap, the conflicting PK rows are silently updated (same values, essentially a no-op).

**Correct or bug?** ✅ **Correct.** UPSERT guarantees idempotency.

---

### 6.3 Cycle sleep of 180s is hardcoded — too short if 429 retries take >3min?

**What happens:**  
If a cycle takes >180s (e.g., many 429 retries adding 60s+ each), `cmd_loop` detects the overrun via:
```python
elapsed = time.time() - cycle_start
sleep_time = max(0, next_start - time.time())
if sleep_time > 0:
    time.sleep(sleep_time)
else:
    overrun = elapsed - CYCLE_SECONDS
    logger.warning("Cycle overran by %.1fs, starting next immediately", overrun)
```
The next cycle starts immediately. There is no drift accumulation.

If overruns are persistent (always >180s), the system never catches up, and average API call rate may exceed 40/min if the data window also grows. However, `_wait_for_capacity()` enforces the 40/min limit regardless of cycle duration.

**Correct or bug?** ⚠️ **Design limitation, not a bug.** The system correctly handles overruns and prevents rate-limit violations. Persistent overruns indicate the data set is too large for the 3-minute window, which is a capacity planning concern, not a code defect.

---

## Summary of Bugs Found

| # | Category | Edge Case | Severity | Fix |
|---|----------|-----------|----------|-----|
| 1 | Startup | Missing symbol map → raw traceback | Medium | Catch non-`FatalError` exceptions in `cmd_fetch`/`cmd_loop` |
| 2 | Startup | Wrong symbol map entry count → raw traceback | Medium | Same as #1 |
| 3 | Startup | Duplicate symbols in map → raw traceback | Medium | Same as #1 |
| 4 | Resource | Read-only filesystem → raw traceback | Low | Catch `PermissionError`/`OperationalError` in CLI |
| 5 | Concurrency | `SQLITE_BUSY` on concurrent writes → crash | Medium | Add retry loop for `SQLITE_BUSY` in storage layer |
| 6 | Concurrency | Concurrent `count_rows` diff skew | Low | (Cosmetic; attribute counting to approximate) |

**Non-bugs (design notes):**

| # | Item | Rationale |
|---|------|-----------|
| 7 | Empty API key validation excludes `show` | Intentionally correct — `show` doesn't need API access |
| 8 | 429 double-retry hard-fails as ERROR | One retry is enough; persistent 429 should abort that symbol |
| 9 | Unexpected API response format → NODATA | Graceful by default; could add debug logging |
| 10 | Overlapping backfill/incremental ranges | UPSERT guarantees idempotency |
| 11 | Cycle overrun → immediate restart | No drift; rate limiting is separately enforced |
| 12 | Liquidation field map uses `l`/`s` not `lv`/`sv` | Already fixed per the spec |
| 13 | Orphan data when symbols are removed | No functional impact; user can clean manually |
