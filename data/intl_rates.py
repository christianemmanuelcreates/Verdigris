"""
data/intl_rates.py
International electricity rate data.

Sources:
- EU/EEA: Eurostat nrg_pc_204 (residential) and
           nrg_pc_205 (commercial) — live API
- UK: Ofgem published tariff data
- AU: AEMC Electricity Price Trends Report 2023
- JP: METI Electricity Price Survey 2023
- IN: CEA Annual Report on Electricity Tariffs 2023
- SA: SEC (Saudi Electricity Company) tariff schedule
- ZA: Eskom Tariff Book 2023/24
- All others: STATIC_RATES — national regulator 
  published 2024 averages
"""

from __future__ import annotations
import logging
import requests
from functools import lru_cache

LOGGER = logging.getLogger("verdigris")

# ── EU/EEA country codes ──────────────────────────────────
EU_ISO2 = {
    "AT","BE","BG","CY","CZ","DE","DK","EE","EL","ES",
    "FI","FR","HR","HU","IE","IT","LT","LU","LV","MT",
    "NL","PL","PT","RO","SE","SI","SK",
    # EEA non-EU
    "IS","LI","NO",
    # Special
    "ME","MK","RS","AL","BA","XK"
}

# ── Eurostat API base ─────────────────────────────────────
_ESTAT = (
    "https://ec.europa.eu/eurostat/api/"
    "dissemination/statistics/1.0/data"
)

# ── Non-EU verified historical rates (cents/kWh USD) ─────
# Each year is the annual average residential rate.
# Sources documented per country above.
NON_EU_HISTORY: dict[str, dict] = {
    "GB": {
        "residential": {
            2015: 16.0, 2016: 15.8, 2017: 16.5,
            2018: 18.2, 2019: 18.9, 2020: 18.5,
            2021: 19.2, 2022: 28.0, 2023: 34.0,
            2024: 30.0
        },
        "commercial": {
            2015: 13.0, 2016: 12.8, 2017: 13.4,
            2018: 15.0, 2019: 15.6, 2020: 15.2,
            2021: 16.0, 2022: 26.0, 2023: 30.0,
            2024: 26.0
        },
        "source": "Ofgem published tariff data",
        "cagr_res": 7.2,
        "cagr_com": 7.0,
        "crisis_year": 2022,
    },
    "AU": {
        "residential": {
            2015: 22.0, 2016: 23.5, 2017: 25.0,
            2018: 27.0, 2019: 28.5, 2020: 28.0,
            2021: 27.5, 2022: 28.5, 2023: 31.0,
            2024: 32.0
        },
        "commercial": {
            2015: 18.0, 2016: 19.5, 2017: 21.0,
            2018: 23.0, 2019: 24.0, 2020: 23.5,
            2021: 23.0, 2022: 24.5, 2023: 27.0,
            2024: 28.0
        },
        "source": "AEMC Electricity Price Trends 2023",
        "cagr_res": 4.2,
        "cagr_com": 4.5,
        "crisis_year": None,
    },
    "JP": {
        "residential": {
            2015: 20.0, 2016: 19.5, 2017: 19.8,
            2018: 20.5, 2019: 21.0, 2020: 20.8,
            2021: 21.5, 2022: 23.0, 2023: 26.0,
            2024: 26.0
        },
        "commercial": {
            2015: 17.0, 2016: 16.5, 2017: 16.8,
            2018: 17.5, 2019: 18.0, 2020: 17.8,
            2021: 18.5, 2022: 20.5, 2023: 23.0,
            2024: 23.0
        },
        "source": "METI Electricity Price Survey 2023",
        "cagr_res": 3.0,
        "cagr_com": 3.2,
        "crisis_year": 2022,
    },
    "IN": {
        "residential": {
            2015: 5.0, 2016: 5.3, 2017: 5.6,
            2018: 6.0, 2019: 6.4, 2020: 6.8,
            2021: 7.2, 2022: 7.5, 2023: 7.8,
            2024: 8.0
        },
        "commercial": {
            2015: 7.0, 2016: 7.4, 2017: 7.8,
            2018: 8.3, 2019: 8.8, 2020: 9.2,
            2021: 9.6, 2022: 10.0, 2023: 10.4,
            2024: 10.8
        },
        "source": "CEA Annual Report on Electricity Tariffs 2023",
        "cagr_res": 5.4,
        "cagr_com": 4.9,
        "crisis_year": None,
    },
    "SA": {
        "residential": {
            2015: 1.6, 2016: 4.8, 2017: 4.8,
            2018: 4.8, 2019: 4.8, 2020: 4.8,
            2021: 4.8, 2022: 4.8, 2023: 5.0,
            2024: 5.0
        },
        "commercial": {
            2015: 4.0, 2016: 5.3, 2017: 5.3,
            2018: 5.3, 2019: 5.3, 2020: 5.3,
            2021: 5.3, 2022: 5.3, 2023: 5.5,
            2024: 5.5
        },
        "source": "SEC tariff schedule 2024",
        "cagr_res": 2.5,
        "cagr_com": 1.8,
        "crisis_year": None,
    },
    "ZA": {
        "residential": {
            2015: 10.0, 2016: 11.2, 2017: 12.3,
            2018: 13.5, 2019: 14.8, 2020: 15.8,
            2021: 16.5, 2022: 17.5, 2023: 18.5,
            2024: 19.0
        },
        "commercial": {
            2015: 8.5, 2016: 9.5, 2017: 10.4,
            2018: 11.5, 2019: 12.5, 2020: 13.4,
            2021: 14.0, 2022: 15.0, 2023: 15.8,
            2024: 16.2
        },
        "source": "Eskom Tariff Book 2023/24",
        "cagr_res": 7.4,
        "cagr_com": 7.0,
        "crisis_year": None,
    },
}

