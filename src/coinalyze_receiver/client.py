"""Coinalyze API client — raw httpx with rate limiting."""

import logging
import time
from collections import deque
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coinalyze.net/v1"

# Rate limit: 40 calls per 60 seconds (sliding window)
RATE_LIMIT = 40
RATE_WINDOW = 60  # seconds

# API endpoint paths
ENDPOINTS: dict[str, str] = {
    "ohlcv": "/ohlcv-history",
    "open-interest": "/open-interest-history",
    "funding-rate": "/funding-rate-history",
    "liquidation": "/liquidation-history",
    "long-short-ratio": "/long-short-ratio-history",
}

# Interval → API param mapping
INTERVAL_PARAM: dict[str, str] = {
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "30min": "30min",
    "1hour": "1hour",
    "2hour": "2hour",
    "4hour": "4hour",
    "6hour": "6hour",
    "12hour": "12hour",
    "daily": "daily",
}

# Per-endpoint default intervals
ENDPOINT_INTERVALS: dict[str, str] = {
    "ohlcv": "1min",
    "open-interest": "1min",
    "funding-rate": "1min",
    "liquidation": "1min",
    "long-short-ratio": "15min",
}


class RateLimitExceeded(Exception):
    """Rate limit reached — try again later."""


class Client:
    """Coinalyze API client with sliding-window rate limiting.

    Uses a plain httpx.Client (no httpx_retries) with a deque-based
    sliding window to enforce 40 calls/minute.
    """

    def __init__(self, api_key: str) -> None:
        self._http = httpx.Client(
            headers={"api_key": api_key},
            timeout=30.0,
        )
        # Sliding window: store timestamps of recent API calls
        self._call_times: deque[float] = deque()

    def close(self) -> None:
        self._http.close()

    def _wait_for_capacity(self) -> None:
        """Block until we have capacity under the rate limit."""
        now = time.time()
        # Remove timestamps outside the window
        while self._call_times and self._call_times[0] < now - RATE_WINDOW:
            self._call_times.popleft()

        if len(self._call_times) >= RATE_LIMIT:
            # Need to wait until oldest call falls out of the window
            wait = self._call_times[0] + RATE_WINDOW - now
            if wait > 0:
                logger.debug("Rate limit reached, sleeping %.1fs", wait)
                time.sleep(wait)
                # Re-check after waiting
                self._wait_for_capacity()

    def _record_call(self) -> None:
        self._call_times.append(time.time())

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Make a rate-limited GET request to the Coinalyze API."""
        path = ENDPOINTS.get(endpoint)
        if path is None:
            raise ValueError(f"Unknown endpoint: {endpoint}. Valid: {list(ENDPOINTS.keys())}")

        self._wait_for_capacity()
        url = f"{BASE_URL}{path}"

        logger.debug("HTTP GET %s params=%s", url, params)
        resp = self._http.get(url, params=params)
        self._record_call()

        if resp.status_code == 429:
            # Parse Retry-After (Coinalyze returns decimal seconds)
            retry_after = resp.headers.get("Retry-After", "60")
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 60.0
            logger.warning("429 rate limited, waiting %.1fs before retry", wait)
            time.sleep(wait)
            # Retry once after waiting
            self._wait_for_capacity()
            resp = self._http.get(url, params=params)
            self._record_call()

        if resp.status_code == 401:
            logger.error("401 Unauthorized — check COINALYZE_API_KEY")
            resp.raise_for_status()

        if resp.status_code >= 400:
            logger.error("HTTP %d for %s: %s", resp.status_code, url, resp.text[:200])
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Unexpected response format: %s", type(data))
            return []

        return data

    def get_history(
        self,
        endpoint: str,
        symbol: str,
        from_ts: int,
        to_ts: int,
        interval: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical data for one symbol.

        Args:
            endpoint: One of ENDPOINTS keys (ohlcv, open-interest, etc.)
            symbol: Coinalyze symbol (e.g. BTCUSDT_PERP.A)
            from_ts: Unix timestamp (seconds) — start of range
            to_ts: Unix timestamp (seconds) — end of range
            interval: API interval string (defaults to per-endpoint default)

        Returns:
            List of dicts from the API response.
        """
        if interval is None:
            interval = ENDPOINT_INTERVALS.get(endpoint, "1min")

        params = {
            "symbols": symbol,
            "interval": INTERVAL_PARAM[interval],
            "from": str(from_ts),
            "to": str(to_ts),
        }
        return self._request(endpoint, params)

    def search_markets(self, query: str) -> list[dict[str, Any]]:
        """Search future/spot markets by keyword."""
        results = []
        for market_type in ("future-markets", "spot-markets"):
            try:
                params = {} if market_type == "future-markets" else {}
                url = f"{BASE_URL}/{market_type}"
                self._wait_for_capacity()
                resp = self._http.get(url)
                self._record_call()
                if resp.status_code == 200:
                    for m in resp.json():
                        if query.upper() in m.get("symbol", "").upper() or query.upper() in m.get("base_asset", "").upper():
                            results.append(m)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", market_type, e)
        return results
