from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "verdigris.db"


def _utcnow_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(value: str | None) -> datetime | None:
	if not value:
		return None
	try:
		return datetime.fromisoformat(value.replace("Z", "+00:00"))
	except ValueError:
		return None


def _to_float(value: Any) -> float | None:
	try:
		if value is None:
			return None
		return float(value)
	except (TypeError, ValueError):
		return None


def _format_value(value: float | None, decimals: int = 2) -> str:
	if value is None:
		return "N/A"
	return f"{value:.{decimals}f}"


def _connect() -> sqlite3.Connection:
	return sqlite3.connect(DB_PATH)


def init_db() -> None:
	with _connect() as conn:
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS cache (
				key TEXT PRIMARY KEY,
				value TEXT,
				fetched_at TEXT
			)
			"""
		)
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS market_benchmarks (
				metric TEXT PRIMARY KEY,
				value REAL,
				unit TEXT,
				source TEXT,
				region TEXT,
				fetched_at TEXT
			)
			"""
		)
		conn.commit()


def cache_get(key: str, max_age_hours: int = 24) -> str | None:
	init_db()
	with _connect() as conn:
		row = conn.execute(
			"SELECT value, fetched_at FROM cache WHERE key = ?", (key,)
		).fetchone()
	if not row:
		return None

	value, fetched_at = row
	fetched_dt = _parse_iso_utc(fetched_at)
	if fetched_dt is None:
		return None

	if datetime.now(timezone.utc) - fetched_dt > timedelta(hours=max_age_hours):
		return None
	return value


def cache_set(key: str, value: str) -> None:
	init_db()
	with _connect() as conn:
		conn.execute(
			"""
			INSERT INTO cache (key, value, fetched_at)
			VALUES (?, ?, ?)
			ON CONFLICT(key) DO UPDATE SET
				value = excluded.value,
				fetched_at = excluded.fetched_at
			""",
			(key, value, _utcnow_iso()),
		)
		conn.commit()


def cache_clear(key: str | None = None) -> None:
	init_db()
	with _connect() as conn:
		if key is None:
			conn.execute("DELETE FROM cache")
		else:
			conn.execute("DELETE FROM cache WHERE key = ?", (key,))
		conn.commit()


# Returns a prompt-ready snapshot of current market benchmark values.
def get_market_benchmarks() -> str:
	load_dotenv(PROJECT_ROOT / ".env")
	_ = os.getenv("OBSIDIAN_VAULT_PATH")
	_ = os.getenv("EIA_BASE_URL")
	_ = os.getenv("EMBER_BASE_URL")

	init_db()
	with _connect() as conn:
		rows = conn.execute(
			"SELECT metric, value, unit, source, region, fetched_at FROM market_benchmarks"
		).fetchall()

	fallback = (
		"## Current market benchmarks\n"
		"Status: unavailable - using fallback values from niche.md\n"
		"Run db.refresh_benchmarks() to update."
	)

	if not rows:
		return fallback

	now_utc = datetime.now(timezone.utc)
	latest = None
	for row in rows:
		ts = _parse_iso_utc(row[5])
		if ts is not None and (latest is None or ts > latest):
			latest = ts

	if latest is None or (now_utc - latest) > timedelta(days=30):
		return fallback

	by_metric: dict[str, float | None] = {}
	for metric, value, *_rest in rows:
		by_metric[metric] = _to_float(value)

	residential = _format_value(by_metric.get("us_residential_rate_avg"), decimals=2)
	commercial = _format_value(by_metric.get("us_commercial_rate_avg"), decimals=2)
	solar_share = _format_value(by_metric.get("us_solar_generation_share"), decimals=2)
	irradiance = _format_value(
		by_metric.get("us_avg_irradiance_national_mean"), decimals=2
	)
	eu_renewables = _format_value(by_metric.get("eu_renewables_average"), decimals=2)

	return (
		"## Current market benchmarks\n"
		f"Last refreshed: {latest.isoformat()}\n"
		"Source: EIA, Ember Climate, NASA POWER\n\n"
		f"US residential rate average: {residential} ¢/kWh [EIA]\n"
		f"US commercial rate average: {commercial} ¢/kWh [EIA]\n"
		f"US solar generation share: {solar_share}% [EIA]\n"
		f"US avg irradiance (national mean): {irradiance} kWh/m²/day [NASA POWER]\n"
		f"Global renewables average (42 countries): {_format_value(by_metric.get('global_renewables_average'), decimals=2)}% [Ember/Warehouse]"
	)


