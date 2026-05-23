from __future__ import annotations

from datetime import datetime, timezone


def utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def parse_duration_seconds(value: str) -> int:
    text = value.strip().lower()
    if text.endswith("min"):
        return int(float(text[:-3]) * 60)
    if text.endswith("m"):
        return int(float(text[:-1]) * 60)
    if text.endswith("h"):
        return int(float(text[:-1]) * 3600)
    if text.endswith("d"):
        return int(float(text[:-1]) * 86400)
    return int(float(text))

def iso_from_ts(ts: int | float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