# ── Static current rates — national regulator 2024 ───────
STATIC_RATES: dict[str, float] = {
    "AU": 32.0,
    "JP": 26.0,
    "KR": 12.0,
    "CA": 12.0,
    "BR": 15.0,
    "IN": 8.0,
    "CN": 8.0,
    "ZA": 19.0,
    "NG": 1.4,
    "KE": 26.0,
    "GH": 15.0,
    "TZ": 8.0,
    "UG": 16.0,
    "ET": 0.3,
    "EG": 1.9,
    "MA": 8.0,
    "SA": 5.0,
    "TH": 12.0,
    "VN": 8.0,
    "PH": 20.0,
    "ID": 10.0,
    "PK": 12.0,
    "BD": 9.0,
    "CL": 20.0,
    "CO": 17.0,
    "PE": 16.0,
    "UY": 22.0,
    "MX": 10.0,
    "TR": 10.0,
    "GB": 30.0,
}

# EUR/USD exchange rate for Eurostat conversion
_EUR_TO_USD = 1.08


def _eurostat_series(
    dataset: str,
    iso2: str,
    nrg_cons: str,
) -> dict[int, float]:
    """
    Fetch bi-annual Eurostat rate series and return
    annual averages as {year: cents_per_kwh}.
    Returns empty dict on any failure.
    """
    try:
        r = requests.get(
            f"{_ESTAT}/{dataset}",
            params={
                "lang": "EN",
                "geo": iso2,
                "nrg_cons": nrg_cons,
                "tax": "I_TAX",
                "currency": "EUR",
                "unit": "KWH",
                "sinceTimePeriod": "2015-S1",
            },
            timeout=20,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        time_idx = (
            data.get("dimension", {})
            .get("time", {})
            .get("category", {})
            .get("index", {})
        )
        values = data.get("value", {})

        # Collect semi-annual values
        semi: dict[str, float] = {}
        for period, idx in time_idx.items():
            val = values.get(str(idx))
            if val:
                semi[period] = val * _EUR_TO_USD * 100

        # Average S1 + S2 per year
        annual: dict[int, float] = {}
        years: set[int] = set()
        for period in semi:
            years.add(int(period[:4]))
        for year in sorted(years):
            s1 = semi.get(f"{year}-S1")
            s2 = semi.get(f"{year}-S2")
            vals = [v for v in [s1, s2] if v]
            if vals:
                annual[year] = round(sum(vals) / len(vals), 2)
        return annual

    except Exception as exc:
        LOGGER.warning("Eurostat series failed %s %s: %s",
                       dataset, iso2, exc)
        return {}


@lru_cache(maxsize=128)
def get_intl_rate_history(iso2: str) -> dict:
    """
    Return rate history for a country.

    Returns dict with keys:
        residential: {year: cents_kwh}
        commercial:  {year: cents_kwh}
        source:      str
        cagr_res:    float
        cagr_com:    float
        crisis_year: int | None
        is_live:     bool
    """
    iso2 = iso2.upper()

    # EU/EEA — live Eurostat data
    if iso2 in EU_ISO2:
        res = _eurostat_series(
            "nrg_pc_204", iso2, "KWH2500-4999"
        )
        com = _eurostat_series(
            "nrg_pc_205", iso2, "MWH500-1999"
        )
        if res:
            years = sorted(res.keys())
            if len(years) >= 2:
                cagr_res = round(
                    ((res[years[-1]] / res[years[0]])
                     ** (1 / (years[-1] - years[0])) - 1) * 100,
                    2
                )
            else:
                cagr_res = 0.0
            if com and len(years) >= 2:
                com_years = sorted(com.keys())
                cagr_com = round(
                    ((com[com_years[-1]] / com[com_years[0]])
                     ** (1 / (com_years[-1] - com_years[0]))
                     - 1) * 100,
                    2
                )
            else:
                cagr_com = cagr_res * 0.85
            return {
                "residential": res,
                "commercial": com or {},
                "source": "Eurostat nrg_pc_204 / nrg_pc_205",
                "cagr_res": cagr_res,
                "cagr_com": cagr_com,
                "crisis_year": 2022 if iso2 in {
                    "DE","FR","IT","ES","NL","BE",
                    "PL","AT","SE","FI","DK","NO"
                } else None,
                "is_live": True,
            }

    # Non-EU with verified historical data
    if iso2 in NON_EU_HISTORY:
        entry = NON_EU_HISTORY[iso2]
        return {**entry, "is_live": False}

    # All other countries — static rate only
    current = STATIC_RATES.get(iso2, 15.0)
    # Build synthetic history using 3% CAGR backwards
    synthetic_res = {}
    synthetic_com = {}
    for year in range(2015, 2025):
        years_back = 2024 - year
        synthetic_res[year] = round(
            current / (1.03 ** years_back), 2
        )
        synthetic_com[year] = round(
            current * 0.75 / (1.03 ** years_back), 2
        )
    return {
        "residential": synthetic_res,
        "commercial": synthetic_com,
        "source": "Estimated — static 2024 rate with 3% CAGR",
        "cagr_res": 3.0,
        "cagr_com": 3.0,
        "crisis_year": None,
        "is_live": False,
    }


def get_current_rate(iso2: str) -> float:
    """Return current residential rate in cents/kWh."""
    history = get_intl_rate_history(iso2)
    res = history.get("residential", {})
    if res:
        return res[max(res.keys())]
    return STATIC_RATES.get(iso2.upper(), 15.0)


def get_current_commercial_rate(iso2: str) -> float:
    """Return current commercial rate in cents/kWh."""
    history = get_intl_rate_history(iso2)
    com = history.get("commercial", {})
    if com:
        return com[max(com.keys())]
    res = get_current_rate(iso2)
    return round(res * 0.75, 2)
