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

PVWATTS_ENDPOINT = "https://developer.nrel.gov/api/pvwatts/v8.json"
CACHE_TTL_HOURS = 8_760  # 1 year

# Standard 4kW residential system — fixed, not configurable
SYSTEM_CONFIG = {
    "system_capacity": 4.0,
    "module_type": 0,       # standard crystalline silicon
    "array_type": 1,        # fixed roof mount
    "losses": 14,        # system losses % — correct param name for PVWatts v8
    "tilt": 20,             # degrees
    "azimuth": 180,         # south-facing
    
}

MONTH_NAMES = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _pvwatts_get(params: dict) -> requests.Response:
    return requests.get(PVWATTS_ENDPOINT, params=params, timeout=15)


def get_output(lat: float, lon: float) -> dict:
    """
    Estimates annual and monthly solar output for a standard
    4kW residential system at the given U.S. coordinates
    using NREL PVWatts v8.

    U.S. locations only — analyst.py routes international
    requests elsewhere.

    Cache key: f"pvwatts_{lat:.2f}_{lon:.2f}"
    Cache TTL: 8,760 hours (1 year)

    Returns:
    {
        "annual_kwh": float,
        "monthly_kwh": [float x 12],  # Jan–Dec
        "capacity_factor_pct": float,
        "source": "NREL PVWatts v8",
        "system_kw": 4.0,
        "cache_status": "live" | "cached",
        "lat": float,
        "lon": float
    }
    """
    api_key = os.getenv("NREL_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("NREL_API_KEY not set in .env")
        return _error_response(lat, lon, "NREL_API_KEY not set in .env")

    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    cache_key = f"pvwatts_{lat_r}_{lon_r}"

    # Check cache first
    cached = cache_get(cache_key, max_age_hours=CACHE_TTL_HOURS)
    if cached:
        data = json.loads(cached)
        data["cache_status"] = "cached"
        return data

    # Build request params
    params = {
        "api_key": api_key,
        "lat": lat_r,
        "lon": lon_r,
        **SYSTEM_CONFIG,
    }

    try:
        resp = _pvwatts_get(params)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        LOGGER.error(
            "PVWatts request failed for (%s, %s): %s", lat, lon, exc
        )
        return _error_response(lat_r, lon_r, str(exc))

    # Check for API-level errors
    errors = payload.get("errors", [])
    if errors:
        LOGGER.error("PVWatts API errors for (%s, %s): %s", lat, lon, errors)
        return _error_response(lat_r, lon_r, str(errors))

    outputs = payload.get("outputs", {})
    if not outputs:
        LOGGER.error("PVWatts returned no outputs for (%s, %s)", lat, lon)
        return _error_response(lat_r, lon_r, "No outputs in response")

    # Annual output in kWh
    annual_kwh = outputs.get("ac_annual")
    if annual_kwh is None:
        return _error_response(lat_r, lon_r, "ac_annual missing from response")

    # Monthly output — PVWatts returns a list of 12 values
    monthly_raw = outputs.get("ac_monthly", [])
    if len(monthly_raw) != 12:
        LOGGER.warning(
            "PVWatts returned %d monthly values (expected 12) for (%s, %s)",
            len(monthly_raw), lat, lon
        )

    monthly_kwh = [round(float(v), 2) for v in monthly_raw]

    # Capacity factor: annual_kwh / (system_kw * 8760 hours)
    system_kw = SYSTEM_CONFIG["system_capacity"]
    capacity_factor = round(
        (float(annual_kwh) / (system_kw * 8_760)) * 100, 2
    )

    result = {
        "annual_kwh": round(float(annual_kwh), 2),
        "monthly_kwh": monthly_kwh,
        "capacity_factor_pct": capacity_factor,
        "source": "NREL PVWatts v8",
        "system_kw": system_kw,
        "cache_status": "live",
        "lat": lat_r,
        "lon": lon_r,
    }

    # Cache the result
    cache_set(cache_key, json.dumps(result))

    return result


def _error_response(lat: float, lon: float, error: str) -> dict:
    """Returns a consistent error structure when the API fails."""
    return {
        "annual_kwh": None,
        "monthly_kwh": [],
        "capacity_factor_pct": None,
        "source": "NREL PVWatts v8",
        "system_kw": SYSTEM_CONFIG["system_capacity"],
        "cache_status": "error",
        "lat": lat,
        "lon": lon,
        "error": error,
    }