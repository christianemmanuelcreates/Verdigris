from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = PROJECT_ROOT / "verdigris_warehouse.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(WAREHOUSE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_warehouse() -> None:
    """Creates all five warehouse tables if they do not exist."""
    with _connect() as conn:

        # U.S. annual electricity consumption by state and sector
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eia_consumption (
                state_abbr      TEXT NOT NULL,
                year            INTEGER NOT NULL,
                sector          TEXT NOT NULL,
                consumption_mwh REAL,
                updated_at      TEXT,
                PRIMARY KEY (state_abbr, year, sector)
            )
        """)

        # U.S. monthly retail electricity rates by state and sector
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eia_rates (
                state_abbr      TEXT NOT NULL,
                period          TEXT NOT NULL,
                sector          TEXT NOT NULL,
                rate_cents_kwh  REAL,
                updated_at      TEXT,
                PRIMARY KEY (state_abbr, period, sector)
            )
        """)

        # U.S. monthly electricity generation by state and fuel type
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eia_generation (
                state_abbr      TEXT NOT NULL,
                period          TEXT NOT NULL,
                fuel_type       TEXT NOT NULL,
                generation_mwh  REAL,
                updated_at      TEXT,
                PRIMARY KEY (state_abbr, period, fuel_type)
            )
        """)

        # International annual World Bank energy indicators by country
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wb_country_data (
                iso2            TEXT NOT NULL,
                year            INTEGER NOT NULL,
                indicator       TEXT NOT NULL,
                value           REAL,
                updated_at      TEXT,
                PRIMARY KEY (iso2, year, indicator)
            )
        """)

        # International annual Ember electricity generation mix by country
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ember_generation (
                iso3            TEXT NOT NULL,
                year            INTEGER NOT NULL,
                fuel_type       TEXT NOT NULL,
                generation_twh  REAL,
                share_pct       REAL,
                updated_at      TEXT,
                PRIMARY KEY (iso3, year, fuel_type)
            )
        """)

        # Create indexes for the most common query patterns
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_consumption_state_sector
            ON eia_consumption (state_abbr, sector)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rates_state_sector
            ON eia_rates (state_abbr, sector)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_generation_state_fuel
            ON eia_generation (state_abbr, fuel_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_wb_iso2
            ON wb_country_data (iso2)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ember_iso3
            ON ember_generation (iso3)
        """)

        conn.commit()

    LOGGER.info("Warehouse initialised at %s", WAREHOUSE_PATH)


def query(sql: str) -> list[dict]:
    """
    Executes a SELECT query against the warehouse.

    Validates that the statement is a SELECT before execution.
    Raises ValueError if the statement is not a SELECT.
    Returns a list of row dicts (column name → value).
    Returns an empty list if no rows match — never raises on empty.
    """
    stripped = sql.strip()
    first_word = stripped.split()[0].upper() if stripped.split() else ""

    if first_word != "SELECT":
        raise ValueError(
            f"warehouse.query() only accepts SELECT statements. "
            f"Received: {first_word!r}. "
            f"Write operations are not permitted through this interface."
        )

    # Block common dangerous patterns even if buried in a subquery
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER", "ATTACH"]
    upper_sql = sql.upper()
    for keyword in forbidden:
        if keyword in upper_sql:
            raise ValueError(
                f"warehouse.query() blocked: SQL contains forbidden keyword {keyword!r}."
            )

    try:
        with _connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        LOGGER.error("Warehouse query failed: %s\nSQL: %s", exc, sql)
        raise


