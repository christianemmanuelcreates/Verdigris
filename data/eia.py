from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from data.db import cache_get, cache_set

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

CACHE_TTL_HOURS = 720  # 30 days — rates update monthly


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _eia_get(endpoint: str, params: dict) -> requests.Response:
    return requests.get(endpoint, params=params, timeout=15)


def get_rates(state_abbr: str) -> dict:
    """
    Fetches the most recent retail electricity rates for a U.S. state.
    Returns residential, commercial rates and comparison to national average.

    Historical rate trends come from the warehouse (eia_rates table).
    This connector fetches current rates only — the most recent 3 months.

    Cache key: f"eia_rates_{state_abbr}"
    Cache TTL: 720 hours (30 days)

    Returns:
    {
        "state": str,
        "residential_cents_kwh": float | None,
        "commercial_cents_kwh": float | None,
        "period": str,                  # most recent period e.g. "2025-02"
        "national_avg_residential": float | None,
        "vs_national_pct": float | None,
        "source": "EIA",
        "cache_status": "live" | "cached"
    }
    """
    api_key = os.getenv("EIA_API_KEY", "").strip()
    base_url = os.getenv("EIA_BASE_URL", "https://api.eia.gov/v2").rstrip("/")

    if not api_key:
        LOGGER.error("EIA_API_KEY not set in .env")
        return _error_response(state_abbr, "EIA_API_KEY not set in .env")

    state = state_abbr.upper().strip()
    cache_key = f"eia_rates_{state}"

    # Check cache first
    cached = cache_get(cache_key, max_age_hours=CACHE_TTL_HOURS)
    if cached:
        data = json.loads(cached)
        data["cache_status"] = "cached"
        return data

    endpoint = f"{base_url}/electricity/retail-sales/data"

    # Fetch state residential rate
    res_rate, period = _fetch_rate(endpoint, api_key, state, "RES")

    # Fetch state commercial rate
    com_rate, _ = _fetch_rate(endpoint, api_key, state, "COM")

    # Fetch national average residential rate
    nat_avg, _ = _fetch_rate(endpoint, api_key, "US", "RES")

    # Calculate delta vs national average
    vs_national = None
    if res_rate is not None and nat_avg is not None and nat_avg > 0:
        vs_national = round(((res_rate - nat_avg) / nat_avg) * 100, 2)

    result = {
        "state": state,
        "residential_cents_kwh": res_rate,
        "commercial_cents_kwh": com_rate,
        "period": period,
        "national_avg_residential": nat_avg,
        "vs_national_pct": vs_national,
        "source": "EIA",
        "cache_status": "live",
    }

    cache_set(cache_key, json.dumps(result))
    return result


def _fetch_rate(
    endpoint: str,
    api_key: str,
    state: str,
    sector: str,
) -> tuple[float | None, str | None]:
    """
    Fetches the most recent rate for a state and sector.
    Returns (rate_cents_kwh, period) or (None, None) on failure.
    """
    params = {
        "api_key": api_key,
        "frequency": "monthly",
        "data[0]": "price",
        "facets[stateid][]": state,
        "facets[sectorid][]": sector,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": 3,  # most recent 3 months only
    }

    try:
        resp = _eia_get(endpoint, params)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        LOGGER.error(
            "EIA request failed for %s/%s: %s", state, sector, exc
        )
        return None, None

    rows = payload.get("response", {}).get("data", [])
    if not rows:
        LOGGER.warning("EIA returned no data for %s/%s", state, sector)
        return None, None

    # Take the most recent non-null value
    for row in rows:
        price = row.get("price")
        period = str(row.get("period", ""))
        if price is not None:
            try:
                return round(float(price), 3), period
            except (ValueError, TypeError):
                continue

    return None, None


def _error_response(state: str, error: str) -> dict:
    """Returns a consistent error structure."""
    return {
        "state": state,
        "residential_cents_kwh": None,
        "commercial_cents_kwh": None,
        "period": None,
        "national_avg_residential": None,
        "vs_national_pct": None,
        "source": "EIA",
        "cache_status": "error",
        "error": error,
    }