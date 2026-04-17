from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGIONS_PATH = PROJECT_ROOT / "config" / "regions.md"

COUNTRY_CENTROIDS = {
    "DE": (51.1657, 10.4515), "GB": (55.3781, -3.4360),
    "FR": (46.2276, 2.2137),  "IT": (41.8719, 12.5674),
    "ES": (40.4637, -3.7492), "AU": (-25.2744, 133.7751),
    "IN": (20.5937, 78.9629), "CN": (35.8617, 104.1954),
    "BR": (-14.2350, -51.9253), "CA": (56.1304, -106.3468),
    "JP": (36.2048, 138.2529), "KR": (35.9078, 127.7669),
    "MX": (23.6345, -102.5528), "ZA": (-30.5595, 22.9375),
    "NG": (9.0820, 8.6753),   "KE": (-0.0236, 37.9062),
    "EG": (26.8206, 30.8025), "MA": (31.7917, -7.0926),
    "SA": (23.8859, 45.0792), "TH": (15.8700, 100.9925),
    "VN": (14.0583, 108.2772), "PH": (12.8797, 121.7740),
    "ID": (-0.7893, 113.9213), "PK": (30.3753, 69.3451),
    "BD": (23.6850, 90.3563), "CL": (-35.6751, -71.5430),
    "CO": (4.5709, -74.2973),  "PE": (-9.1900, -75.0152),
    "NO": (60.4720, 8.4689),  "SE": (60.1282, 18.6435),
    "DK": (56.2639, 9.5018),  "NL": (52.1326, 5.2913),
    "BE": (50.5039, 4.4699),  "AT": (47.5162, 14.5501),
    "PL": (51.9194, 19.1451), "PT": (39.3999, -8.2245),
    "TR": (38.9637, 35.2433), "GH": (7.9465, -1.0232),
    "TZ": (-6.3690, 34.8888), "UG": (1.3733, 32.2903),
    "ET": (9.1450, 40.4897),  "UY": (-32.5228, -55.7658),
}

# ── Module-level cache ────────────────────────────────────────────────────────
_REGIONS: dict | None = None


# ── Public API ────────────────────────────────────────────────────────────────

def resolve(location_input: str) -> dict | list[dict]:
    """
    Resolves any location string to a standard location object.

    Returns a dict for a single location.
    Returns a list[dict] for comma-separated multi-region input.
    Returns {"error": str, "input": str} if unresolvable.
    Never raises an exception.
    """
    if not location_input or not location_input.strip():
        return {"error": "Empty input", "input": location_input}

    # Multi-region: comma-separated
    parts = [p.strip() for p in location_input.split(",") if p.strip()]
    if len(parts) > 1:
        return [_resolve_single(p) for p in parts]

    return _resolve_single(location_input.strip())


# ── Internal resolution ───────────────────────────────────────────────────────

def _resolve_single(input_str: str) -> dict:
    """Resolves one location string. Returns location object or error dict."""
    regions = _load_regions()
    normalized = input_str.strip().lower()

    # 1. U.S. alias → canonical state name
    if normalized in regions["us_aliases"]:
        canonical = regions["us_aliases"][normalized]
        return _build_us_location(canonical, regions)

    # 2. U.S. state — full name or abbreviation
    result = _match_us_state(normalized, regions)
    if result:
        return result

    # 3. International alias → canonical country name
    if normalized in regions["intl_aliases"]:
        canonical = regions["intl_aliases"][normalized]
        return _build_intl_location(canonical, regions)

    # 4. Country — name, ISO2, or ISO3
    result = _match_country(normalized, regions)
    if result:
        return result

    # 5. ZIP code — 5 digits
    if re.fullmatch(r"\d{5}", input_str.strip()):
        return _resolve_zip(input_str.strip(), regions)

    # 6. Unresolvable
    return {"error": f"Could not resolve location: {input_str!r}", "input": input_str}


def _match_us_state(normalized: str, regions: dict) -> dict | None:
    """Match by state name or abbreviation."""
    states = regions["us_states"]

    # By abbreviation (2 letters)
    upper = normalized.upper()
    if upper in states:
        return _build_us_location(states[upper]["name"], regions)

    # By full name
    for abbr, info in states.items():
        if info["name"].lower() == normalized:
            return _build_us_location(info["name"], regions)

    return None


def _match_country(normalized: str, regions: dict) -> dict | None:
    """Match by country name, ISO2, or ISO3."""
    countries = regions["countries"]

    for name, info in countries.items():
        if (name.lower() == normalized
                or info.get("iso2", "").lower() == normalized
                or info.get("iso3", "").lower() == normalized):
            return _build_intl_location(name, regions)

    return None