def get_schema_description() -> str:
    """
    Returns a human-readable schema description for injection
    into the analyst agent prompt. Includes example queries.
    """
    counts = get_row_counts()

    return f"""## Warehouse — Historical Energy Data

Available via warehouse.query(sql) — SELECT only.
Use this for trend analysis, historical comparisons, and time-series data.
Do not use for current point-in-time data — use the API connectors for that.

---

### Table: eia_consumption
U.S. annual electricity consumption by state and sector.
Rows: {counts.get('eia_consumption', 0):,}
Columns:
  state_abbr TEXT         — 2-letter state abbreviation (e.g. 'CA', 'TX')
  year INTEGER            — calendar year (2015–2024)
  sector TEXT             — 'residential' | 'commercial' | 'industrial' | 'total'
  consumption_mwh REAL    — annual electricity consumption in MWh

Example queries:
  -- California total consumption trend
  SELECT year, consumption_mwh FROM eia_consumption
  WHERE state_abbr = 'CA' AND sector = 'total' ORDER BY year ASC;

  -- Which states consumed the most in 2023?
  SELECT state_abbr, consumption_mwh FROM eia_consumption
  WHERE year = 2023 AND sector = 'total' ORDER BY consumption_mwh DESC LIMIT 10;

---

### Table: eia_rates
U.S. monthly retail electricity rates by state and sector.
Rows: {counts.get('eia_rates', 0):,}
Columns:
  state_abbr TEXT         — 2-letter state abbreviation
  period TEXT             — month as 'YYYY-MM' (e.g. '2024-03')
  sector TEXT             — 'residential' | 'commercial' | 'industrial'
  rate_cents_kwh REAL     — retail rate in cents per kWh

Example queries:
  -- Texas residential rate trend (last 24 months)
  SELECT period, rate_cents_kwh FROM eia_rates
  WHERE state_abbr = 'TX' AND sector = 'residential'
  ORDER BY period DESC LIMIT 24;

  -- States with fastest residential rate growth since 2020
  SELECT state_abbr,
         MAX(rate_cents_kwh) - MIN(rate_cents_kwh) AS rate_increase
  FROM eia_rates
  WHERE sector = 'residential' AND period >= '2020-01'
  GROUP BY state_abbr ORDER BY rate_increase DESC LIMIT 10;

---

### Table: eia_generation
U.S. monthly electricity generation by state and fuel type.
Rows: {counts.get('eia_generation', 0):,}
Columns:
  state_abbr TEXT         — 2-letter state abbreviation
  period TEXT             — month as 'YYYY-MM'
  fuel_type TEXT          — 'SUN' | 'WND' | 'NG' | 'COL' | 'NUC' | 'WAT' | 'OIL'
  generation_mwh REAL     — generation in MWh for this month

Fuel type codes:
  SUN = Solar  |  WND = Wind  |  NG = Natural Gas
  COL = Coal   |  NUC = Nuclear  |  WAT = Hydro  |  OIL = Petroleum

Example queries:
  -- California solar generation growth
  SELECT period, generation_mwh FROM eia_generation
  WHERE state_abbr = 'CA' AND fuel_type = 'SUN'
  ORDER BY period ASC;

  -- Top solar states by 2024 generation
  SELECT state_abbr, SUM(generation_mwh) AS total_solar_mwh
  FROM eia_generation
  WHERE fuel_type = 'SUN' AND period LIKE '2024%'
  GROUP BY state_abbr ORDER BY total_solar_mwh DESC LIMIT 10;

---

### Table: wb_country_data
International World Bank energy indicators by country and year.
Rows: {counts.get('wb_country_data', 0):,}
Columns:
  iso2 TEXT               — ISO 2-letter country code (e.g. 'DE', 'IN')
  year INTEGER            — calendar year (2015–2024)
  indicator TEXT          — see below
  value REAL              — indicator value

Indicator codes:
  SP.POP.TOTL       — total population
  EG.ELC.ACCS.ZS    — electricity access (% of population)
  EG.USE.ELEC.KH.PC — electric power consumption (kWh per capita)

Example queries:
  -- Germany electricity access over time
  SELECT year, value FROM wb_country_data
  WHERE iso2 = 'DE' AND indicator = 'EG.ELC.ACCS.ZS'
  ORDER BY year ASC;

  -- Countries with lowest electricity access (most recent year)
  SELECT iso2, value FROM wb_country_data
  WHERE indicator = 'EG.ELC.ACCS.ZS' AND year = (
      SELECT MAX(year) FROM wb_country_data WHERE indicator = 'EG.ELC.ACCS.ZS'
  )
  ORDER BY value ASC LIMIT 10;

---

### Table: ember_generation
International annual electricity generation mix by country.
Rows: {counts.get('ember_generation', 0):,}
Columns:
  iso3 TEXT               — ISO 3-letter country code (e.g. 'DEU', 'IND')
  year INTEGER            — calendar year (2015–2024)
  fuel_type TEXT          — 'solar' | 'wind' | 'hydro' | 'nuclear' | 'gas' | 'coal' | 'other_renewables'
  generation_twh REAL     — generation in TWh
  share_pct REAL          — percentage share of total generation

IMPORTANT: Ember data measures generation mix, not retail prices.
Never use share_pct to make statements about electricity costs.

Example queries:
  -- Germany renewable share trend
  SELECT year, SUM(share_pct) AS renewables_pct
  FROM ember_generation
  WHERE iso3 = 'DEU' AND fuel_type IN ('solar', 'wind', 'hydro', 'other_renewables')
  GROUP BY year ORDER BY year ASC;

  -- Countries with highest solar share in most recent year
  SELECT iso3, share_pct FROM ember_generation
  WHERE fuel_type = 'solar' AND year = (
      SELECT MAX(year) FROM ember_generation WHERE fuel_type = 'solar'
  )
  ORDER BY share_pct DESC LIMIT 10;
"""


def get_row_counts() -> dict:
    """Returns row count for each warehouse table."""
    tables = [
        "eia_consumption",
        "eia_rates",
        "eia_generation",
        "wb_country_data",
        "ember_generation",
    ]
    counts = {}
    try:
        with _connect() as conn:
            for table in tables:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()
                counts[table] = row["n"] if row else 0
    except sqlite3.Error as exc:
        LOGGER.warning("Could not get row counts: %s", exc)
        for table in tables:
            counts.setdefault(table, 0)
    return counts


