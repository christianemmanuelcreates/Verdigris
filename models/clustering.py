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
    run_decision_tree(fm)               → DecisionTreeResult
    score_opportunity(fm)               → OpportunityResult
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
class DecisionTreeResult:
    rules:          list[str]       # plain-English go/no-go rules
    target_passes:  bool
    explanation:    str


@dataclass
class OpportunityResult:
    scores:         list[dict]      # all locations with scores
    target_score:   float
    target_rank:    int
    recommendation: str
    explanation:    str


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


# ── Model 3 — Decision Tree Rules ────────────────────────────────────────────

def run_decision_tree(fm: FeatureMatrix) -> DecisionTreeResult:
    """
    Decision tree trained to classify markets as viable (score >= 50)
    or not viable (score < 50).

    Extracts human-readable go/no-go rules that a rep can memorize.
    Threshold of 50 is configurable — represents 'worth deploying crew'.
    """
    from sklearn.tree import DecisionTreeClassifier, export_text

    VIABILITY_THRESHOLD = 50

    vi_idx = FEATURES.index("viability_score")
    feature_cols = [i for i in range(len(FEATURES)) if i != vi_idx]
    feature_names_clean = [FEATURES[i] for i in feature_cols]

    X = fm.X[:, feature_cols]
    y = (fm.X[:, vi_idx] >= VIABILITY_THRESHOLD).astype(int)

    if len(X) < 4 or y.sum() < 1 or (1 - y).sum() < 1:
        # Not enough examples of both classes
        return DecisionTreeResult(
            rules=["Insufficient data — need markets above and below 50/100"],
            target_passes=False,
            explanation=_dt_insufficient(fm),
        )

    dt = DecisionTreeClassifier(max_depth=3, min_samples_leaf=2, random_state=42)
    dt.fit(X, y)

    # Extract rules
    rules = _extract_dt_rules(dt, feature_names_clean, fm.X, feature_cols)

    # Evaluate target
    target_passes = False
    if fm.target_idx >= 0:
        x_target = fm.X[fm.target_idx, feature_cols].reshape(1, -1)
        target_passes = bool(dt.predict(x_target)[0] == 1)

    explanation = _dt_explanation(rules, target_passes, fm, VIABILITY_THRESHOLD)

    return DecisionTreeResult(
        rules=rules,
        target_passes=target_passes,
        explanation=explanation,
    )


def _extract_dt_rules(
    dt,
    feature_names: list[str],
    X: np.ndarray,
    feature_cols: list[int],
) -> list[str]:
    """Converts decision tree splits into plain-English rules."""
    from sklearn.tree import _tree

    tree_ = dt.tree_
    feature_name = [
        FEATURE_LABELS.get(feature_names[i], feature_names[i])
        if feature_names[i] != _tree.TREE_UNDEFINED else "undefined"
        for i in tree_.feature
    ]

    rules = []

    def recurse(node, depth, conditions):
        if tree_.feature[node] == _tree.TREE_UNDEFINED:
            # Leaf node
            class_counts = tree_.value[node][0]
            predicted = int(np.argmax(class_counts))
            confidence = class_counts[predicted] / class_counts.sum()
            if predicted == 1 and conditions:
                rule = " AND ".join(conditions)
                rules.append(
                    f"GO: If {rule} → viable "
                    f"({confidence*100:.0f}% confidence)"
                )
            elif predicted == 0 and conditions:
                rule = " AND ".join(conditions)
                rules.append(
                    f"NO-GO: If {rule} → not viable "
                    f"({confidence*100:.0f}% confidence)"
                )
            return

        fname    = feature_name[node]
        thresh   = tree_.threshold[node]

        recurse(node + 1, depth + 1,
                conditions + [f"{fname} ≤ {thresh:.1f}"])
        recurse(tree_.children_right[node], depth + 1,
                conditions + [f"{fname} > {thresh:.1f}"])

    recurse(0, 0, [])
    return rules[:6]  # Cap at 6 rules for readability


