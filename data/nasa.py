from __future__ import annotations

import logging
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from data.db import cache_get, cache_set

LOGGER = logging.getLogger(__name__)

NASA_ENDPOINT = "https://power.larc.nasa.gov/api/temporal/climatology/point"
CACHE_TTL_HOURS = 8_760  # 1 year — climatology doesn't change

MONTH_NAMES = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _nasa_get(params: dict) -> requests.Response:
    return requests.get(NASA_ENDPOINT, params=params, timeout=15)


def get_irradiance(lat: float, lon: float) -> dict:
    """
    Fetches annual and monthly average solar irradiance (GHI)
    for any lat/lon globally using NASA POWER climatology.

    No API key required.
    Cache TTL: 8,760 hours (1 year).

    Returns:
    {
        "annual_avg_kwh_m2_day": float,
        "monthly_avg": {
            "JAN": float, ..., "DEC": float
        },
        "source": "NASA POWER",
        "parameter": "ALLSKY_SFC_SW_DWN",
        "cache_status": "live" | "cached",
        "lat": float,
        "lon": float
    }
    """
    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    cache_key = f"nasa_irradiance_{lat_r}_{lon_r}"

    # Check cache first
    cached = cache_get(cache_key, max_age_hours=CACHE_TTL_HOURS)
    if cached:
        import json
        data = json.loads(cached)
        data["cache_status"] = "cached"
        return data

    # Live API call
    params = {
        "latitude": lat_r,
        "longitude": lon_r,
        "community": "RE",
        "parameters": "ALLSKY_SFC_SW_DWN",
        "format": "JSON",
        "header": "true",
    }

    try:
        resp = _nasa_get(params)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        LOGGER.error("NASA POWER request failed for (%s, %s): %s", lat, lon, exc)
        return _error_response(lat_r, lon_r, str(exc))

    # Parse response
    try:
        monthly_raw = (
            payload
            .get("properties", {})
            .get("parameter", {})
            .get("ALLSKY_SFC_SW_DWN", {})
        )
    except (AttributeError, KeyError) as exc:
        LOGGER.error("Unexpected NASA POWER response structure: %s", exc)
        return _error_response(lat_r, lon_r, "Unexpected response structure")

    if not monthly_raw:
        LOGGER.error("NASA POWER returned empty data for (%s, %s)", lat, lon)
        return _error_response(lat_r, lon_r, "Empty response from NASA POWER")

    # Extract monthly values — NASA returns keys JAN, FEB, ..., DEC, ANN
    # Filter out fill values (-999) and the annual key
    monthly_avg: dict[str, float] = {}
    valid_values: list[float] = []

    for month in MONTH_NAMES:
        val = monthly_raw.get(month)
        if val is not None and float(val) > -990:
            monthly_avg[month] = round(float(val), 3)
            valid_values.append(float(val))
        else:
            monthly_avg[month] = None

    # Use NASA's own annual average if available, else compute from months
    ann_val = monthly_raw.get("ANN")
    if ann_val is not None and float(ann_val) > -990:
        annual_avg = round(float(ann_val), 3)
    elif valid_values:
        annual_avg = round(sum(valid_values) / len(valid_values), 3)
    else:
        LOGGER.error("All NASA POWER values are fill values for (%s, %s)", lat, lon)
        return _error_response(lat_r, lon_r, "All values are fill values")

    result = {
        "annual_avg_kwh_m2_day": annual_avg,
        "monthly_avg": monthly_avg,
        "source": "NASA POWER",
        "parameter": "ALLSKY_SFC_SW_DWN",
        "cache_status": "live",
        "lat": lat_r,
        "lon": lon_r,
    }

    # Cache the result
    import json
    cache_set(cache_key, json.dumps(result))

    return result


def _error_response(lat: float, lon: float, error: str) -> dict:
    """Returns a consistent error structure when the API fails."""
    return {
        "annual_avg_kwh_m2_day": None,
        "monthly_avg": {m: None for m in MONTH_NAMES},
        "source": "NASA POWER",
        "parameter": "ALLSKY_SFC_SW_DWN",
        "cache_status": "error",
        "lat": lat,
        "lon": lon,
        "error": error,
    }