def is_seeded() -> bool:
    """
    Returns True if all five tables have meaningful data.
    Uses 100 rows as the threshold — enough to confirm seeding ran.
    """
    counts = get_row_counts()
    return all(counts.get(t, 0) >= 100 for t in counts)


def get_data_range(table: str, date_col: str) -> dict:
    """
    Returns the min and max value of a date/year column in a table.
    Useful for confirming what time range has been seeded.
    """
    try:
        with _connect() as conn:
            row = conn.execute(
                f"SELECT MIN({date_col}) AS min_val, "
                f"MAX({date_col}) AS max_val FROM {table}"
            ).fetchone()
            if row:
                return {"min": row["min_val"], "max": row["max_val"]}
    except sqlite3.Error as exc:
        LOGGER.warning("get_data_range failed for %s.%s: %s", table, date_col, exc)
    return {"min": None, "max": None}


def get_country_profile(iso2: str, iso3: str) -> dict:
    """
    Returns Ember generation mix + World Bank indicators
    for a country directly from the warehouse.

    Replaces ember.py and worldbank.py connectors entirely.
    No API calls — reads from pre-seeded warehouse tables.

    Returns:
    {
        "country": str,
        "iso2": str,
        "iso3": str,
        "renewables_pct": float | None,
        "solar_pct": float | None,
        "wind_pct": float | None,
        "hydro_pct": float | None,
        "fossil_pct": float | None,
        "nuclear_pct": float | None,
        "generation_year": int | None,
        "population": float | None,
        "electricity_access_pct": float | None,
        "kwh_per_capita": float | None,
        "wb_year": int | None,
        "note": "Generation mix only — not retail electricity rates",
        "source": "Ember Climate + World Bank (warehouse)"
    }
    """
    iso2 = iso2.upper().strip()
    iso3 = iso3.upper().strip()

    # ── Ember generation mix ──────────────────────────────────────────
    ember_rows = query(f"""
        SELECT year, fuel_type, share_pct, generation_twh
        FROM ember_generation
        WHERE iso3 = '{iso3}'
        ORDER BY year DESC
        LIMIT 20
    """)

    # Group by most recent year
    generation_year = None
    fuel_shares: dict[str, float | None] = {}

    if ember_rows:
        generation_year = ember_rows[0]["year"]
        for row in ember_rows:
            if row["year"] == generation_year:
                fuel_shares[row["fuel_type"]] = row["share_pct"]

    # Aggregate renewable share
    renewable_fuels = {"solar", "wind", "hydro", "other_renewables", "bioenergy"}
    fossil_fuels = {"coal", "gas", "other_fossil"}

    renewables_pct = None
    if any(f in fuel_shares for f in renewable_fuels):
        vals = [fuel_shares[f] for f in renewable_fuels
                if f in fuel_shares and fuel_shares[f] is not None]
        renewables_pct = round(sum(vals), 2) if vals else None

    fossil_pct = None
    if any(f in fuel_shares for f in fossil_fuels):
        vals = [fuel_shares[f] for f in fossil_fuels
                if f in fuel_shares and fuel_shares[f] is not None]
        fossil_pct = round(sum(vals), 2) if vals else None

    # ── World Bank indicators ─────────────────────────────────────────
    wb_rows = query(f"""
        SELECT year, indicator, value
        FROM wb_country_data
        WHERE iso2 = '{iso2}'
        ORDER BY year DESC
        LIMIT 15
    """)

    wb_year = None
    population = None
    electricity_access_pct = None
    kwh_per_capita = None

    if wb_rows:
        # Get most recent non-null value for each indicator
        for row in wb_rows:
            if row["value"] is None:
                continue
            ind = row["indicator"]
            if ind == "SP.POP.TOTL" and population is None:
                population = row["value"]
                wb_year = row["year"]
            elif ind == "EG.ELC.ACCS.ZS" and electricity_access_pct is None:
                electricity_access_pct = row["value"]
            elif ind == "EG.USE.ELEC.KH.PC" and kwh_per_capita is None:
                kwh_per_capita = row["value"]

    return {
        "country": iso2,
        "iso2": iso2,
        "iso3": iso3,
        "renewables_pct": renewables_pct,
        "solar_pct": fuel_shares.get("solar"),
        "wind_pct": fuel_shares.get("wind"),
        "hydro_pct": fuel_shares.get("hydro"),
        "fossil_pct": fossil_pct,
        "nuclear_pct": fuel_shares.get("nuclear"),
        "generation_year": generation_year,
        "population": population,
        "electricity_access_pct": electricity_access_pct,
        "kwh_per_capita": kwh_per_capita,
        "wb_year": wb_year,
        "note": "Generation mix only — not retail electricity rates",
        "source": "Ember Climate + World Bank (warehouse)",
    }