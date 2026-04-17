"""
seed_warehouse.py — One-time historical data loader for Verdigris.

Run once after cloning:
    python3 data/seed_warehouse.py

Loads 10 years of data (2015–2024) for:
  - All 50 U.S. states + DC (EIA consumption, rates, generation)
  - ~40 international countries (World Bank + Ember)

Estimated run time: 2–4 minutes depending on API response speed.
Estimated database size after seeding: ~10MB.

Safe to re-run — uses upsert logic, will not duplicate rows.
Each dataset loads independently — one failure does not stop others.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from time import sleep
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

# ── Project setup ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT))
from data.warehouse import init_warehouse, WAREHOUSE_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("seed_warehouse")

# ── Configuration ─────────────────────────────────────────────────────────────

EIA_BASE_URL = os.getenv("EIA_BASE_URL", "https://api.eia.gov/v2").rstrip("/")
EIA_API_KEY  = os.getenv("EIA_API_KEY", "").strip() or None

START_YEAR = 2015
END_YEAR   = 2024

# EIA allows 1,000 requests/hour = ~1 per 3.6 seconds to be safe
# We use 0.5s delay — well within limits but polite
EIA_REQUEST_DELAY = 0.5

# All 50 states + DC
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
]

# Countries from regions.md — ISO2 and ISO3 pairs
COUNTRIES = [
    ("AU","AUS"),("AT","AUT"),("BE","BEL"),("BR","BRA"),("CA","CAN"),
    ("CL","CHL"),("CN","CHN"),("CO","COL"),("DK","DNK"),("EG","EGY"),
    ("ET","ETH"),("FR","FRA"),("DE","DEU"),("GH","GHA"),("IN","IND"),
    ("ID","IDN"),("IT","ITA"),("JP","JPN"),("KE","KEN"),("MX","MEX"),
    ("MA","MAR"),("NL","NLD"),("NG","NGA"),("NO","NOR"),("PK","PAK"),
    ("PE","PER"),("PH","PHL"),("PL","POL"),("PT","PRT"),("SA","SAU"),
    ("ZA","ZAF"),("KR","KOR"),("ES","ESP"),("SE","SWE"),("TZ","TZA"),
    ("TH","THA"),("TR","TUR"),("UG","UGA"),("GB","GBR"),("US","USA"),
    ("UY","URY"),("VN","VNM"),
]

# World Bank indicators to load
WB_INDICATORS = [
    "SP.POP.TOTL",       # total population
    "EG.ELC.ACCS.ZS",   # electricity access %
    "EG.USE.ELEC.KH.PC", # kWh per capita
]

# EIA fuel type codes
EIA_FUEL_TYPES = ["SUN","WND","NG","COL","NUC","WAT","OIL"]

# EIA sectors
EIA_SECTORS = {
    "consumption": ["residential","commercial","industrial","total"],
    "rates": ["RES","COM","IND"],
}
SECTOR_MAP = {"RES":"residential","COM":"commercial","IND":"industrial"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(WAREHOUSE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get(url: str, params: dict, label: str, retries: int = 3) -> dict | None:
    """GET with retry and basic error handling."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            LOGGER.warning(
                "%s — HTTP %s (attempt %d/%d)", label, resp.status_code, attempt, retries
            )
        except requests.RequestException as exc:
            LOGGER.warning("%s — request error (attempt %d/%d): %s", label, attempt, retries, exc)
        if attempt < retries:
            time.sleep(2 ** attempt)
    LOGGER.error("%s — all %d attempts failed", label, retries)
    return None


def _paginate_eia(endpoint: str, params: dict, label: str) -> list[dict]:
    """
    Handles EIA API pagination. Returns all rows across all pages.
    EIA returns max 5,000 rows per request.
    """
    all_rows = []
    offset = 0
    page_size = 5000

    while True:
        paged_params = {**params, "offset": offset, "length": page_size}
        data = _get(endpoint, paged_params, f"{label} (offset={offset})")

        if not data:
            break

        rows = data.get("response", {}).get("data", [])
        if not rows:
            break

        all_rows.extend(rows)
        if len(rows) < page_size:
            break

        total_raw = data.get("response", {}).get("total", 0)
        try:
            total = int(total_raw)
        except (ValueError, TypeError):
            total = 0

        offset = int(offset) + int(page_size)
        if int(offset) >= int(total):
            break

        time.sleep(EIA_REQUEST_DELAY)  # polite pacing

    return all_rows


# ── EIA Consumption ───────────────────────────────────────────────────────────