# Upserts one benchmark record and timestamps it with current UTC.
def set_benchmark(metric: str, value: float, unit: str, source: str, region: str) -> None:
	load_dotenv(PROJECT_ROOT / ".env")

	init_db()
	with _connect() as conn:
		conn.execute(
			"""
			INSERT INTO market_benchmarks (metric, value, unit, source, region, fetched_at)
			VALUES (?, ?, ?, ?, ?, ?)
			ON CONFLICT(metric) DO UPDATE SET
				value = excluded.value,
				unit = excluded.unit,
				source = excluded.source,
				region = excluded.region,
				fetched_at = excluded.fetched_at
			""",
			(metric, float(value), unit, source, region, _utcnow_iso()),
		)
		conn.commit()


def _extract_eia_rates(eia_base_url: str, eia_api_key: str | None) -> tuple[float, float]:
	endpoint = f"{eia_base_url.rstrip('/')}/electricity/retail-sales/data"
	common = {
		"api_key": eia_api_key,
		"frequency": "monthly",
		"data[0]": "price",
		"facets[stateid][]": "US",
		"sort[0][column]": "period",
		"sort[0][direction]": "desc",
		"offset": 0,
		"length": 12,
	}

	res_params = {**common, "facets[sectorid][]": "RES"}
	com_params = {**common, "facets[sectorid][]": "COM"}

	res_resp = requests.get(endpoint, params=res_params, timeout=30)
	com_resp = requests.get(endpoint, params=com_params, timeout=30)
	res_resp.raise_for_status()
	com_resp.raise_for_status()

	res_data = res_resp.json().get("response", {}).get("data", [])
	com_data = com_resp.json().get("response", {}).get("data", [])

	if not res_data or not com_data:
		raise ValueError("EIA rates response did not include expected data rows")

	res_values = [_to_float(item.get("price")) for item in res_data]
	com_values = [_to_float(item.get("price")) for item in com_data]
	res_clean = [v for v in res_values if v is not None]
	com_clean = [v for v in com_values if v is not None]

	if not res_clean or not com_clean:
		raise ValueError("EIA rates response included non-numeric values")

	return sum(res_clean) / len(res_clean), sum(com_clean) / len(com_clean)


def _extract_eia_solar_share(eia_base_url: str, eia_api_key: str | None) -> float:
	endpoint = f"{eia_base_url.rstrip('/')}/electricity/electric-power-operational-data/data"
	common = {
		"api_key": eia_api_key,
		"frequency": "monthly",
		"data[0]": "generation",
		"facets[location][]": "US",
		"sort[0][column]": "period",
		"sort[0][direction]": "desc",
		"offset": 0,
		"length": 12,
	}

	solar_params = {**common, "facets[fueltypeid][]": "SUN"}
	total_params = dict(common)

	solar_resp = requests.get(endpoint, params=solar_params, timeout=30)
	total_resp = requests.get(endpoint, params=total_params, timeout=30)
	solar_resp.raise_for_status()
	total_resp.raise_for_status()

	solar_data = solar_resp.json().get("response", {}).get("data", [])
	total_data = total_resp.json().get("response", {}).get("data", [])

	solar_values = [_to_float(item.get("generation")) for item in solar_data]
	total_values = [_to_float(item.get("generation")) for item in total_data]
	solar_sum = sum(v for v in solar_values if v is not None)
	total_sum = sum(v for v in total_values if v is not None)

	if total_sum <= 0:
		raise ValueError("Unable to compute solar generation share from EIA data")

	return (solar_sum / total_sum) * 100.0


def _extract_nasa_irradiance() -> float:
	endpoint = "https://power.larc.nasa.gov/api/temporal/climatology/point"
	params = {
		"latitude": 38.0,
		"longitude": -97.0,
		"community": "RE",
		"parameters": "ALLSKY_SFC_SW_DWN",
		"format": "JSON",
	}
	response = requests.get(endpoint, params=params, timeout=30)
	response.raise_for_status()
	payload = response.json()
	value = (
		payload.get("properties", {})
		.get("parameter", {})
		.get("ALLSKY_SFC_SW_DWN", {})
		.get("ANN")
	)
	numeric = _to_float(value)
	if numeric is None:
		raise ValueError("NASA POWER response did not include ANN irradiance value")
	return numeric


def _find_first_numeric(obj: Any, keys: tuple[str, ...]) -> float | None:
	if isinstance(obj, dict):
		for key in keys:
			if key in obj:
				val = _to_float(obj.get(key))
				if val is not None:
					return val
		for value in obj.values():
			found = _find_first_numeric(value, keys)
			if found is not None:
				return found
	elif isinstance(obj, list):
		for item in obj:
			found = _find_first_numeric(item, keys)
			if found is not None:
				return found
	return None