def _build_us_location(canonical_name: str, regions: dict) -> dict:
    """Build a U.S. state location object."""
    states = regions["us_states"]
    centroids = regions["centroids"]

    # Find state by name
    state_info = None
    for abbr, info in states.items():
        if info["name"].lower() == canonical_name.lower():
            state_info = info
            break

    if not state_info:
        return {"error": f"State data not found for {canonical_name!r}",
                "input": canonical_name}

    abbr = state_info["abbr"]
    centroid = centroids.get(abbr, {})

    return {
        "name": state_info["name"],
        "lat": float(centroid.get("lat", 0)),
        "lon": float(centroid.get("lon", 0)),
        "is_us": True,
        "scope": "state",
        "country": "US",
        "fips": state_info.get("fips"),
        "state_abbr": abbr,
        "region": state_info.get("region"),
        "iso_rto": state_info.get("iso_rto"),
        "pvgis_uncertainty": "n/a",
        "iso3": "USA",
    }


def _build_intl_location(canonical_name: str, regions: dict) -> dict:
    """Build an international country location object."""
    countries = regions["countries"]
    country_info = countries.get(canonical_name)

    if not country_info:
        # Try case-insensitive match
        for name, info in countries.items():
            if name.lower() == canonical_name.lower():
                country_info = info
                canonical_name = name
                break

    if not country_info:
        return {"error": f"Country data not found for {canonical_name!r}",
                "input": canonical_name}

    iso2 = country_info.get("iso2", "")
    uncertainty = regions["pvgis_uncertainty"].get(iso2, "medium")

    # Use centroid from regions if available, otherwise fallback
    centroid = COUNTRY_CENTROIDS.get(iso2, {})

    return {
        "name": canonical_name,
        "lat": float(centroid[0]) if isinstance(centroid, tuple) else 0.0,
        "lon": float(centroid[1]) if isinstance(centroid, tuple) else 0.0,
        "is_us": False,
        "scope": "country",
        "country": iso2,
        "iso2": iso2,
        "iso3": country_info.get("iso3", ""),
        "fips": None,
        "state_abbr": None,
        "region": country_info.get("wb_region"),
        "iso_rto": None,
        "pvgis_uncertainty": uncertainty,
    }


def _resolve_zip(zip_code: str, regions: dict) -> dict:
    """Resolve a U.S. ZIP code using pgeocode."""
    import ssl
    import certifi
    ssl._create_default_https_context = lambda: (
        ssl.create_default_context(cafile=certifi.where())
    )

    try:
        import pgeocode
        nomi = pgeocode.Nominatim("us")
        result = nomi.query_postal_code(zip_code)

        if result is None or str(result.get("state_code", "")) == "nan":
            return {"error": f"ZIP code not found: {zip_code}",
                    "input": zip_code}

        lat = result.get("latitude")
        lon = result.get("longitude")
        state_abbr = str(result.get("state_code", "")).upper()
        place_name = str(result.get("place_name", zip_code))

        if str(lat) == "nan" or str(lon) == "nan":
            return {"error": f"No coordinates for ZIP {zip_code}",
                    "input": zip_code}

        # Look up state info
        states = regions["us_states"]
        state_info = states.get(state_abbr, {})

        return {
            "name": f"{place_name}, {state_abbr} {zip_code}",
            "lat": float(lat),
            "lon": float(lon),
            "is_us": True,
            "scope": "zip",
            "country": "US",
            "fips": state_info.get("fips"),
            "state_abbr": state_abbr,
            "region": state_info.get("region"),
            "iso_rto": state_info.get("iso_rto"),
            "pvgis_uncertainty": "n/a",
            "iso3": "USA",
            "zip_code": zip_code,
        }

    except ImportError:
        return {"error": "pgeocode not installed — run: pip install pgeocode",
                "input": zip_code}
    except Exception as exc:
        LOGGER.warning("ZIP resolution failed for %s: %s", zip_code, exc)
        return {"error": f"ZIP resolution error: {exc}", "input": zip_code}


# ── Regions parser ────────────────────────────────────────────────────────────

def _load_regions() -> dict:
    """
    Parses config/regions.md and returns lookup dictionaries.
    Called once at module import — result cached in _REGIONS.
    """
    global _REGIONS
    if _REGIONS is not None:
        return _REGIONS

    if not REGIONS_PATH.exists():
        LOGGER.error("regions.md not found at %s", REGIONS_PATH)
        _REGIONS = _empty_regions()
        return _REGIONS

    text = REGIONS_PATH.read_text(encoding="utf-8")
    _REGIONS = _parse_regions(text)
    return _REGIONS