def load_eia_consumption() -> int:
    """Loads annual state electricity consumption 2015–2024."""
    print("\n── EIA Consumption (annual, all states, 2015–2024)")

    endpoint = f"{EIA_BASE_URL}/electricity/retail-sales/data"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "annual",
        "data[0]": "sales",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "start": str(START_YEAR),
        "end": str(END_YEAR),
    }

    rows = _paginate_eia(endpoint, params, "EIA consumption")
    if not rows:
        print("  ✗ No data returned")
        return 0

    inserted = 0
    now = _utcnow()

    with _connect() as conn:
        for i, row in enumerate(rows):
            state = row.get("stateid") or row.get("stateId") or row.get("state")
            period = str(row.get("period", ""))
            sector_raw = row.get("sectorid") or row.get("sectorId") or row.get("sector", "")
            sales = row.get("sales")

            if not state or not period or sales is None:
                continue

            # Map EIA sector codes to readable names
            sector_map = {
                "RES": "residential", "COM": "commercial",
                "IND": "industrial",  "ALL": "total",
                "residential": "residential", "commercial": "commercial",
                "industrial": "industrial",   "total": "total",
            }
            sector = sector_map.get(str(sector_raw).upper(), str(sector_raw).lower())

            # Only keep the sectors we care about
            if sector not in ("residential", "commercial", "industrial", "total"):
                continue

            try:
                year = int(str(period)[:4])
            except (ValueError, TypeError):
                continue
            if year < START_YEAR or year > END_YEAR:
                continue

            if state not in US_STATES:
                continue

            conn.execute("""
                INSERT INTO eia_consumption
                    (state_abbr, year, sector, consumption_mwh, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(state_abbr, year, sector) DO UPDATE SET
                    consumption_mwh = excluded.consumption_mwh,
                    updated_at = excluded.updated_at
            """, (state, year, sector, float(sales) if sales is not None else None, now))
            inserted += 1
            if i % 5000 == 0 and i > 0:
                conn.commit()

        conn.commit()

    print(f"  ✓ {inserted:,} rows inserted/updated")
    return inserted


# ── EIA Rates ─────────────────────────────────────────────────────────────────

def load_eia_rates() -> int:
    """Loads monthly retail electricity rates 2015–2024."""
    print("\n── EIA Retail Rates (monthly, all states, 2015–2024)")

    endpoint = f"{EIA_BASE_URL}/electricity/retail-sales/data"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "monthly",
        "data[0]": "price",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "start": f"{START_YEAR}-01",
        "end": f"{END_YEAR}-12",
    }

    rows = _paginate_eia(endpoint, params, "EIA rates")
    if not rows:
        print("  ✗ No data returned")
        return 0

    inserted = 0
    now = _utcnow()

    with _connect() as conn:
        for i, row in enumerate(rows):
            state = row.get("stateid") or row.get("stateId") or row.get("state")
            period = str(row.get("period", ""))
            sector_raw = row.get("sectorid") or row.get("sectorId") or row.get("sector", "")
            price = row.get("price")

            if not state or not period or price is None:
                continue

            try:
                year_check = int(str(period)[:4])
            except (ValueError, TypeError):
                continue
            if year_check < START_YEAR or year_check > END_YEAR:
                continue

            sector_map = {
                "RES": "residential", "COM": "commercial",
                "IND": "industrial",  "ALL": "total",
            }
            sector = sector_map.get(str(sector_raw).upper())
            if not sector or sector == "total":
                continue

            if state not in US_STATES:
                continue

            if len(period) < 7:
                continue

            conn.execute("""
                INSERT INTO eia_rates
                    (state_abbr, period, sector, rate_cents_kwh, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(state_abbr, period, sector) DO UPDATE SET
                    rate_cents_kwh = excluded.rate_cents_kwh,
                    updated_at = excluded.updated_at
            """, (state, period[:7], sector, float(price), now))
            inserted += 1
            if i % 5000 == 0 and i > 0:
                conn.commit()

        conn.commit()

    print(f"  ✓ {inserted:,} rows inserted/updated")
    return inserted


# ── EIA Generation ────────────────────────────────────────────────────────────

