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

CENSUS_ENDPOINT = "https://api.census.gov/data/2023/acs/acs5"
CACHE_TTL_HOURS = 8_760  # 1 year — ACS updates annually

# ACS variables we fetch
VARIABLES = {
    "B01003_001E": "population",
    "B25001_001E": "housing_units",
    "B19013_001E": "median_income",
}

# State area in square miles — used to calculate population density
# Source: U.S. Census Bureau
STATE_AREA_SQ_MI = {
    "AL": 50645, "AK": 571951, "AZ": 113594, "AR": 52035,
    "CA": 155779, "CO": 103642, "CT": 4842,  "DE": 1949,
    "FL": 53625,  "GA": 57513,  "HI": 6423,  "ID": 82643,
    "IL": 55519,  "IN": 35826,  "IA": 55857, "KS": 81759,
    "KY": 39486,  "LA": 43204,  "ME": 30843, "MD": 9707,
    "MA": 7800,   "MI": 56804,  "MN": 79627, "MS": 46923,
    "MO": 68742,  "MT": 145546, "NE": 76824, "NV": 109781,
    "NH": 8953,   "NJ": 7354,   "NM": 121298,"NY": 47126,
    "NC": 48618,  "ND": 68976,  "OH": 40861, "OK": 68595,
    "OR": 95988,  "PA": 44743,  "RI": 1034,  "SC": 30061,
    "SD": 75811,  "TN": 41235,  "TX": 261232,"UT": 82170,
    "VT": 9217,   "VA": 39490,  "WA": 66456, "WV": 24038,
    "WI": 54158,  "WY": 97093,  "DC": 61,
}

# Census suppression value — replace with None
SUPPRESSED = -666666666


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _census_get(params: dict) -> requests.Response:
    return requests.get(CENSUS_ENDPOINT, params=params, timeout=15)


