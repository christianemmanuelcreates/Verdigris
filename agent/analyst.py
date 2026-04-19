from __future__ import annotations

import json
import logging
import os
from typing import Optional
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from data.location import resolve
from data.nasa import get_irradiance
from data.eia import get_rates
from data.intl_rates import get_current_rate as get_intl_rate
from data.pvwatts import get_output as pvwatts_output
from data.census import get_demographics
from data.warehouse import get_country_profile, get_schema_description, query
from data.db import get_market_benchmarks
from models.solar_score import score as solar_score
from models.demand import forecast as demand_forecast

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

VALID_REPORT_TYPES = {
    "solar_viability",
    "demand_forecast",
    "market_comparison",
    "rate_roi",
    "executive_summary",
}

# Token budget — truncate context before sending to LLM
MAX_PROMPT_TOKENS = 6_000


class FindingItem(BaseModel):
    title: str = ""
    number: str = ""
    benchmark: str = ""
    driver: str = ""
    implication: str = ""
    constraint: str = ""
    plain_english: str = ""


class DataQuality(BaseModel):
    benchmark_status: str = "unavailable"
    sources_used: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    anomalies_detected: list[str] = Field(default_factory=list)


class AnalystFindings(BaseModel):
    location: str = ""
    report_type: str = ""
    headline: str = ""
    findings: list[FindingItem] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    sources: list[str] = Field(default_factory=list)


def run(location_input: str, report_type: str) -> dict:
    """
    Full analyst pipeline:
    1. Resolve location
    2. Fetch data (connectors + warehouse)
    3. Run models
    4. Build and send prompt to LLM
    5. Parse and validate findings package

    Returns a findings package dict matching the schema in
    config/prompts/analyst.md.
    Returns an error dict if the pipeline fails.
    """
    if report_type not in VALID_REPORT_TYPES:
        return {
            "error": f"Invalid report type: {report_type!r}. "
                     f"Valid types: {sorted(VALID_REPORT_TYPES)}"
        }

    # Resolve location
    location_obj = resolve(location_input)

    # Handle multi-region input
    if isinstance(location_obj, list):
        return _run_multi_region(location_obj, report_type)

    if "error" in location_obj:
        return {"error": f"Location resolution failed: {location_obj['error']}"}

    if report_type == "demand_forecast":
        scope = location_obj.get("scope", "")
        is_us = location_obj.get("is_us", False)
        if not is_us:
            return {
                "error": (
                    "Demand forecast is only available for "
                    "U.S. states. This location resolved as "
                    "international. Try a U.S. state name instead."
                )
            }
        if scope in ("zip", "city"):
            state = location_obj.get("state_abbr", "")
            state_name = location_obj.get("name", location_obj.get("state_abbr", ""))
            return {
                "error": (
                    f"Demand forecast requires a U.S. state, "
                    f"not a city or ZIP code. "
                    f"Try '{state_name}' or '{state}' instead."
                )
            }
        if not location_obj.get("state_abbr"):
            return {
                "error": (
                    "Could not resolve this location to a U.S. state. "
                    "Demand forecast requires a full state name like "
                    "'Texas', 'California', or 'New York'."
                )
            }

    # Fetch data and run models
    data_package = _fetch_data(location_obj, report_type)

    # Build prompt and call LLM
    prompt = build_analyst_prompt(data_package, report_type)
    findings = _call_llm(prompt)

    if findings is None:
        return {"error": "LLM call failed — check OPENROUTER_API_KEY and model availability"}

    # Inject raw connector and model data for vault enrichment
    # Allows vault.py to write PVWatts output and other metrics to notes
    if "error" not in findings:
        findings["connectors"] = data_package.get("connectors", {})
        findings["models"] = data_package.get("models", {})
        findings["is_us"] = location_obj.get("is_us", True)

    return findings


def _run_multi_region(locations: list[dict], report_type: str) -> list[dict]:
    """Runs the full pipeline for each location in a multi-region input."""
    results = []
    for loc in locations:
        if "error" in loc:
            results.append(loc)
            continue
        data_package = _fetch_data(loc, report_type)
        prompt = build_analyst_prompt(data_package, report_type)
        findings = _call_llm(prompt)
        if findings:
            results.append(findings)
        else:
            results.append({"error": f"LLM failed for {loc['name']}"})
    return results


