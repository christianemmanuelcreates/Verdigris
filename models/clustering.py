"""
Verdigris — Market Intelligence Models
models/clustering.py

Four models operating on a shared feature matrix extracted from
vault reports and warehouse data. All designed to answer the three
questions a solar sales team actually needs:

  1. WHERE to go      → K-Means clustering + opportunity score
  2. WHAT drives it   → Linear regression coefficients
  3. GO or NO-GO      → Decision tree rules

All four models return plain-English explanations alongside numbers.
No ML background required to interpret the output.

Public API:
    build_feature_matrix(reports)       → FeatureMatrix
    run_full_market_analysis(location)  → dict
    run_kmeans(fm)                      → KMeansResult
    run_regression(fm)                  → RegressionResult
    compute_lcoe_table(target_lf)       → LCOEResult
    compute_rate_trajectory(location)   → RateTrajectoryResult
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

LOGGER = logging.getLogger(__name__)

# ── Feature schema ────────────────────────────────────────────────────────────

FEATURES = [
    "irradiance",       # kWh/m²/day — natural solar resource
    "rate_cents_kwh",   # residential electricity rate — financial driver
    "density",          # people/sq mi — lead density / canvassing ROI
    "viability_score",  # 0–100 composite — overall market quality
    "payback_years",    # estimated simple payback — customer decision ease
]

FEATURE_LABELS = {
    "irradiance":       "Solar resource (kWh/m²/day)",
    "rate_cents_kwh":   "Electricity rate (¢/kWh)",
    "density":          "Population density (/sq mi)",
    "viability_score":  "Viability score (/100)",
    "payback_years":    "Payback period (years)",
}

# Opportunity score weights — tuned for residential solar sales
# Rate and viability are highest leverage; density drives canvassing ROI
OPPORTUNITY_WEIGHTS = {
    "irradiance":       0.15,
    "rate_cents_kwh":   0.30,
    "density":          0.20,
    "viability_score":  0.25,
    "payback_years":    0.10,   # inverted — lower payback = higher score
}

# Cluster labels by profile
CLUSTER_PROFILES = [
    "Premium residential",    # high rate, moderate sun
    "High-volume sun belt",   # high sun, moderate rate
    "Emerging market",        # moderate on all dimensions
    "Price-sensitive",        # low rate, high density
    "International high-rate", # very high rate, lower sun
]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class LocationFeatures:
    name:           str
    irradiance:     float = 0.0
    rate_cents_kwh: float = 0.0
    density:        float = 0.0
    viability_score:float = 0.0
    payback_years:  float = 0.0
    report_type:    str   = ""
    report_date:    str   = ""

    def to_array(self) -> np.ndarray:
        return np.array([
            self.irradiance,
            self.rate_cents_kwh,
            self.density,
            self.viability_score,
            self.payback_years,
        ], dtype=float)

    def is_valid(self) -> bool:
        """Returns True if we have enough data to cluster."""
        return (
            self.irradiance > 0
            and self.rate_cents_kwh > 0
            and self.viability_score > 0
        )


@dataclass
class FeatureMatrix:
    locations:  list[LocationFeatures]
    X:          np.ndarray          # shape (n, len(FEATURES))
    X_scaled:   np.ndarray          # normalized 0–1 per feature
    names:      list[str]
    target_idx: int = -1            # index of the query location


@dataclass
class KMeansResult:
    labels:         np.ndarray
    n_clusters:     int
    target_cluster: int
    similar:        list[dict]      # other locations in same cluster
    cluster_profile:str
    explanation:    str


@dataclass
class RegressionResult:
    coefficients:   dict[str, float]
    r_squared:      float
    top_driver:     str
    explanation:    str


@dataclass
class LCOEResult:
    rows_res: list[dict]         # residential rows with ITC
    rows_res_noitc: list[dict]   # residential rows without ITC
    rows_com: list[dict]         # commercial rows
    rows: list[dict]             # kept for backward compat = rows_res
    lcoe_cents_kwh: float        # 8kW residential with ITC
    lcoe_cents_kwh_noitc: float  # 8kW residential without ITC
    break_even_rate: float
    is_us: bool
    explanation: str


@dataclass
class RateTrajectoryResult:
    historical: dict[int, float]   # {year: residential_cents}
    historical_com: dict[int, float]  # {year: commercial_cents}
    projected: dict[int, float]    # {year: projected_cents}
    cagr: float
    crisis_year: int | None
    source: str
    lcoe_reference: float          # horizontal line on chart
    explanation: str


# ── Feature extraction ────────────────────────────────────────────────────────

def extract_features_from_report(report: dict) -> LocationFeatures | None:
    """
    Extracts LocationFeatures from a vault report dict.
    Report dict must have 'content', 'location', 'type', 'date' keys.
    Returns None if insufficient data.
    """
    text     = report.get("content", "")
    location = report.get("location", report.get("name", ""))
    rtype    = report.get("type", "")
    rdate    = report.get("date", "")

    lf = LocationFeatures(name=location, report_type=rtype, report_date=rdate)

    # Irradiance
    m = re.search(r"(\d+\.?\d*)\s*kWh/m[²2]/day", text)
    if m:
        lf.irradiance = float(m.group(1))

    # Rate — ¢/kWh
    m = re.search(r"(\d+\.?\d*)\s*(?:¢/kWh|cents/kWh)", text)
    if m:
        lf.rate_cents_kwh = float(m.group(1))

    # Density
    m = re.search(
        r"(\d[\d,]+)\s*(?:per sq mi|/sq mi|per square mile|people per sq)",
        text, re.IGNORECASE
    )
    if m:
        lf.density = float(m.group(1).replace(",", ""))

    # Viability score — handles multiple formats:
    # "65.6/100", "65.6 / 100", "65.6 out of 100",
    # "score: 65.6", "| 65.6 | /100 |"
    m = re.search(
        r"(\d+\.?\d*)\s*(?:/\s*100|out\s+of\s+100)", text, re.IGNORECASE
    )
    if not m:
        # Table format: | 65.6 | /100 |
        m = re.search(
            r"\|\s*(\d+\.?\d*)\s*\|\s*/100\s*\|", text
        )
    if not m:
        # "viability score of 65.6" or "score of 65.6"
        m = re.search(
            r"viability score (?:of\s+)?[*_]*(\d+\.?\d*)", 
            text, re.IGNORECASE
        )
    if m:
        val = float(m.group(1))
        if 0 < val <= 100:
            lf.viability_score = val

    # Payback years
    m = re.search(
        r"(\d+\.?\d*)\s*(?:year|yr)s?\s*(?:payback|simple payback)",
        text, re.IGNORECASE
    )
    if not m:
        m = re.search(
            r"payback\s+(?:period|in|of)?\s*(?:is\s*)?(\d+\.?\d*)\s*(?:year|yr)",
            text, re.IGNORECASE
        )
    if m:
        lf.payback_years = float(m.group(1))
    elif lf.rate_cents_kwh > 0 and lf.irradiance > 0:
        # Estimate payback from rate + irradiance if not explicit
        annual_kwh = lf.irradiance * 365 * 4 * 0.75
        annual_savings = annual_kwh * (lf.rate_cents_kwh / 100)
        if annual_savings > 0:
            lf.payback_years = round(8_400 / annual_savings, 1)

    return lf if lf.is_valid() else None


def build_feature_matrix(
    reports: list[dict],
    target_location: str = "",
) -> FeatureMatrix | None:
    """
    Builds a normalized feature matrix from vault report dicts.

    Args:
        reports:         List of report dicts from get_vault_reports()
        target_location: If provided, marks this location as the query target

    Returns:
        FeatureMatrix or None if fewer than 3 valid locations
    """
    locations = []
    for r in reports:
        lf = extract_features_from_report(r)
        if lf:
            locations.append(lf)

    # Deduplicate by name — keep highest viability score
    seen: dict[str, LocationFeatures] = {}
    for lf in locations:
        key = lf.name.lower().strip()
        if key not in seen or lf.viability_score > seen[key].viability_score:
            seen[key] = lf
    locations = list(seen.values())

    if len(locations) < 3:
        LOGGER.warning("Need at least 3 valid locations for clustering")
        return None

    X = np.array([lf.to_array() for lf in locations], dtype=float)

    # Min-max normalize each feature to 0–1
    X_min = X.min(axis=0)
    X_max = X.max(axis=0)
    X_range = np.where(X_max - X_min > 0, X_max - X_min, 1.0)
    X_scaled = (X - X_min) / X_range

    # Invert payback (lower is better → higher scaled score)
    payback_idx = FEATURES.index("payback_years")
    X_scaled[:, payback_idx] = 1.0 - X_scaled[:, payback_idx]

    names = [lf.name for lf in locations]
    target_idx = -1
    if target_location:
        tl = target_location.lower().strip()
        for i, n in enumerate(names):
            if tl in n.lower() or n.lower() in tl:
                target_idx = i
                break

    return FeatureMatrix(
        locations=locations,
        X=X,
        X_scaled=X_scaled,
        names=names,
        target_idx=target_idx,
    )


# ── Model 1 — K-Means Clustering ─────────────────────────────────────────────

def run_kmeans(fm: FeatureMatrix, n_clusters: int = 5) -> KMeansResult:
    """
    K-Means clustering on normalized feature matrix.

    Finds which cluster the target location belongs to, then returns
    the other members of that cluster ranked by viability score.

    Plain-English interpretation is generated from cluster centroid
    characteristics — no ML jargon in the output.
    """
    from sklearn.cluster import KMeans

    n = len(fm.locations)
    k = min(n_clusters, max(2, n // 2))

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(fm.X_scaled)

    target_cluster = int(labels[fm.target_idx]) if fm.target_idx >= 0 else 0

    # Find similar markets in same cluster
    similar = []
    for i, lf in enumerate(fm.locations):
        if i == fm.target_idx:
            continue
        if labels[i] == target_cluster:
            similar.append({
                "name":           lf.name,
                "viability":      lf.viability_score,
                "rate":           lf.rate_cents_kwh,
                "irradiance":     lf.irradiance,
                "payback_years":  lf.payback_years,
            })

    similar.sort(key=lambda x: -x["viability"])

    # Characterize the cluster from its centroid
    centroid = km.cluster_centers_[target_cluster]
    profile  = _characterize_cluster(centroid, fm)

    # Plain-English explanation
    target_name = fm.names[fm.target_idx] if fm.target_idx >= 0 else "the target"
    similar_names = ", ".join(s["name"] for s in similar[:4]) if similar else "none yet"

    explanation = _kmeans_explanation(
        target_name, k, target_cluster, profile, similar, fm
    )

    return KMeansResult(
        labels=labels,
        n_clusters=k,
        target_cluster=target_cluster,
        similar=similar,
        cluster_profile=profile,
        explanation=explanation,
    )


def _characterize_cluster(centroid: np.ndarray, fm: FeatureMatrix) -> str:
    """Returns a plain-English profile of a cluster from its centroid."""
    # centroid is in normalized 0-1 space
    rate_idx = FEATURES.index("rate_cents_kwh")
    irr_idx  = FEATURES.index("irradiance")
    den_idx  = FEATURES.index("density")

    rate_c = centroid[rate_idx]
    irr_c  = centroid[irr_idx]
    den_c  = centroid[den_idx]

    if rate_c > 0.65:
        return "High-rate premium market"
    elif irr_c > 0.65 and rate_c < 0.45:
        return "High-sun, price-sensitive market"
    elif den_c > 0.65:
        return "Dense urban market"
    elif rate_c > 0.45 and irr_c > 0.45:
        return "Balanced growth market"
    else:
        return "Emerging or marginal market"


def _kmeans_explanation(
    target: str,
    k: int,
    cluster: int,
    profile: str,
    similar: list[dict],
    fm: FeatureMatrix,
) -> str:
    lines = [
        f"## K-Means Clustering — {target}",
        f"*{len(fm.locations)} markets analyzed, {k} clusters identified*\n",
        f"**How it works:** Each market is described by 5 features: solar "
        f"resource, electricity rate, population density, viability score, "
        f"and payback period. K-Means groups markets by similarity across "
        f"all five dimensions simultaneously — not just one metric.\n",
        f"**{target}** falls in **Cluster {cluster + 1}** — "
        f"profile: _{profile}_\n",
    ]

    if similar:
        lines.append(
            "**Structurally similar markets** "
            "(same cluster, ranked by viability):\n"
        )
        lines.append(
            "| Market | Viability | Rate (¢/kWh) | Irradiance | Payback |"
        )
        lines.append("|--------|-----------|-------------|------------|---------|")
        for s in similar[:6]:
            pb = f"{s['payback_years']:.1f}yr" if s["payback_years"] else "—"
            lines.append(
                f"| {s['name']} | {s['viability']:.0f}/100 | "
                f"{s['rate']:.1f} | {s['irradiance']:.2f} | {pb} |"
            )
        lines.append("")
        if similar:
            top = similar[0]
            lines.append(
                f"**Deployment insight:** {top['name']} is the highest-viability "
                f"market structurally similar to {target}. If crew performance "
                f"is strong in {target}, {top['name']} should be the next "
                f"expansion target."
            )
    else:
        lines.append(
            f"_{target} is currently the only market in this cluster. "
            f"Run more reports in similar geographies to populate the comparison._"
        )

    return "\n".join(lines)


# ── Model 2 — Linear Regression ──────────────────────────────────────────────

def run_regression(fm: FeatureMatrix) -> RegressionResult:
    """
    OLS linear regression: features → viability score.

    Tells you which single variable most explains viability variance
    across your analyzed portfolio. Useful for understanding whether
    your best markets are rate-driven or resource-driven.
    """
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import StandardScaler

    vi_idx = FEATURES.index("viability_score")

    # X = all features except viability, y = viability
    feature_cols = [i for i in range(len(FEATURES)) if i != vi_idx]
    feature_names = [FEATURES[i] for i in feature_cols]

    X = fm.X[:, feature_cols]
    y = fm.X[:, vi_idx]

    if len(X) < 3:
        return RegressionResult(
            coefficients={}, r_squared=0.0,
            top_driver="insufficient data",
            explanation="Need at least 3 markets to run regression."
        )

    scaler = StandardScaler()
    X_std = scaler.fit_transform(X)

    model = LinearRegression()
    model.fit(X_std, y)
    r2 = float(model.score(X_std, y))

    coefs = {
        name: float(coef)
        for name, coef in zip(feature_names, model.coef_)
    }

    # Top driver by absolute coefficient
    top_driver = max(coefs, key=lambda k: abs(coefs[k]))
    top_label  = FEATURE_LABELS.get(top_driver, top_driver)

    explanation = _regression_explanation(coefs, r2, top_driver, top_label, fm)

    return RegressionResult(
        coefficients=coefs,
        r_squared=r2,
        top_driver=top_driver,
        explanation=explanation,
    )


def compute_lcoe_table(
    target_lf: "LocationFeatures",
    is_us: bool = True,
    commercial_rate: float | None = None,
) -> LCOEResult:
    """
    Computes LCOE and 25-year NPV for three system sizes.
    Uses industry-standard assumptions documented in code.
    """
    SYSTEM_LIFETIME = 25       # years
    DEGRADATION_RATE = 0.005   # 0.5%/year industry standard
    DISCOUNT_RATE = 0.05       # 5% NPV discount rate
    COST_PER_KW = 3000         # USD installed cost per kW
    ITC = 0.30 if is_us else 0.0  # 30% federal tax credit (US only)
    PANEL_EFFICIENCY = 0.80    # system derate factor

    irradiance = target_lf.irradiance
    res_rate = target_lf.rate_cents_kwh / 100  # convert to $/kWh
    com_rate = (commercial_rate / 100) if commercial_rate else res_rate * 0.65

    system_sizes = [
        {"kw": 4,   "label": "4 kW (small residential)",   "sector": "residential"},
        {"kw": 8,   "label": "8 kW (standard residential)", "sector": "residential"},
        {"kw": 12,  "label": "12 kW (large residential)",   "sector": "residential"},
        {"kw": 50,  "label": "50 kW (small commercial)",    "sector": "commercial"},
        {"kw": 250, "label": "250 kW (mid commercial)",     "sector": "commercial"},
        {"kw": 500, "label": "500 kW (large commercial)",   "sector": "commercial"},
    ]

    rows = []
    lcoe_8kw = 0.0

    for sys in system_sizes:
        kw = sys["kw"]
        gross_cost = kw * COST_PER_KW
        net_cost = gross_cost * (1 - ITC)

        # Annual output with degradation series
        annual_kwh_base = irradiance * 365 * kw * PANEL_EFFICIENCY
        total_kwh = sum(
            annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr)
            for yr in range(SYSTEM_LIFETIME)
        )

        lcoe = (net_cost / total_kwh) * 100  # cents/kWh

        # Annual savings (year 1, residential)
        annual_kwh_y1 = annual_kwh_base
        annual_savings_res = annual_kwh_y1 * res_rate
        annual_savings_com = annual_kwh_y1 * com_rate

        # Payback
        payback_res = net_cost / annual_savings_res if annual_savings_res else 99
        payback_com = net_cost / annual_savings_com if annual_savings_com else 99

        # 10-year ROI (residential)
        ten_yr_savings = sum(
            annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr) * res_rate
            for yr in range(10)
        )
        roi_10yr = ((ten_yr_savings - net_cost) / net_cost) * 100

        # 25-year NPV (residential)
        npv = -net_cost
        for yr in range(1, SYSTEM_LIFETIME + 1):
            yr_kwh = annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr)
            yr_savings = yr_kwh * res_rate
            npv += yr_savings / ((1 + DISCOUNT_RATE) ** yr)

        # 25-year NPV (commercial)
        npv_com = -net_cost
        for yr in range(1, SYSTEM_LIFETIME + 1):
            yr_kwh = annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr)
            yr_savings = yr_kwh * com_rate
            npv_com += yr_savings / ((1 + DISCOUNT_RATE) ** yr)

        sector = sys.get("sector", "residential")
        is_commercial = sector == "commercial"

        # No ITC variant (net cost = gross cost)
        net_cost_noitc = gross_cost
        lcoe_noitc = (net_cost_noitc / total_kwh) * 100
        payback_noitc = (
            net_cost_noitc / annual_savings_res
            if annual_savings_res else 99
        )
        npv_noitc = -net_cost_noitc
        for yr in range(1, SYSTEM_LIFETIME + 1):
            yr_kwh = annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr)
            npv_noitc += (yr_kwh * res_rate) / ((1 + DISCOUNT_RATE) ** yr)

        if kw == 8 and not is_commercial:
            lcoe_8kw = round(lcoe, 2)
            lcoe_8kw_noitc = round(lcoe_noitc, 2)

        # Primary savings for this sector
        primary_rate = com_rate if is_commercial else res_rate
        annual_savings_primary = round(annual_kwh_y1 * primary_rate)
        payback_primary = round(
            net_cost / annual_savings_primary
            if annual_savings_primary else 99, 1
        )
        npv_primary = -net_cost
        for yr in range(1, SYSTEM_LIFETIME + 1):
            yr_kwh = annual_kwh_base * ((1 - DEGRADATION_RATE) ** yr)
            npv_primary += (yr_kwh * primary_rate) / ((1 + DISCOUNT_RATE) ** yr)

        row_data = {
            "system":              sys["label"],
            "kw":                  kw,
            "sector":              sector,
            "gross_cost":          gross_cost,
            "net_cost":            round(net_cost),
            "net_cost_noitc":      round(net_cost_noitc),
            "itc_savings":         round(gross_cost - net_cost),
            "lcoe":                round(lcoe, 2),
            "lcoe_noitc":          round(lcoe_noitc, 2),
            "annual_kwh":          round(annual_kwh_y1),
            "annual_savings_res":  round(annual_savings_res),
            "annual_savings_com":  round(annual_savings_com),
            "annual_savings_primary": annual_savings_primary,
            "payback_res":         round(payback_res, 1),
            "payback_com":         round(payback_com, 1),
            "payback_primary":     payback_primary,
            "payback_noitc":       round(payback_noitc, 1),
            "roi_10yr":            round(roi_10yr, 1),
            "npv_25yr_res":        round(npv),
            "npv_25yr_com":        round(npv_com),
            "npv_25yr_primary":    round(npv_primary),
            "npv_25yr_noitc":      round(npv_noitc),
        }
        rows.append(row_data)

    # Break-even rate: grid rate at which LCOE = grid cost
    # LCOE is fixed cost of solar — when grid rises to meet it,
    # solar reaches parity
    break_even = lcoe_8kw  # cents/kWh

    rows_res     = [r for r in rows if r["sector"] == "residential"]
    rows_res_noitc = rows_res  # same rows, noitc fields already present
    rows_com     = [r for r in rows if r["sector"] == "commercial"]
    lcoe_8kw_noitc = lcoe_8kw_noitc if 'lcoe_8kw_noitc' in dir() else lcoe_8kw

    vs_grid = res_rate * 100 - lcoe_8kw
    if vs_grid > 0:
        verdict = (
            f"Solar is **{vs_grid:.1f}¢/kWh cheaper** than "
            f"grid at current rates."
        )
    elif vs_grid > -5:
        verdict = (
            f"Solar LCOE ({lcoe_8kw:.1f}¢) is near grid parity "
            f"({res_rate*100:.1f}¢). Economics improve as rates rise."
        )
    else:
        deficit = abs(vs_grid)
        verdict = (
            f"Solar LCOE ({lcoe_8kw:.1f}¢) exceeds current grid "
            f"rate ({res_rate*100:.1f}¢) by {deficit:.1f}¢. "
            f"Solar becomes cost-competitive when grid rate "
            f"exceeds {break_even:.1f}¢/kWh."
        )

    itc_note = (
        " (after 30% federal ITC)" if is_us
        else " (no ITC applied — international market)"
    )

    explanation = (
        f"## LCOE & System Economics\n\n"
        f"**Levelized Cost of Energy (LCOE):** {lcoe_8kw:.1f}¢/kWh"
        f"{itc_note}\n\n"
        f"{verdict}\n\n"
        f"*Assumptions: {SYSTEM_LIFETIME}-year system life, "
        f"{DEGRADATION_RATE*100:.1f}%/year degradation, "
        f"{DISCOUNT_RATE*100:.0f}% discount rate, "
        f"${COST_PER_KW:,}/kW installed cost.*\n\n"
    )

    return LCOEResult(
        rows_res=rows_res,
        rows_res_noitc=rows_res_noitc,
        rows_com=rows_com,
        rows=rows_res,
        lcoe_cents_kwh=lcoe_8kw,
        lcoe_cents_kwh_noitc=lcoe_8kw_noitc,
        break_even_rate=break_even,
        is_us=is_us,
        explanation=explanation,
    )


def compute_rate_trajectory(
    location_name: str,
    is_us: bool,
    state_abbr: str | None = None,
    iso2: str | None = None,
) -> RateTrajectoryResult:
    """
    Computes historical and projected electricity rate trajectory.
    U.S.: uses EIA warehouse data (eia_rates table).
    EU/EEA: calls Eurostat live API via intl_rates.
    Non-EU international: uses verified static CAGR table.
    """
    import sqlite3 as _sqlite3
    from data.warehouse import WAREHOUSE_PATH
    from data.intl_rates import get_intl_rate_history

    historical_res: dict[int, float] = {}
    historical_com: dict[int, float] = {}
    cagr = 3.0
    crisis_year = None
    source = "Estimated"

    if is_us and state_abbr:
        # Query EIA warehouse for annual averages
        try:
            import sqlite3 as _sqlite3
            from data.warehouse import WAREHOUSE_PATH
            conn = _sqlite3.connect(WAREHOUSE_PATH)
            rows = conn.execute(
                """
                SELECT substr(period, 1, 4) as yr,
                                             AVG(rate_cents_kwh) as avg_price
                FROM eia_rates
                WHERE state_abbr = ?
                                    AND sector = 'residential'
                  AND period >= '2015-01'
                GROUP BY yr
                ORDER BY yr
                """,
                (state_abbr.upper(),)
            ).fetchall()
            conn.close()
            if rows:
                historical_res = {
                    int(r[0]): round(r[1], 2)
                    for r in rows if r[1]
                }
                source = "EIA retail sales data"
        except Exception as exc:
            LOGGER.warning("EIA warehouse query failed: %s", exc)

        # Commercial from warehouse
        try:
            import sqlite3 as _sqlite3
            from data.warehouse import WAREHOUSE_PATH
            conn = _sqlite3.connect(WAREHOUSE_PATH)
            rows_com = conn.execute(
                """
                SELECT substr(period, 1, 4) as yr,
                                             AVG(rate_cents_kwh) as avg_price
                FROM eia_rates
                WHERE state_abbr = ?
                                    AND sector = 'commercial'
                  AND period >= '2015-01'
                GROUP BY yr
                ORDER BY yr
                """,
                (state_abbr.upper(),)
            ).fetchall()
            conn.close()
            if rows_com:
                historical_com = {
                    int(r[0]): round(r[1], 2)
                    for r in rows_com if r[1]
                }
        except Exception as exc:
            LOGGER.warning("EIA commercial warehouse query failed: %s", exc)

    else:
        # International
        code = iso2 or "US"
        hist = get_intl_rate_history(code)
        historical_res = hist.get("residential", {})
        historical_com = hist.get("commercial", {})
        cagr = hist.get("cagr_res", 3.0)
        crisis_year = hist.get("crisis_year")
        source = hist.get("source", "Estimated")

    # Compute CAGR from historical if U.S.
    if is_us and len(historical_res) >= 2:
        years = sorted(historical_res.keys())
        start = historical_res[years[0]]
        end   = historical_res[years[-1]]
        n_yrs = years[-1] - years[0]
        if start > 0 and n_yrs > 0:
            cagr = round(
                ((end / start) ** (1 / n_yrs) - 1) * 100, 2
            )

    # Project 10 years forward from last known year
    projected: dict[int, float] = {}
    if historical_res:
        last_year = max(historical_res.keys())
        last_rate = historical_res[last_year]
        # Use post-crisis stabilized CAGR for EU markets
        proj_cagr = min(cagr, 5.0) / 100  # cap at 5% for projections
        for yr in range(last_year + 1, last_year + 11):
            years_fwd = yr - last_year
            projected[yr] = round(
                last_rate * ((1 + proj_cagr) ** years_fwd), 2
            )

    # Get LCOE reference (will be set by caller from LCOEResult)
    lcoe_reference = 0.0

    # Build explanation
    if historical_res:
        years = sorted(historical_res.keys())
        first_rate = historical_res[years[0]]
        last_rate  = historical_res[max(years)]
        last_year  = max(years)
        proj_5yr   = projected.get(last_year + 5, last_rate)
        proj_10yr  = projected.get(last_year + 10, last_rate)

        crisis_note = ""
        if crisis_year:
            crisis_note = (
                f"\n\n> **Note:** The {crisis_year} energy crisis "
                f"caused a sharp spike in rates. The projection uses "
                f"a stabilized CAGR based on pre- and post-crisis "
                f"trends rather than the spike peak."
            )

        explanation = (
            f"## Rate Trajectory Analysis\n\n"
            f"**Historical CAGR ({years[0]}–{last_year}):** "
            f"{cagr:.1f}%/year\n\n"
            f"| Year | Residential | Commercial |\n"
            f"|------|-------------|------------|\n"
            f"| {years[0]} | {first_rate:.1f}¢ | "
            f"{historical_com.get(years[0], first_rate*0.65):.1f}¢ |\n"
            f"| {last_year} | {last_rate:.1f}¢ | "
            f"{historical_com.get(last_year, last_rate*0.65):.1f}¢ |\n"
            f"| {last_year+5}* | {proj_5yr:.1f}¢ | "
            f"{proj_5yr*0.65:.1f}¢ |\n"
            f"| {last_year+10}* | {proj_10yr:.1f}¢ | "
            f"{proj_10yr*0.65:.1f}¢ |\n\n"
            f"*Projected at {min(cagr, 5.0):.1f}% CAGR "
            f"(capped at 5% for conservative projection)*\n\n"
            f"**Source:** {source}"
            f"{crisis_note}"
        )
    else:
        explanation = (
            "## Rate Trajectory Analysis\n\n"
            "Historical rate data not available for this location."
        )

    return RateTrajectoryResult(
        historical=historical_res,
        historical_com=historical_com,
        projected=projected,
        cagr=cagr,
        crisis_year=crisis_year,
        source=source,
        lcoe_reference=lcoe_reference,
        explanation=explanation,
    )


def _regression_explanation(
    coefs: dict,
    r2: float,
    top_driver: str,
    top_label: str,
    fm: FeatureMatrix,
) -> str:
    sorted_coefs = sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True)
    r2_pct = r2 * 100

    lines = [
        f"## Linear Regression — What Drives Viability?",
        f"*{len(fm.locations)} markets, R² = {r2:.2f} "
        f"({r2_pct:.0f}% of variance explained)*\n",
        f"**How it works:** Regression fits a straight line through your "
        f"portfolio data to measure how much each feature — rate, sun, "
        f"density, payback — independently predicts the viability score. "
        f"Larger coefficients = stronger influence.\n",
        f"**Feature importance** (standardized coefficients):\n",
        "| Feature | Coefficient | Direction | Interpretation |",
        "|---------|------------|-----------|----------------|",
    ]

    for fname, coef in sorted_coefs:
        label    = FEATURE_LABELS.get(fname, fname)
        direction = "↑ increases score" if coef > 0 else "↓ decreases score"
        strength = (
            "Strong" if abs(coef) > 8 else
            "Moderate" if abs(coef) > 4 else
            "Weak"
        )
        lines.append(
            f"| {label} | {coef:+.2f} | {direction} | {strength} influence |"
        )

    lines.append("")

    top_coef = coefs[top_driver]
    direction_word = "higher" if top_coef > 0 else "lower"

    lines.extend([
        f"**Key finding:** {top_label} is the strongest driver of viability "
        f"in your analyzed portfolio. Markets with {direction_word} "
        f"{top_label.split('(')[0].strip().lower()} tend to score "
        f"{'better' if top_coef > 0 else 'worse'}.\n",
        f"**Sales implication:** "
    ])

    if top_driver == "rate_cents_kwh":
        lines.append(
            "Your best markets are **rate-driven**. Prioritize states and ZIPs "
            "with above-average electricity prices — that's where the ROI story "
            "is easiest to tell and fastest to close."
        )
    elif top_driver == "irradiance":
        lines.append(
            "Your best markets are **resource-driven**. Sun belt locations "
            "dominate your portfolio. Rate improvements in these markets "
            "would compound returns significantly."
        )
    elif top_driver == "density":
        lines.append(
            "Your best markets are **density-driven**. Dense urban markets "
            "are producing the best outcomes — canvassing ROI is high and "
            "lead volume offsets lower per-deal margins."
        )
    else:
        lines.append(
            f"{top_label} is the primary lever. Focus marketing spend "
            "on markets where this metric is favorable."
        )

    return "\n".join(lines)


# ── Unified analysis entry point ──────────────────────────────────────────────

def run_full_market_analysis(
    location: str,
    vault_reports: list[dict] | None = None,
) -> dict:
    """
    Runs all four models for a given location and returns both
    Markdown output and raw model result objects.

    This is the primary entry point called from search.py and app.py.

    Args:
        location:      Location name to analyze (must be in vault)
        vault_reports: Optional pre-loaded report list. If None, loads
                       from vault automatically.

    Returns:
        Dict containing markdown_report, target metrics, raw model data,
        and market count.
    """
    if vault_reports is None:
        vault_reports = _load_vault_reports_direct()

    if not vault_reports:
        return {
            "markdown_report": (
                "No vault reports found. Run DEMO_SEED.py first to populate "
                "the knowledge base, then retry this analysis."
            ),
            "target": None,
            "data": {
                "kmeans": None,
                "regression": None,
                "decision_tree": None,
                "opportunity": None,
            },
            "n_markets": 0,
        }

    LOGGER.info("CLUSTERING ── reports received: %d", len(vault_reports))

    fm = build_feature_matrix(vault_reports, target_location=location)
    LOGGER.info("CLUSTERING ── feature matrix: %s locations, target_idx: %s",
                len(fm.locations) if fm else 0,
                fm.target_idx if fm else "None")

    if fm is None:
        return {
            "markdown_report": (
                f"Insufficient data for market analysis. Need at least 3 reports "
                f"with extractable metrics (irradiance, rate, viability score)."
            ),
            "target": None,
            "data": {
                "kmeans": None,
                "regression": None,
                "decision_tree": None,
                "opportunity": None,
            },
            "n_markets": 0,
        }

    if fm.target_idx < 0:
        available = ", ".join(fm.names[:8])
        return {
            "markdown_report": (
                f"Location '{location}' not found in vault. "
                f"Available markets: {available}..."
            ),
            "target": None,
            "data": {
                "kmeans": None,
                "regression": None,
                "decision_tree": None,
                "opportunity": None,
            },
            "n_markets": len(fm.locations),
        }

    n = len(fm.locations)
    target_name = fm.names[fm.target_idx]
    target_lf   = fm.locations[fm.target_idx]

    # Header
    sections = [
        f"# Market Intelligence Analysis — {target_name}",
        f"*{n} markets in portfolio · "
        f"Rate: {target_lf.rate_cents_kwh:.1f}¢/kWh · "
        f"Irradiance: {target_lf.irradiance:.2f} kWh/m²/day · "
        f"Score: {target_lf.viability_score:.0f}/100*",
        "",
        "---",
        "",
    ]

    # Run all four models
    try:
        km_result = run_kmeans(fm)
        LOGGER.info("CLUSTERING ── kmeans complete: %d clusters", km_result.n_clusters)
        sections.append(km_result.explanation)
        sections.append("\n---\n")
    except Exception as e:
        LOGGER.error("K-Means failed: %s", e)
        sections.append(f"*K-Means clustering unavailable: {e}*\n---\n")

    try:
        reg_result = run_regression(fm)
        LOGGER.info("CLUSTERING ── regression complete: R²=%.2f", reg_result.r_squared)
        sections.append(reg_result.explanation)
        sections.append("\n---\n")
    except Exception as e:
        LOGGER.error("Regression failed: %s", e)
        sections.append(f"*Regression unavailable: {e}*\n---\n")

    # Determine location metadata for new models
    from data.location import resolve as _resolve
    _loc_meta = _resolve(location) or {}
    _is_us    = _loc_meta.get("is_us", False)
    _state    = _loc_meta.get("state_abbr")
    _iso2     = _loc_meta.get("iso2")

    try:
        lcoe_result = compute_lcoe_table(
            target_lf,
            is_us=_is_us,
        )
        LOGGER.info("CLUSTERING ── LCOE complete: %.1f¢/kWh",
                    lcoe_result.lcoe_cents_kwh)
        sections.append(lcoe_result.explanation)
        sections.append("\n---\n")
    except Exception as e:
        LOGGER.error("LCOE failed: %s", e)
        lcoe_result = None
        sections.append(f"*LCOE unavailable: {e}*\n---\n")

    try:
        traj_result = compute_rate_trajectory(
            location_name=target_name,
            is_us=_is_us,
            state_abbr=_state,
            iso2=_iso2,
        )
        if lcoe_result:
            traj_result.lcoe_reference = lcoe_result.lcoe_cents_kwh
        LOGGER.info("CLUSTERING ── trajectory complete: CAGR=%.1f%%",
                    traj_result.cagr)
        sections.append(traj_result.explanation)
    except Exception as e:
        LOGGER.error("Rate trajectory failed: %s", e)
        traj_result = None
        sections.append(f"*Rate trajectory unavailable: {e}*")

    return {
        "markdown_report": "\n".join(sections),
        "target": {
            "name":           target_name,
            "rate":           target_lf.rate_cents_kwh,
            "irradiance":     target_lf.irradiance,
            "viability":      target_lf.viability_score,
            "payback_years":  target_lf.payback_years,
            "density":        target_lf.density,
            "is_us":          _is_us,
            "state_abbr":     _state,
            "iso2":           _iso2,
        },
        "data": {
            "kmeans":          km_result if 'km_result' in dir() else None,
            "regression":      reg_result if 'reg_result' in dir() else None,
            "lcoe":            lcoe_result if 'lcoe_result' in dir() else None,
            "rate_trajectory": traj_result if 'traj_result' in dir() else None,
        },
        "n_markets": len(fm.locations),
        "_fm_locations": fm.locations,
    }


def _load_vault_reports_direct() -> list[dict]:
    """Fallback: load vault reports without importing app.py."""
    import os
    from pathlib import Path as _Path
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_Path(__file__).resolve().parent.parent / ".env")
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    # Strip surrounding quotes if present (dotenv edge case)
    vault_path = vault_path.strip("'\"")
    if not vault_path:
        return []
    reports_dir = Path(vault_path) / "Reports"
    if not reports_dir.exists():
        return []
    reports = []
    for p in reports_dir.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            loc  = re.search(r"^location:\s*(.+)$", text, re.MULTILINE)
            rt   = re.search(r"^report_type:\s*(.+)$", text, re.MULTILINE)
            rd   = re.search(r"^date:\s*(.+)$", text, re.MULTILINE)
            reports.append({
                "filename": p.name,
                "path":     str(p),
                "location": loc.group(1).strip() if loc else p.stem,
                "type":     rt.group(1).strip() if rt else "unknown",
                "date":     rd.group(1).strip() if rd else "",
                "content":  text,
            })
        except Exception:
            continue
    return reports