def get_demographics(identifier: str) -> dict:
    """
    Fetches population, housing units, and median income
    for a U.S. state (FIPS code) or ZIP code.

    identifier: 2-digit state FIPS (e.g. "06") or
                5-digit ZIP code (e.g. "90210")

    Cache key: f"census_{identifier}"
    Cache TTL: 8,760 hours (1 year)

    Returns:
    {
        "identifier": str,
        "type": "state" | "zip",
        "population": int | None,
        "housing_units": int | None,
        "median_income": int | None,
        "area_sq_mi": float | None,
        "density_per_sq_mi": float | None,
        "state_abbr": str | None,
        "source": "U.S. Census ACS 5-Year 2019-2023",
        "cache_status": "live" | "cached"
    }
    """
    api_key = os.getenv("CENSUS_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("CENSUS_API_KEY not set in .env")
        return _error_response(identifier, "CENSUS_API_KEY not set in .env")

    identifier = identifier.strip().zfill(
        5 if len(identifier.strip()) > 2 else 2
    )
    cache_key = f"census_{identifier}"

    # Check cache first
    cached = cache_get(cache_key, max_age_hours=CACHE_TTL_HOURS)
    if cached:
        data = json.loads(cached)
        data["cache_status"] = "cached"
        return data

    # Determine if state FIPS or ZIP
    is_zip = len(identifier) == 5 and identifier.isdigit()
    is_state = len(identifier) == 2

    if is_zip:
        result = _fetch_zip(identifier, api_key)
    elif is_state:
        result = _fetch_state(identifier, api_key)
    else:
        return _error_response(
            identifier,
            f"Unrecognised identifier format: {identifier!r}. "
            "Expected 2-digit state FIPS or 5-digit ZIP."
        )

    if "error" in result:
        return result

    # Cache the result
    cache_set(cache_key, json.dumps(result))
    return result


def _fetch_state(fips: str, api_key: str) -> dict:
    """Fetch ACS data for a state by FIPS code."""
    var_str = ",".join(VARIABLES.keys())
    params = {
        "get": var_str,
        "for": f"state:{fips}",
        "key": api_key,
    }

    payload = _call_census(params, f"state FIPS {fips}")
    if payload is None:
        return _error_response(fips, f"Census API returned no data for state {fips}")

    row = _parse_row(payload)
    if row is None:
        return _error_response(fips, f"Could not parse Census response for state {fips}")

    population = _safe_int(row.get("B01003_001E"))
    housing_units = _safe_int(row.get("B25001_001E"))
    median_income = _safe_int(row.get("B19013_001E"))

    # Look up state abbreviation from FIPS
    state_abbr = _fips_to_abbr(fips)
    area = STATE_AREA_SQ_MI.get(state_abbr) if state_abbr else None
    density = (
        round(population / area, 2)
        if population and area and area > 0
        else None
    )

    return {
        "identifier": fips,
        "type": "state",
        "population": population,
        "housing_units": housing_units,
        "median_income": median_income,
        "area_sq_mi": float(area) if area else None,
        "density_per_sq_mi": density,
        "state_abbr": state_abbr,
        "source": "U.S. Census ACS 5-Year 2019-2023",
        "cache_status": "live",
    }


def _fetch_zip(zip_code: str, api_key: str) -> dict:
    """Fetch ACS data for a ZIP code tabulation area (ZCTA)."""
    var_str = ",".join(VARIABLES.keys())
    params = {
        "get": var_str,
        "for": f"zip code tabulation area:{zip_code}",
        "key": api_key,
    }

    payload = _call_census(params, f"ZIP {zip_code}")
    if payload is None:
        return _error_response(
            zip_code,
            f"Census API returned no data for ZIP {zip_code}. "
            "Not all ZIPs have ACS coverage."
        )

    row = _parse_row(payload)
    if row is None:
        return _error_response(
            zip_code,
            f"Could not parse Census response for ZIP {zip_code}"
        )

    population = _safe_int(row.get("B01003_001E"))
    housing_units = _safe_int(row.get("B25001_001E"))
    median_income = _safe_int(row.get("B19013_001E"))

    return {
        "identifier": zip_code,
        "type": "zip",
        "population": population,
        "housing_units": housing_units,
        "median_income": median_income,
        "area_sq_mi": None,       # ZIP area not available from this endpoint
        "density_per_sq_mi": None,
        "state_abbr": None,
        "source": "U.S. Census ACS 5-Year 2019-2023",
        "cache_status": "live",
    }


def _call_census(params: dict, label: str) -> list | None:
    """Makes the Census API call. Returns parsed JSON or None."""
    try:
        resp = _census_get(params)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        LOGGER.error("Census API HTTP error for %s: %s", label, exc)
        return None
    except requests.RequestException as exc:
        LOGGER.error("Census API request failed for %s: %s", label, exc)
        return None
    except (ValueError, KeyError) as exc:
        LOGGER.error("Census API response parse error for %s: %s", label, exc)
        return None


def _parse_row(payload: list) -> dict | None:
    """
    Census API returns a list where [0] is headers and [1] is data.
    Maps headers to values and returns as a dict.
    """
    if not payload or len(payload) < 2:
        return None
    headers = payload[0]
    data = payload[1]
    if len(headers) != len(data):
        return None
    return dict(zip(headers, data))


def _safe_int(value) -> int | None:
    """Convert Census value to int, handling suppression and None."""
    if value is None:
        return None
    try:
        v = int(value)
        return None if v == SUPPRESSED else v
    except (ValueError, TypeError):
        return None


def _fips_to_abbr(fips: str) -> str | None:
    """Convert 2-digit state FIPS to abbreviation."""
    fips_map = {
        "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
        "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
        "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
        "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
        "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
        "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
        "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
        "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
        "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
        "56": "WY",
    }
    return fips_map.get(fips.zfill(2))


def _error_response(identifier: str, error: str) -> dict:
    """Returns a consistent error structure."""
    return {
        "identifier": identifier,
        "type": None,
        "population": None,
        "housing_units": None,
        "median_income": None,
        "area_sq_mi": None,
        "density_per_sq_mi": None,
        "state_abbr": None,
        "source": "U.S. Census ACS 5-Year 2019-2023",
        "cache_status": "error",
        "error": error,
    }