def _fetch_data(location_obj: dict, report_type: str) -> dict:
    """
    Fetches all data needed for this location and report type.
    Routes U.S. vs international based on is_us flag.
    Each connector fails independently — never crashes the pipeline.
    """
    is_us = location_obj.get("is_us", True)
    lat = location_obj.get("lat", 0)
    lon = location_obj.get("lon", 0)
    name = location_obj.get("name", "Unknown")

    data: dict = {
        "location": location_obj,
        "report_type": report_type,
        "connectors": {},
        "models": {},
    }

    # NASA irradiance — always, both U.S. and international
    try:
        data["connectors"]["nasa"] = get_irradiance(lat, lon)
    except Exception as exc:
        LOGGER.error("NASA connector failed for %s: %s", name, exc)
        data["connectors"]["nasa"] = {"error": str(exc)}

    if is_us:
        state_abbr = location_obj.get("state_abbr", "")
        fips = location_obj.get("fips", "")

        # EIA rates
        try:
            data["connectors"]["eia"] = get_rates(state_abbr)
        except Exception as exc:
            LOGGER.error("EIA connector failed for %s: %s", name, exc)
            data["connectors"]["eia"] = {"error": str(exc)}

        # PVWatts solar output
        try:
            data["connectors"]["pvwatts"] = pvwatts_output(lat, lon)
        except Exception as exc:
            LOGGER.error("PVWatts connector failed for %s: %s", name, exc)
            data["connectors"]["pvwatts"] = {"error": str(exc)}

        # Census demographics
        try:
            data["connectors"]["census"] = get_demographics(fips)
        except Exception as exc:
            LOGGER.error("Census connector failed for %s: %s", name, exc)
            data["connectors"]["census"] = {"error": str(exc)}

        # Historical rates from warehouse
        if state_abbr:
            try:
                rate_trend = query(f"""
                    SELECT period, rate_cents_kwh
                    FROM eia_rates
                    WHERE state_abbr = '{state_abbr}'
                      AND sector = 'residential'
                    ORDER BY period DESC
                    LIMIT 24
                """)
                data["connectors"]["eia_trend"] = rate_trend
            except Exception as exc:
                LOGGER.warning("Warehouse rate trend failed: %s", exc)

        # Models
        irr = data["connectors"].get("nasa", {})
        eia = data["connectors"].get("eia", {})
        census = data["connectors"].get("census", {})

        # Solar viability score
        if report_type in ("solar_viability", "market_comparison", "rate_roi",
                           "executive_summary"):
            try:
                score_inputs = {
                    "irradiance": irr.get("annual_avg_kwh_m2_day", 0) or 0,
                    "rate": eia.get("residential_cents_kwh", 0) or 0,
                    "density": census.get("density_per_sq_mi", 0) or 0,
                }
                data["models"]["solar_score"] = solar_score(score_inputs)
            except Exception as exc:
                LOGGER.error("Solar score model failed: %s", exc)
                data["models"]["solar_score"] = {"error": str(exc)}

        # Demand forecast
        if report_type in ("demand_forecast", "executive_summary"):
            if state_abbr:
                try:
                    data["models"]["demand"] = demand_forecast(state_abbr)
                except Exception as exc:
                    LOGGER.error("Demand forecast failed: %s", exc)
                    data["models"]["demand"] = {"error": str(exc)}

    else:
        # International path — warehouse replaces EIA + Census
        iso2 = location_obj.get("country", "")
        iso3 = location_obj.get("iso3", "")

        try:
            data["connectors"]["country_profile"] = get_country_profile(iso2, iso3)

            # International electricity rate
            try:
                data["connectors"]["intl_rate"] = get_intl_rate(iso2)
            except Exception as exc:
                LOGGER.error("intl_rate failed for %s: %s", name, exc)
                data["connectors"]["intl_rate"] = {"error": str(exc)}
        except Exception as exc:
            LOGGER.error("Country profile failed for %s: %s", name, exc)
            data["connectors"]["country_profile"] = {"error": str(exc)}

        # Solar score for international — irradiance + approximate rate proxy
        if report_type in ("solar_viability", "market_comparison", "executive_summary"):
            try:
                irr = data["connectors"].get("nasa", {})
                profile = data["connectors"].get("country_profile", {})
                # Use kWh_per_capita as density proxy (scaled)
                kwh_pc = profile.get("kwh_per_capita") or 0
                density_proxy = min(kwh_pc / 10, 5000)  # rough scaling

                intl_rate = data["connectors"].get("intl_rate", 0)
                if isinstance(intl_rate, dict):
                    rate_val = intl_rate.get("rate_cents_kwh") or 0
                else:
                    rate_val = intl_rate or 0
                score_inputs = {
                    "irradiance": irr.get("annual_avg_kwh_m2_day", 0) or 0,
                    "rate": rate_val,
                    "density": density_proxy,
                }
                data["models"]["solar_score"] = solar_score(score_inputs)
                if rate_val == 0:
                    data["models"]["solar_score"]["intl_rate_unavailable"] = True
            except Exception as exc:
                LOGGER.error("International solar score failed: %s", exc)
                data["models"]["solar_score"] = {"error": str(exc)}

    return data