def load_eia_generation() -> int:
    """Loads monthly generation by fuel type, one fuel+state
    combo at a time to get state-level data.
    Rate limited to 0.5s between requests — well within EIA
    limit of 1,000 requests/hour.
    """
    print("\n── EIA Generation Mix (monthly, all states, 2015–2024)")

    endpoint = (
        f"{EIA_BASE_URL}/electricity/"
        f"electric-power-operational-data/data"
    )
    inserted = 0
    now = _utcnow()
    total_combos = len(EIA_FUEL_TYPES) * len(US_STATES)

    with tqdm(total=total_combos,
              desc="  Generation",
              unit="combo") as pbar:
        for fuel in EIA_FUEL_TYPES:
            for state in US_STATES:
                params = {
                    "api_key": EIA_API_KEY,
                    "frequency": "monthly",
                    "data[0]": "generation",
                    "facets[fueltypeid][]": fuel,
                    "facets[location][]": state,
                    "facets[sectorid][]": "99",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "start": f"{START_YEAR}-01",
                    "end": f"{END_YEAR}-12",
                }

                # Retry on 429 rate limit response
                for attempt in range(3):
                    try:
                        resp = requests.get(
                            endpoint,
                            params=params,
                            timeout=30
                        )
                        if resp.status_code == 429:
                            wait = 60 * (attempt + 1)
                            tqdm.write(
                                f"  Rate limited — waiting "
                                f"{wait}s before retry"
                            )
                            time.sleep(wait)
                            continue
                        resp.raise_for_status()
                        rows = (
                            resp.json()
                            .get("response", {})
                            .get("data", [])
                        )
                        break
                    except requests.RequestException as exc:
                        tqdm.write(
                            f"  {fuel}/{state} attempt "
                            f"{attempt+1} failed: {exc}"
                        )
                        time.sleep(EIA_REQUEST_DELAY * 2)
                        rows = []
                else:
                    rows = []

                pbar.update(1)
                time.sleep(EIA_REQUEST_DELAY)

                if not rows:
                    continue

                with _connect() as conn:
                    for row in rows:
                        period = str(row.get("period", ""))
                        generation = row.get("generation")

                        if not period or generation is None:
                            continue
                        if len(period) < 7:
                            continue

                        try:
                            year_check = int(str(period)[:4])
                        except (ValueError, TypeError):
                            continue
                        if (year_check < START_YEAR
                                or year_check > END_YEAR):
                            continue

                        conn.execute("""
                            INSERT INTO eia_generation
                                (state_abbr, period, fuel_type,
                                 generation_mwh, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(state_abbr, period, fuel_type)
                            DO UPDATE SET
                                generation_mwh = excluded.generation_mwh,
                                updated_at = excluded.updated_at
                        """, (state, period[:7], fuel,
                              float(generation), now))
                        inserted += 1
                    conn.commit()

    print(f"  ✓ {inserted:,} rows total")
    return inserted


# ── World Bank ────────────────────────────────────────────────────────────────

def load_world_bank() -> int:
    """Loads World Bank energy indicators for all countries 2015–2024."""
    print(f"\n── World Bank Indicators ({len(COUNTRIES)} countries × {len(WB_INDICATORS)} indicators)")

    inserted = 0
    now = _utcnow()

    for iso2, _iso3 in tqdm(COUNTRIES, desc="  Countries",
                             unit="country"):
        for indicator in WB_INDICATORS:
            url = (
                f"https://api.worldbank.org/v2/country/{iso2}"
                f"/indicator/{indicator}"
            )
            params = {
                "format": "json",
                "date": f"{START_YEAR}:{END_YEAR}",
                "per_page": 50,
            }
            data = _get(url, params, f"WorldBank {iso2}/{indicator}")
            if not data or len(data) < 2:
                continue

            records = data[1] if isinstance(data, list) and len(data) > 1 else []
            if not records:
                continue

            with _connect() as conn:
                for record in records:
                    year_str = record.get("date")
                    value = record.get("value")
                    try:
                        year = int(year_str)
                    except (TypeError, ValueError):
                        continue

                    conn.execute("""
                        INSERT INTO wb_country_data
                            (iso2, year, indicator, value, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(iso2, year, indicator) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at
                    """, (iso2, year, indicator, float(value) if value is not None else None, now))
                    inserted += 1
                conn.commit()

            time.sleep(0.2)

    print(f"  ✓ {inserted:,} rows inserted/updated")
    return inserted


# ── Ember Generation ──────────────────────────────────────────────────────────