def _dt_insufficient(fm: FeatureMatrix) -> str:
    below = sum(1 for lf in fm.locations if lf.viability_score < 50)
    above = sum(1 for lf in fm.locations if lf.viability_score >= 50)
    return (
        f"## Decision Tree Rules\n\n"
        f"Need markets on both sides of the 50/100 viability threshold "
        f"to extract go/no-go rules.\n\n"
        f"Current portfolio: {above} viable markets, {below} below threshold.\n"
        f"Run more reports in marginal markets to enable rule extraction."
    )


def _dt_explanation(
    rules: list[str],
    target_passes: bool,
    fm: FeatureMatrix,
    threshold: int,
) -> str:
    target_name = fm.names[fm.target_idx] if fm.target_idx >= 0 else "target"
    verdict     = "PASSES" if target_passes else "DOES NOT PASS"
    verdict_sym = "✓" if target_passes else "✗"
    rec         = (
        "Worth deploying crew — economics support it."
        if target_passes else
        "Not recommended for crew deployment at current rates. "
        "Monitor for rate increases."
    )

    lines = [
        f"## Decision Tree — Go/No-Go Rules",
        f"*Trained on {len(fm.locations)} markets, "
        f"viability threshold: {threshold}/100*\n",
        f"**How it works:** A decision tree learns which combinations of "
        f"rate, sun, and density separate your viable markets (score ≥ {threshold}) "
        f"from marginal ones. The rules below can be memorized by any rep "
        f"— no laptop required in the field.\n",
        f"**Learned rules from your portfolio:**\n",
    ]

    for rule in rules:
        prefix = "🟢" if rule.startswith("GO") else "🔴"
        lines.append(f"{prefix} {rule}")

    lines.extend([
        f"\n**{target_name} verdict:** {verdict_sym} {verdict}",
        f"_{rec}_",
    ])

    return "\n".join(lines)


# ── Model 4 — Opportunity Scoring ────────────────────────────────────────────

def score_opportunity(fm: FeatureMatrix) -> OpportunityResult:
    """
    Transparent weighted composite score for crew deployment ranking.

    Unlike the ML models above, this is an auditable formula — no black box.
    Weights are tuned for residential solar sales and documented in code.
    Managers can adjust weights in OPPORTUNITY_WEIGHTS at top of file.
    """
    scores = []

    for i, lf in enumerate(fm.locations):
        row = fm.X_scaled[i]

        # Payback is already inverted in X_scaled (lower payback = higher score)
        weighted = (
            row[FEATURES.index("irradiance")]     * OPPORTUNITY_WEIGHTS["irradiance"] +
            row[FEATURES.index("rate_cents_kwh")] * OPPORTUNITY_WEIGHTS["rate_cents_kwh"] +
            row[FEATURES.index("density")]         * OPPORTUNITY_WEIGHTS["density"] +
            row[FEATURES.index("viability_score")] * OPPORTUNITY_WEIGHTS["viability_score"] +
            row[FEATURES.index("payback_years")]   * OPPORTUNITY_WEIGHTS["payback_years"]
        )

        scores.append({
            "name":           lf.name,
            "opp_score":      round(weighted * 100, 1),
            "viability":      lf.viability_score,
            "rate":           lf.rate_cents_kwh,
            "irradiance":     lf.irradiance,
            "payback_years":  lf.payback_years,
        })

    scores.sort(key=lambda x: -x["opp_score"])

    target_score = 0.0
    target_rank  = -1
    target_name  = fm.names[fm.target_idx] if fm.target_idx >= 0 else ""

    if fm.target_idx >= 0:
        for rank, s in enumerate(scores, 1):
            if s["name"] == target_name:
                target_score = s["opp_score"]
                target_rank  = rank
                break

    recommendation = _opp_recommendation(target_score, target_rank, len(scores))
    explanation    = _opp_explanation(scores, target_name, target_score,
                                       target_rank, recommendation)

    return OpportunityResult(
        scores=scores,
        target_score=target_score,
        target_rank=target_rank,
        recommendation=recommendation,
        explanation=explanation,
    )