def _parse_regions(text: str) -> dict:
    """Parse the regions.md markdown file into lookup dicts."""
    result: dict[str, Any] = {
        "us_states": {},
        "us_aliases": {},
        "countries": {},
        "intl_aliases": {},
        "centroids": {},
        "intl_centroids": {},
        "pvgis_uncertainty": {},
        "iso_rto_map": {},
    }

    lines = text.splitlines()
    current_section = None

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if "U.S. States" in stripped and "Name to FIPS" in stripped:
            current_section = "us_states"
            continue
        elif "U.S. Common Aliases" in stripped:
            current_section = "us_aliases"
            continue
        elif "International Countries" in stripped and "Name to ISO" in stripped:
            current_section = "countries"
            continue
        elif "International Common Aliases" in stripped:
            current_section = "intl_aliases"
            continue
        elif "State Centroids" in stripped:
            current_section = "centroids"
            continue
        elif "PVGIS Uncertainty" in stripped:
            current_section = "pvgis_uncertainty"
            continue
        elif "U.S. Utility Territories" in stripped or "ISO" in stripped and "RTO" in stripped:
            current_section = "iso_rto"
            continue
        elif "U.S. Region Groupings" in stripped:
            current_section = "region_groupings"
            continue

        # Skip non-table lines
        if not stripped.startswith("|") or stripped.startswith("| ---") or stripped.startswith("|---"):
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]

        if current_section == "us_states" and len(cells) >= 5:
            name, abbr, fips, area, region = (
                cells[0], cells[1], cells[2], cells[3], cells[4]
            )
            if name and abbr and fips and name != "State Name":
                result["us_states"][abbr.upper()] = {
                    "name": name,
                    "abbr": abbr.upper(),
                    "fips": fips.zfill(2),
                    "area_sq_mi": area,
                    "region": region,
                    "iso_rto": None,
                }

        elif current_section == "us_aliases" and len(cells) >= 2:
            alias, canonical = cells[0], cells[1]
            if alias and canonical and alias != "Input":
                result["us_aliases"][alias.lower()] = canonical

        elif current_section == "countries" and len(cells) >= 5:
            name, iso2, iso3, region, wb_region = (
                cells[0], cells[1], cells[2], cells[3], cells[4]
            )
            if name and iso2 and iso3 and name != "Country Name":
                result["countries"][name] = {
                    "iso2": iso2.upper(),
                    "iso3": iso3.upper(),
                    "region": region,
                    "wb_region": wb_region,
                }

        elif current_section == "intl_aliases" and len(cells) >= 2:
            alias, canonical = cells[0], cells[1]
            if alias and canonical and alias != "Input":
                result["intl_aliases"][alias.lower()] = canonical

        elif current_section == "centroids" and len(cells) >= 3:
            state, lat, lon = cells[0], cells[1], cells[2]
            if state and lat and state != "State":
                try:
                    result["centroids"][state.upper()] = {
                        "lat": float(lat),
                        "lon": float(lon),
                    }
                except ValueError:
                    pass

        elif current_section == "pvgis_uncertainty" and len(cells) >= 3:
            region_name, countries_str, uncertainty = (
                cells[0], cells[1], cells[2]
            )
            if region_name and uncertainty and region_name != "Region":
                # Map each country ISO2 in the list
                for iso2 in re.findall(r"\b[A-Z]{2}\b", countries_str):
                    result["pvgis_uncertainty"][iso2] = (
                        uncertainty.lower().replace("-", "_")
                    )

        elif current_section == "iso_rto" and len(cells) >= 2:
            iso_rto, states_str = cells[0], cells[1]
            if iso_rto and states_str and iso_rto != "ISO/RTO":
                for abbr in re.findall(r"\b[A-Z]{2}\b", states_str):
                    if abbr in result["us_states"]:
                        result["us_states"][abbr]["iso_rto"] = iso_rto

    # Build reverse lookups for aliases already pointing to canonical names
    # Ensure alias map values point to existing state names
    validated_aliases: dict[str, str] = {}
    state_names_lower = {
        info["name"].lower(): info["name"]
        for info in result["us_states"].values()
    }
    for alias, canonical in result["us_aliases"].items():
        canon_lower = canonical.lower()
        if canon_lower in state_names_lower:
            validated_aliases[alias] = state_names_lower[canon_lower]
    result["us_aliases"] = validated_aliases

    # Validate intl aliases point to existing countries
    validated_intl: dict[str, str] = {}
    country_names_lower = {n.lower(): n for n in result["countries"]}
    for alias, canonical in result["intl_aliases"].items():
        canon_lower = canonical.lower()
        if canon_lower in country_names_lower:
            validated_intl[alias] = country_names_lower[canon_lower]
    result["intl_aliases"] = validated_intl

    LOGGER.info(
        "Regions loaded: %d states, %d countries, %d US aliases, "
        "%d intl aliases, %d centroids",
        len(result["us_states"]),
        len(result["countries"]),
        len(result["us_aliases"]),
        len(result["intl_aliases"]),
        len(result["centroids"]),
    )
    return result


def _empty_regions() -> dict:
    return {
        "us_states": {}, "us_aliases": {}, "countries": {},
        "intl_aliases": {}, "centroids": {}, "intl_centroids": {},
        "pvgis_uncertainty": {}, "iso_rto_map": {},
    }