def load_ember() -> int:
    """
    Loads yearly electricity generation mix from Ember API.
    Endpoint: https://api.ember-energy.org/v1/electricity-generation/yearly
    API key passed as query parameter.
    No rate limiting required per Ember documentation.
    """
    print(f"\n── Ember Generation Mix ({len(COUNTRIES)} countries)")

    EMBER_API_KEY = os.getenv("EMBER_API_KEY", "").strip()
    base_url = "https://api.ember-energy.org"
    endpoint = f"{base_url}/v1/electricity-generation/yearly"

    if not EMBER_API_KEY:
        print("  ✗ EMBER_API_KEY not set — skipping")
        return 0

    inserted = 0
    now = _utcnow()

    # Build comma-separated list of ISO3 codes
    iso3_codes = ",".join(iso3 for _, iso3 in COUNTRIES)

    params = {
        "entity_code": iso3_codes,
        "is_aggregate_series": "false",
        "start_date": str(START_YEAR),
        "end_date": str(END_YEAR),
        "api_key": EMBER_API_KEY,
    }

    try:
        resp = requests.get(endpoint, params=params, timeout=60)
        if resp.status_code == 403:
            print("  ✗ Ember API key invalid — check EMBER_API_KEY in .env")
            return 0
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        LOGGER.error("Ember API request failed: %s", exc)
        return 0

    # Ember returns data in a 'data' key
    records = payload.get("data", [])
    if not records:
        print("  ✗ No records returned from Ember")
        print("  Response keys:", list(payload.keys()))
        return 0

    print(f"  Retrieved {len(records):,} records from Ember API")

    # Map ISO3 codes for lookup
    iso3_set = {iso3 for _, iso3 in COUNTRIES}

    known_fuels = {
        "solar", "wind", "hydro", "nuclear",
        "gas", "coal", "other_renewables",
        "bioenergy", "other_fossil",
    }

    with _connect() as conn:
        for record in tqdm(records, desc="  Ember", unit="rows"):
            iso3 = record.get("entity_code", "")
            if iso3 not in iso3_set:
                continue

            year_val = record.get("year") or record.get("date")
            try:
                year = int(str(year_val)[:4])
            except (TypeError, ValueError):
                continue

            if year < START_YEAR or year > END_YEAR:
                continue

            # Ember series field contains fuel type
            fuel = str(
                record.get("series", "")
            ).lower().replace(" ", "_")

            if fuel not in known_fuels:
                continue

            gen_twh = record.get("generation_twh")
            share = record.get("share_of_generation_pct")

            conn.execute("""
                INSERT INTO ember_generation
                    (iso3, year, fuel_type, generation_twh,
                     share_pct, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(iso3, year, fuel_type) DO UPDATE SET
                    generation_twh = excluded.generation_twh,
                    share_pct = excluded.share_pct,
                    updated_at = excluded.updated_at
            """, (
                iso3, year, fuel,
                float(gen_twh) if gen_twh is not None else None,
                float(share) if share is not None else None,
                now,
            ))
            inserted += 1

        conn.commit()

    print(f"  ✓ {inserted:,} rows inserted/updated")
    return inserted


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(results: dict, start_time: float) -> None:
    elapsed = time.time() - start_time
    total = sum(v for v in results.values() if isinstance(v, int))

    print("\n" + "─" * 50)
    print("SEED COMPLETE")
    print("─" * 50)
    for dataset, count in results.items():
        status = "✓" if isinstance(count, int) and count > 0 else "✗"
        label = f"{count:,} rows" if isinstance(count, int) else str(count)
        print(f"  {status}  {dataset:<30} {label}")
    print(f"\n  Total rows: {total:,}")
    print(f"  Run time:   {elapsed:.1f}s")
    print(f"  Database:   {WAREHOUSE_PATH}")
    print("─" * 50)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 50)
    print("Verdigris — Warehouse Seed Script")
    print(f"Target: {START_YEAR}–{END_YEAR}")
    print(f"U.S. states: {len(US_STATES)}")
    print(f"Countries:   {len(COUNTRIES)}")
    print(f"Database:    {WAREHOUSE_PATH}")
    print("=" * 50)

    # Validate environment
    if not EIA_API_KEY:
        print("\n⚠  EIA_API_KEY not set in .env")
        print("   EIA datasets will be skipped.")
        print("   Set EIA_API_KEY and re-run to load U.S. data.\n")

    # Initialise tables
    print("\nInitialising warehouse tables...")
    init_warehouse()
    print("  ✓ Tables ready")

    start_time = time.time()
    results = {}

    # Load each dataset independently
    # ── U.S. EIA datasets ──
    if EIA_API_KEY:
        try:
            results["EIA Consumption"] = load_eia_consumption()
        except Exception as exc:
            LOGGER.error("EIA Consumption failed: %s", exc)
            results["EIA Consumption"] = "FAILED"

        try:
            results["EIA Rates"] = load_eia_rates()
        except Exception as exc:
            LOGGER.error("EIA Rates failed: %s", exc)
            results["EIA Rates"] = "FAILED"

        try:
            results["EIA Generation"] = load_eia_generation()
        except Exception as exc:
            LOGGER.error("EIA Generation failed: %s", exc)
            results["EIA Generation"] = "FAILED"
    else:
        results["EIA Consumption"] = "SKIPPED (no API key)"
        results["EIA Rates"] = "SKIPPED (no API key)"
        results["EIA Generation"] = "SKIPPED (no API key)"

    # ── International datasets (no key required) ──
    try:
        results["World Bank"] = load_world_bank()
    except Exception as exc:
        LOGGER.error("World Bank failed: %s", exc)
        results["World Bank"] = "FAILED"

    try:
        results["Ember"] = load_ember()
    except Exception as exc:
        LOGGER.error("Ember failed: %s", exc)
        results["Ember"] = "FAILED"

    print_summary(results, start_time)


if __name__ == "__main__":
    main()