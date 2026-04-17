from __future__ import annotations

import json
import logging
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from data.db import cache_get, cache_set

LOGGER = logging.getLogger(__name__)

CACHE_TTL_HOURS = 4_380  # 6 months — Eurostat publishes bi-annually

# Eurostat Statistics API — no API key required, fully public
# Dataset: nrg_pc_204 — Electricity prices for household consumers
# Band DC: 2500–5000 kWh/year — closest to standard residential
import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
_EUROSTAT_BASE = os.getenv(
    "EUROSTAT_BASE_URL",
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
).rstrip("/")
EUROSTAT_ENDPOINT = f"{_EUROSTAT_BASE}/nrg_pc_204"

# EU/EEA countries covered by Eurostat nrg_pc_204
# These get live data from the API — no static fallback needed
EUROSTAT_COUNTRIES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES",
    "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    # EEA non-EU
    "NO", "IS",
}

# Eurostat uses EL for Greece (not GR)
EUROSTAT_GEO_MAP = {
    "GR": "EL",
}

# EUR to USD cents conversion — 1 EUR = ~108 USD cents (2024 average)
EUR_TO_USD_CENTS = 108.0

# Verified static reference rates for non-Eurostat countries
# Units: USD cents per kWh (residential, all taxes included)
# Sources: IEA, Africa Data Hub, GlobalPetrolPrices, national regulators
# Last verified: Q1 2025
STATIC_RATES: dict[str, float] = {
    "AU": 32.0,   # Australia — AEMC national average 2024
    "JP": 26.0,   # Japan — national average 2024
    "KR": 12.0,   # South Korea — KEPCO regulated rate
    "CA": 12.0,   # Canada — national average incl. hydro provinces
    "BR": 15.0,   # Brazil — ANEEL average 2024
    "IN": 8.0,    # India — regulated, heavily subsidized
    "CN": 8.0,    # China — regulated residential 2024
    "ZA": 19.0,   # South Africa — Eskom 2024
    "NG": 1.4,    # Nigeria — NERC regulated (heavily subsidized)
    "KE": 26.0,   # Kenya — KPLC 2024 (among highest in Africa)
    "GH": 15.0,   # Ghana — ECG 2024
    "TZ": 8.0,    # Tanzania — TANESCO 2024
    "UG": 16.0,   # Uganda — UMEME 2024
    "ET": 0.3,    # Ethiopia — EEP (world's cheapest, hydro-based)
    "EG": 1.9,    # Egypt — heavily subsidized
    "MA": 8.0,    # Morocco — ONEE 2024
    "SA": 5.0,    # Saudi Arabia — highly subsidized
    "TH": 12.0,   # Thailand — MEA/PEA average 2024
    "VN": 8.0,    # Vietnam — EVN regulated 2024
    "PH": 20.0,   # Philippines — Meralco 2024
    "ID": 10.0,   # Indonesia — PLN regulated 2024
    "PK": 12.0,   # Pakistan — NEPRA 2024
    "BD": 9.0,    # Bangladesh — BPDB 2024
    "CL": 20.0,   # Chile — CNE average 2024
    "CO": 17.0,   # Colombia — XM average 2024
    "PE": 16.0,   # Peru — OSINERGMIN 2024
    "UY": 22.0,   # Uruguay — UTE 2024
    "MX": 10.0,   # Mexico — CFE subsidized rate 2024
    "TR": 10.0,   # Turkey — EPDK 2024
    "GB": 30.0,   # UK — Ofgem price cap H2 2024
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _eurostat_get(params: dict) -> requests.Response:
    return requests.get(EUROSTAT_ENDPOINT, params=params, timeout=15)


def get_intl_rate(iso2: str) -> dict:
    """
    Returns residential electricity rate for an international country.

    Routing:
    - EU/EEA countries → Eurostat nrg_pc_204 API (live, no key needed)
    - All other countries → verified static reference table
    - Unknown countries → unavailable response

    Cache key: f"intl_rate_{iso2}"
    Cache TTL: 4,380 hours (6 months)

    Returns:
    {
        "iso2": str,
        "rate_cents_kwh": float | None,
        "currency": "USD",
        "source": str,
        "period": str,
        "method": "eurostat" | "static_reference" | "unavailable",
        "cache_status": "live" | "cached"
    }
    """
    iso2 = iso2.upper().strip()
    cache_key = f"intl_rate_{iso2}"

    # Check cache first
    cached = cache_get(cache_key, max_age_hours=CACHE_TTL_HOURS)
    if cached:
        data = json.loads(cached)
        data["cache_status"] = "cached"
        return data

    # Route to correct source
    if iso2 in EUROSTAT_COUNTRIES or iso2 in EUROSTAT_GEO_MAP:
        result = _fetch_eurostat(iso2)
    elif iso2 in STATIC_RATES:
        result = _static_rate(iso2)
    else:
        result = _unavailable(iso2)

    # Cache if we got a real rate
    if result.get("rate_cents_kwh") is not None:
        cache_set(cache_key, json.dumps(result))

    return result


def _fetch_eurostat(iso2: str) -> dict:
    """
    Fetches residential electricity rate from Eurostat Statistics API.
    No API key required.
    Returns rate converted to USD cents/kWh.
    Falls back to static rate if API fails and static rate exists.
    """
    geo_code = EUROSTAT_GEO_MAP.get(iso2, iso2)

    params = {
        "lang": "EN",
        "geo": geo_code,
        "nrg_cons": "KWH2500-4999",  # standard residential band
        "tax": "I_TAX",              # including all taxes
        "currency": "EUR",
        "unit": "KWH",
        "sinceTimePeriod": "2023-S1",  # last 2 years of data
    }

    try:
        resp = _eurostat_get(params)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        LOGGER.error("Eurostat API failed for %s: %s", iso2, exc)
        if iso2 in STATIC_RATES:
            LOGGER.info("Falling back to static rate for %s", iso2)
            return _static_rate(iso2)
        return _unavailable(iso2)

    rate, period = _parse_jsonstat(payload)

    if rate is None:
        LOGGER.warning("No data in Eurostat response for %s", iso2)
        if iso2 in STATIC_RATES:
            return _static_rate(iso2)
        return _unavailable(iso2)

    # Convert EUR/kWh → USD cents/kWh
    rate_cents = round(rate * EUR_TO_USD_CENTS, 2)

    return {
        "iso2": iso2,
        "rate_cents_kwh": rate_cents,
        "currency": "USD",
        "source": "Eurostat nrg_pc_204 (household, band DC, incl. taxes)",
        "period": period or "most recent",
        "method": "eurostat",
        "cache_status": "live",
    }


def _parse_jsonstat(payload: dict) -> tuple[float | None, str | None]:
    """
    Parses Eurostat JSON-stat format.
    Returns (rate_eur_per_kwh, period_string) or (None, None).
    """
    try:
        dims = payload.get("dimension", {})
        time_cats = (
            dims.get("time", {})
            .get("category", {})
            .get("index", {})
        )
        if not time_cats:
            return None, None

        values = payload.get("value", {})
        # Sort periods descending — get most recent with a value
        for period in sorted(time_cats.keys(), reverse=True):
            idx = time_cats[period]
            val = values.get(str(idx))
            if val is not None:
                return float(val), period

        return None, None

    except (KeyError, TypeError, ValueError) as exc:
        LOGGER.error("Failed to parse Eurostat JSON-stat: %s", exc)
        return None, None


def _static_rate(iso2: str) -> dict:
    """Returns verified static reference rate."""
    rate = STATIC_RATES.get(iso2)
    source_map = {
        "AU": "AEMC 2024", "JP": "METI 2024", "KR": "KEPCO 2024",
        "CA": "NEB 2024",  "BR": "ANEEL 2024", "IN": "CEA 2024",
        "CN": "NDRC 2024", "ZA": "Eskom 2024", "NG": "NERC 2024",
        "KE": "KPLC 2024", "GH": "ECG 2024",  "TZ": "TANESCO 2024",
        "UG": "UMEME 2024","ET": "EEP 2024",   "EG": "EETC 2024",
        "MA": "ONEE 2024", "SA": "SEC 2024",   "TH": "MEA/PEA 2024",
        "VN": "EVN 2024",  "PH": "Meralco 2024","ID": "PLN 2024",
        "PK": "NEPRA 2024","BD": "BPDB 2024",  "CL": "CNE 2024",
        "CO": "XM 2024",   "PE": "OSINERGMIN 2024","UY": "UTE 2024",
        "MX": "CFE 2024",  "TR": "EPDK 2024",  "GB": "Ofgem H2 2024",
    }
    return {
        "iso2": iso2,
        "rate_cents_kwh": rate,
        "currency": "USD",
        "source": source_map.get(iso2, "Static reference 2024"),
        "period": "2024",
        "method": "static_reference",
        "cache_status": "live",
    }


def _unavailable(iso2: str) -> dict:
    """Returns consistent unavailable response."""
    return {
        "iso2": iso2,
        "rate_cents_kwh": None,
        "currency": "USD",
        "source": "unavailable",
        "period": "unknown",
        "method": "unavailable",
        "cache_status": "live",
    }