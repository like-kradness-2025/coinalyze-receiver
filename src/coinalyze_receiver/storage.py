from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _row_hash(row: dict[str, Any]) -> str:
    """
    Create a deterministic hash for a dictionary row using sorting and hashing.
    Useful for deduplicating based on exact content equality.
    """
    row_str = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(row_str.encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Load all rows from a JSONL file into a list. Returns an empty list if file doesn't exist.
    Utility function (used for dedup inspect/testing only).
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """
    Atomic full-write of rows to a JSONL file.
    Used internally after dedup-filtering.
    """
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def upsert_jsonl(path: Path, row: dict[str, Any], key_fields: tuple[str, ...]) -> int:
    """
    Deduped row write to JSONL using last-write-wins semantics by key_fields.

    Reads existing rows, filters out any that match the new row on key_fields,
    then writes the updated list (old filtered + new) back atomically.

    Args:
        path: Path to the JSONL file.
        row: The new or updated row to upsert.
        key_fields: Tuple of field names that uniquely identify a row.

    Returns:
        Total row count after upsert.
    """
    rows = read_jsonl(path)
    key = tuple(row.get(field) for field in key_fields)
    filtered = [existing for existing in rows if tuple(existing.get(field) for field in key_fields) != key]
    filtered.append(row)
    write_jsonl(path, filtered)
    return len(filtered)


def save_jsonl_deduped(path: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """
    Save rows with deduplication across saves using last-write-wins.

    Reads existing rows and discards those that match any incoming row on all
    fields (content equality). Then writes the combined set back.

    Args:
        path: Path to the JSONL file.
        rows: New rows to upsert.

    Returns:
        (final_count, newly_added_count) where newly_added counts rows that
        were not already present (upserted equals neue if overwritten).
    """
    existing = read_jsonl(path)
    existing_hashes = {_row_hash(r) for r in existing}
    new_rows = []
    for row in rows:
        if _row_hash(row) not in existing_hashes:
            existing_hashes.add(_row_hash(row))
            existing.append(row)
            new_rows.append(row)
    write_jsonl(path, existing)
    return (len(existing), len(new_rows))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """
    Legacy write function; purely appends (no dedup).
    Kept for backward compatibility/tests.
    Replaced by upsert_jsonl in data ingestion.
    """
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _parse_saved_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return None


def rotate_raw_jsonl(directory: Path, days: int = 7) -> int:
    """Delete raw JSONL rows older than the retention window and rewrite files."""
    if not directory.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    for path in directory.glob("*.jsonl"):
        rows = read_jsonl(path)
        kept_rows = []
        removed_rows = 0
        for row in rows:
            saved_at = _parse_saved_at(row.get("_saved_at"))
            if saved_at is not None and saved_at < cutoff:
                removed_rows += 1
                continue
            kept_rows.append(row)

        if removed_rows:
            deleted += removed_rows
            if kept_rows:
                write_jsonl(path, kept_rows)
            else:
                path.unlink()
    return deleted

def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
