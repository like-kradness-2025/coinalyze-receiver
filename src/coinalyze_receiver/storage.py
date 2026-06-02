"""SQLite storage for coinalyze market data."""

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd


def normalize_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Convert timestamp column to UNIX int."""
    ts_dtype = str(df["timestamp"].dtype)
    if "datetime64" in ts_dtype:
        unit = ts_dtype.replace("datetime64[", "").rstrip("]")
        if unit == "s":
            df["timestamp"] = df["timestamp"].astype("int64")
        elif unit == "ns":
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9
        else:
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9
    elif df["timestamp"].dtype == "object":
        df["timestamp"] = pd.to_datetime(df["timestamp"]).astype("int64") // 10**9
    return df


SCHEMA_SQL = """
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
"""

# Map API endpoint names → table names
ENDPOINT_TABLE_MAP: dict[str, str] = {
    "ohlcv": "ohlcv_bars",
    "open-interest": "open_interest",
    "liquidation": "liquidations",
    "funding-rate": "funding_rates",
    "long-short-ratio": "ls_ratios",
}


class Storage:
    """SQLite-backed storage for Coinalyze market data."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5s on lock contention
        return conn

    def get_existing_range(
        self, table: str, symbol: str
    ) -> tuple[Optional[int], Optional[int]]:
        """Return (min_timestamp, max_timestamp) for symbol in table, or (None, None)."""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT MIN(timestamp), MAX(timestamp) FROM {table} WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        return row if row and row[0] else (None, None)

    def upsert_dataframe(self, table: str, df: pd.DataFrame) -> int:
        """Upsert rows from a DataFrame into the given table. Returns row count."""
        if df.empty:
            return 0

        cols = list(df.columns)
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        non_pk = [c for c in cols if c not in ("symbol", "timestamp")]
        update_set = ", ".join(f"{c}=excluded.{c}" for c in non_pk)

        rows = [tuple(row) for row in df.to_numpy()]
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(symbol, timestamp) DO UPDATE SET {update_set}"
        )

        with self._conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()
        return len(rows)

    def count_rows(self, table: str, symbol: Optional[str] = None) -> int:
        with self._conn() as conn:
            if symbol:
                return conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE symbol = ?", (symbol,)
                ).fetchone()[0]
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