def _opp_recommendation(score: float, rank: int, total: int) -> str:
    pct = rank / total if total > 0 else 1.0
    if pct <= 0.20:
        return "Priority market — assign full crew, maximum marketing spend"
    elif pct <= 0.40:
        return "Strong candidate — assign crew, standard marketing"
    elif pct <= 0.60:
        return "Test market — assign 1 crew, measure performance before scaling"
    elif pct <= 0.80:
        return "Monitor — not ready for crew deployment, watch rate trends"
    else:
        return "Low priority — reassign resources to higher-ranked markets"


def _opp_explanation(
    scores: list[dict],
    target: str,
    target_score: float,
    target_rank: int,
    recommendation: str,
) -> str:
    n = len(scores)
    lines = [
        f"## Opportunity Scoring — Deployment Ranking",
        f"*{n} markets scored, weights: "
        f"rate 30% · viability 25% · density 20% · "
        f"irradiance 15% · payback 10%*\n",
        f"**How it works:** Each market receives a 0–100 score from a "
        f"weighted formula. Unlike the other models, this formula is fully "
        f"transparent — you can see exactly why each market ranks where it does. "
        f"Weights are tuned for residential solar sales economics.\n",
        f"**Full market ranking:**\n",
        "| Rank | Market | Opp Score | Viability | Rate (¢) | Payback |",
        "|------|--------|-----------|-----------|----------|---------|",
    ]

    for i, s in enumerate(scores[:15], 1):
        marker  = " ◀" if s["name"] == target else ""
        pb_str  = f"{s['payback_years']:.1f}yr" if s["payback_years"] else "—"
        lines.append(
            f"| {i} | {s['name']}{marker} | {s['opp_score']} | "
            f"{s['viability']:.0f}/100 | {s['rate']:.1f} | {pb_str} |"
        )

    if n > 15:
        lines.append(f"| ... | _{n - 15} more markets_ | | | | |")

    if target and target_rank > 0:
        lines.extend([
            f"\n**{target}:** Rank {target_rank} of {n} "
            f"(score: {target_score:.1f}/100)",
            f"**Recommendation:** {recommendation}",
        ])

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
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from app import get_vault_reports
            vault_reports = get_vault_reports()
        except Exception:
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

    try:
        dt_result = run_decision_tree(fm)
        LOGGER.info("CLUSTERING ── decision tree complete: %d rules", len(dt_result.rules))
        sections.append(dt_result.explanation)
        sections.append("\n---\n")
    except Exception as e:
        LOGGER.error("Decision tree failed: %s", e)
        sections.append(f"*Decision tree unavailable: {e}*\n---\n")

    try:
        opp_result = score_opportunity(fm)
        LOGGER.info("CLUSTERING ── opportunity complete: %d scores", len(opp_result.scores))
        sections.append(opp_result.explanation)
    except Exception as e:
        LOGGER.error("Opportunity scoring failed: %s", e)
        sections.append(f"*Opportunity scoring unavailable: {e}*")

    return {
        "markdown_report": "\n".join(sections),
        "target": {
            "name":           target_name,
            "rate":           target_lf.rate_cents_kwh,
            "irradiance":     target_lf.irradiance,
            "viability":      target_lf.viability_score,
            "payback_years":  target_lf.payback_years,
            "density":        target_lf.density,
        },
        "data": {
            "kmeans":        km_result if 'km_result' in dir() else None,
            "regression":    reg_result if 'reg_result' in dir() else None,
            "decision_tree": dt_result if 'dt_result' in dir() else None,
            "opportunity":   opp_result if 'opp_result' in dir() else None,
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