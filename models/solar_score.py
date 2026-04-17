from __future__ import annotations


# Normalization ranges — based on U.S. and global solar market data
# Irradiance: 2.0 (cloudy northern climates) to 7.0 (desert Southwest/MENA)
# Rate: 5 (cheapest markets) to 30 (most expensive markets) cents/kWh
#        Higher rate = higher score — better solar economics
# Density: 0 to 5,000 people per sq mile
#           Higher density = larger addressable market

IRRADIANCE_MIN = 2.0
IRRADIANCE_MAX = 7.0

RATE_MIN = 5.0
RATE_MAX = 30.0

DENSITY_MIN = 0.0
DENSITY_MAX = 5_000.0

# Weights must sum to 1.0
WEIGHT_IRRADIANCE = 0.40
WEIGHT_RATE = 0.35
WEIGHT_DENSITY = 0.25

# Score labels
LABELS = [
    (80, "Exceptional market"),
    (65, "Strong market"),
    (50, "Viable market"),
    (35, "Marginal market"),
    (0,  "Weak market"),
]


def score(inputs: dict) -> dict:
    """
    Composite solar viability index 0–100.

    Combines irradiance, electricity rate, and population density
    into a single score using normalized weighted components.

    Higher electricity rates score higher because they indicate
    stronger solar economics — faster payback, better ROI.

    inputs = {
        "irradiance": float,   # kWh/m²/day — from NASA POWER
        "rate": float,         # cents/kWh residential — from EIA
        "density": float       # people per sq mile — from Census
    }

    Returns:
    {
        "score": float,
        "label": str,
        "irradiance_component": float,
        "rate_component": float,
        "density_component": float,
        "inputs": dict,
        "interpretation": str,
        "weights": dict
    }
    """
    irradiance = float(inputs.get("irradiance", 0))
    rate = float(inputs.get("rate", 0))
    density = float(inputs.get("density", 0))

    # Normalize each input to 0–100
    irr_norm = _normalize(irradiance, IRRADIANCE_MIN, IRRADIANCE_MAX)
    rate_norm = _normalize(rate, RATE_MIN, RATE_MAX)
    den_norm = _normalize(density, DENSITY_MIN, DENSITY_MAX)

    # Weighted composite
    raw_score = (
        irr_norm * WEIGHT_IRRADIANCE
        + rate_norm * WEIGHT_RATE
        + den_norm * WEIGHT_DENSITY
    )

    final_score = round(min(100.0, max(0.0, raw_score)), 1)

    # Component scores (weighted contribution, 0–100 scale each)
    irr_component = round(irr_norm * WEIGHT_IRRADIANCE, 1)
    rate_component = round(rate_norm * WEIGHT_RATE, 1)
    den_component = round(den_norm * WEIGHT_DENSITY, 1)

    label = _get_label(final_score)
    interpretation = _build_interpretation(
        final_score, label, irradiance, rate, density,
        irr_norm, rate_norm, den_norm
    )

    return {
        "score": final_score,
        "label": label,
        "irradiance_component": irr_component,
        "rate_component": rate_component,
        "density_component": den_component,
        "inputs": {
            "irradiance_kwh_m2_day": irradiance,
            "rate_cents_kwh": rate,
            "density_per_sq_mi": density,
        },
        "interpretation": interpretation,
        "weights": {
            "irradiance": WEIGHT_IRRADIANCE,
            "rate": WEIGHT_RATE,
            "density": WEIGHT_DENSITY,
        },
    }


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Clamps and normalizes a value to 0–100."""
    if max_val <= min_val:
        return 0.0
    clamped = max(min_val, min(max_val, value))
    return ((clamped - min_val) / (max_val - min_val)) * 100.0


def _get_label(score_val: float) -> str:
    """Returns the label for a given score."""
    for threshold, label in LABELS:
        if score_val >= threshold:
            return label
    return "Weak market"


def _build_interpretation(
    score_val: float,
    label: str,
    irradiance: float,
    rate: float,
    density: float,
    irr_norm: float,
    rate_norm: float,
    den_norm: float,
) -> str:
    """
    Builds a plain-English interpretation identifying the primary
    driver and the primary constraint.
    """
    # Identify primary driver (highest normalized component)
    components = {
        "solar resource": irr_norm,
        "electricity rate": rate_norm,
        "population density": den_norm,
    }
    driver = max(components, key=components.get)
    constraint = min(components, key=components.get)

    # Build driver sentence
    driver_map = {
        "solar resource": f"strong irradiance of {irradiance:.1f} kWh/m²/day",
        "electricity rate": f"high electricity rate of {rate:.1f} ¢/kWh",
        "population density": f"dense addressable market of {density:,.0f} people/sq mi",
    }
    constraint_map = {
        "solar resource": f"moderate irradiance of {irradiance:.1f} kWh/m²/day",
        "electricity rate": f"low electricity rate of {rate:.1f} ¢/kWh limits ROI",
        "population density": f"thin addressable market of {density:,.0f} people/sq mi",
    }

    return (
        f"{label}. Driven by {driver_map[driver]}. "
        f"Primary constraint: {constraint_map[constraint]}."
    )