def build_analyst_prompt(data_package: dict, report_type: str) -> str:
    """
    Assembles the full prompt for the analyst LLM call.

    Layer 1: config/niche.md — domain knowledge and identity
    Layer 2: db.get_market_benchmarks() — live benchmark injection
    Layer 3: warehouse.get_schema_description() — SQL access description
    Layer 4: config/prompts/analyst.md — reasoning instructions
    Layer 5: data_package — location data and model outputs

    Enforces 6,000 token budget. Truncates layer 5 first if needed.
    """
    niche = _load_config("niche.md")
    instructions = _load_config("prompts/analyst.md")
    benchmarks = get_market_benchmarks()
    warehouse_schema = get_schema_description()

    data_str = json.dumps(data_package, indent=2, default=str)

    # Check token budget — truncate data if needed
    base_tokens = _count_tokens(niche + instructions + benchmarks + warehouse_schema)
    data_tokens = _count_tokens(data_str)

    if base_tokens + data_tokens > MAX_PROMPT_TOKENS:
        # Truncate data_str to fit budget
        available = MAX_PROMPT_TOKENS - base_tokens - 200  # 200 buffer
        chars_allowed = max(500, int(available / 1.3))
        data_str = data_str[:chars_allowed] + "\n... [data truncated for token budget]"
        LOGGER.warning(
            "Prompt truncated — data was %d tokens, budget allows %d",
            data_tokens, available
        )

    return f"""{niche}

---

## Current market benchmarks
{benchmarks}

---

## Warehouse schema (available for SQL queries)
{warehouse_schema}

---

## Your task

Report type: {report_type}

Location data and model outputs:
{data_str}

---

{instructions}"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    reraise=False
)
def _call_llm(prompt: str) -> dict | None:
    """
    Sends the prompt to OpenRouter and returns the parsed findings package.
    Returns None if the call fails.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("MODEL_ANALYST", "anthropic/claude-sonnet-4-5")

    if not api_key:
        LOGGER.error("OPENROUTER_API_KEY not set in .env")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://viridiansociety.com",
        "X-Title": "Verdigris",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are the Verdigris analyst agent. Follow all instructions in the prompt exactly. Return only valid JSON matching the output schema."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.5,
    }

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except requests.RequestException as exc:
        LOGGER.error("OpenRouter request failed: %s", exc)
        return None
    except (KeyError, IndexError) as exc:
        LOGGER.error("Unexpected OpenRouter response structure: %s", exc)
        return None

    return _parse_findings(content)


def _parse_findings(content: str) -> dict | None:
    """
    Parses LLM output into a findings package dict.
    Handles JSON wrapped in markdown code fences.
    Returns None if parsing fails.
    """
    import re

    cleaned = content.strip()


    # Strip markdown code fences — handles ```json, ```python, ``` etc.
    cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```$', '', cleaned)
    cleaned = cleaned.strip()

    # Try direct parse first
    try:
        findings = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object from surrounding text
        match = re.search(r'\{[\s\S]+\}', cleaned)
        if match:
            try:
                findings = json.loads(match.group())
            except json.JSONDecodeError:
                LOGGER.error("Could not parse LLM output as JSON")
                LOGGER.debug("Raw content: %s", content[:500])
                return None
        else:
            LOGGER.error("No JSON object found in LLM output")
            LOGGER.debug("Raw content: %s", content[:500])
            return None

    # Validate required keys
    required = {"location", "report_type", "headline", "findings",
                "data_quality", "sources"}
    missing = required - set(findings.keys())
    if missing:
        LOGGER.warning("Findings package missing keys: %s", missing)
        for key in missing:
            if key == "findings":
                findings[key] = []
            elif key == "data_quality":
                findings[key] = {
                    "benchmark_status": "unavailable",
                    "sources_used": [],
                    "limitations": [],
                    "anomalies_detected": [],
                }
            elif key == "sources":
                findings[key] = []
            else:
                findings[key] = "unavailable"

    data = findings
    try:
        validated = AnalystFindings(**data)
        return validated.model_dump()
    except Exception as e:
        LOGGER.warning("Pydantic validation failed: %s", e)
        return data  # fall back to raw dict


def _load_config(filename: str) -> str:
    """
    Loads a file from config/ directory.
    filename may include subdirectory: e.g. "prompts/analyst.md"
    """
    path = PROJECT_ROOT / "config" / filename
    if not path.exists():
        LOGGER.error("Config file not found: %s", path)
        return f"[Config file missing: {filename}]"
    return path.read_text(encoding="utf-8")


def _count_tokens(text: str) -> int:
    """Rough token estimate: words * 1.3. Good enough for budget enforcement."""
    return int(len(text.split()) * 1.3)