def _extract_ember_eu_renewables(ember_base_url: str) -> float:
	"""
	Computes average renewables share across all countries
	in the warehouse ember_generation table.

	Originally intended as EU-only but expanded to all 42 tracked
	countries - provides a more useful global reference benchmark
	for international solar viability comparisons.

	Ember API has no valid EU aggregate entity code so this uses
	the warehouse directly.
	"""
	import sqlite3
	from pathlib import Path

	warehouse_path = (
		Path(__file__).resolve().parent.parent / "verdigris_warehouse.db"
	)
	if not warehouse_path.exists():
		raise FileNotFoundError(
			f"Warehouse not found at {warehouse_path}"
		)

	conn = sqlite3.connect(warehouse_path)
	conn.row_factory = sqlite3.Row
	try:
		cur = conn.execute("""
			SELECT iso3, SUM(share_pct) AS country_renewables
			FROM ember_generation
			WHERE fuel_type IN (
				'solar', 'wind', 'hydro',
				'other_renewables', 'bioenergy'
			)
			AND year = (
				SELECT MAX(year)
				FROM ember_generation
				WHERE iso3 = 'DEU'
			)
			GROUP BY iso3
			HAVING country_renewables IS NOT NULL
		""")
		rows = cur.fetchall()
	finally:
		conn.close()

	if not rows:
		raise ValueError(
			"No generation data found in warehouse"
		)

	country_totals = [row["country_renewables"] for row in rows]
	avg = sum(country_totals) / len(country_totals)
	return round(avg, 2)


def _write_market_benchmarks_markdown(vault_path: str, last_updated: str) -> None:
	with _connect() as conn:
		rows = conn.execute(
			"""
			SELECT metric, value, unit, source
			FROM market_benchmarks
			ORDER BY metric ASC
			"""
		).fetchall()

	lines = [
		"# Market Benchmarks",
		f"Last updated: {last_updated}",
		"",
		"| Metric | Value | Unit | Source |",
		"|---|---|---|---|",
	]
	for metric, value, unit, source in rows:
		lines.append(f"| {metric} | {value} | {unit} | {source} |")

	path = Path(vault_path).expanduser() / "Market-Benchmarks.md"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Refreshes benchmark data from APIs, stores rows, and writes a vault summary.
def refresh_benchmarks() -> dict[str, Any]:
	load_dotenv(PROJECT_ROOT / ".env")
	vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
	eia_base_url = os.getenv("EIA_BASE_URL", "https://api.eia.gov/v2").strip()
	ember_base_url = os.getenv("EMBER_BASE_URL", "https://api.ember-energy.org").strip()
	eia_api_key = os.getenv("EIA_API_KEY", "").strip() or None

	init_db()

	updated = 0
	failed: list[str] = []

	def _attempt(metric_name: str, work) -> None:
		nonlocal updated
		try:
			value = work()
			if value is None:
				raise ValueError("No value returned")
			metric, val, unit, source, region = value
			set_benchmark(metric, float(val), unit, source, region)
			updated += 1
		except Exception as exc:  # noqa: BLE001
			LOGGER.exception("Failed to refresh benchmark %s: %s", metric_name, exc)
			failed.append(metric_name)

	try:
		res_rate, com_rate = _extract_eia_rates(eia_base_url, eia_api_key)
	except Exception as exc:  # noqa: BLE001
		LOGGER.exception("Failed to fetch EIA rates: %s", exc)
		res_rate, com_rate = None, None

	if res_rate is None:
		failed.append("us_residential_rate_avg")
	else:
		_attempt(
			"us_residential_rate_avg",
			lambda: (
				"us_residential_rate_avg",
				res_rate,
				"¢/kWh",
				"EIA",
				"US",
			),
		)

	if com_rate is None:
		failed.append("us_commercial_rate_avg")
	else:
		_attempt(
			"us_commercial_rate_avg",
			lambda: (
				"us_commercial_rate_avg",
				com_rate,
				"¢/kWh",
				"EIA",
				"US",
			),
		)
	_attempt(
		"us_solar_generation_share",
		lambda: (
			"us_solar_generation_share",
			_extract_eia_solar_share(eia_base_url, eia_api_key),
			"%",
			"EIA",
			"US",
		),
	)
	_attempt(
		"us_avg_irradiance_national_mean",
		lambda: (
			"us_avg_irradiance_national_mean",
			_extract_nasa_irradiance(),
			"kWh/m²/day",
			"NASA POWER",
			"US",
		),
	)
	_attempt(
		"global_renewables_average",
		lambda: (
			"global_renewables_average",
			_extract_ember_eu_renewables(ember_base_url),
			"%",
			"Ember",
			"EU",
		),
	)

	try:
		if not vault_path:
			raise ValueError("OBSIDIAN_VAULT_PATH is not set")
		_write_market_benchmarks_markdown(vault_path, _utcnow_iso())
	except Exception as exc:  # noqa: BLE001
		LOGGER.exception("Failed to write market benchmark markdown: %s", exc)
		failed.append("market_benchmarks_markdown")

	return {"updated": updated, "failed": failed}

