from __future__ import annotations

import math


def explain(
    r2: float,
    rmse: float,
    mape: float,
    baseline_mape: float,
) -> dict:
    """
    Translates raw model accuracy metrics into plain-English output.
    Used by demand.py and injected into every demand forecast report.

    Parameters:
        r2            — R-squared (0 to 1)
        rmse          — Root mean squared error (same units as target)
        mape          — Mean absolute percentage error (%)
        baseline_mape — MAPE of naive baseline (predict the mean)

    Returns:
    {
        "r2": float,
        "rmse": float,
        "mape": float,
        "baseline_mape": float,
        "improvement_pct": float,
        "r2_label": str,
        "mape_label": str,
        "summary": str
    }
    """
    # Clamp inputs to valid ranges
    r2 = max(0.0, min(1.0, float(r2)))  # clamp to 0 — negative R² on small holdouts is misleading
    rmse = max(0.0, float(rmse))
    mape = max(0.0, float(mape))
    baseline_mape = max(0.0, float(baseline_mape))

    # R² label
    if r2 >= 0.85:
        r2_label = "strong"
    elif r2 >= 0.75:
        r2_label = "acceptable"
    elif r2 >= 0.50:
        r2_label = "weak"
    else:
        r2_label = "poor"

    # MAPE label
    if mape < 5.0:
        mape_label = "excellent"
    elif mape < 10.0:
        mape_label = "good"
    elif mape < 20.0:
        mape_label = "acceptable"
    else:
        mape_label = "poor"

    # Improvement over baseline
    if baseline_mape > 0:
        improvement_pct = round(
            ((baseline_mape - mape) / baseline_mape) * 100, 1
        )
    else:
        improvement_pct = 0.0

    # Plain-English summary
    summary = _build_summary(r2, r2_label, mape, mape_label,
                              improvement_pct, baseline_mape)

    return {
        "r2": round(r2, 4),
        "rmse": round(rmse, 2),
        "mape": round(mape, 2),
        "baseline_mape": round(baseline_mape, 2),
        "improvement_pct": improvement_pct,
        "r2_label": r2_label,
        "mape_label": mape_label,
        "summary": summary,
    }


def _build_summary(
    r2: float,
    r2_label: str,
    mape: float,
    mape_label: str,
    improvement_pct: float,
    baseline_mape: float,
) -> str:
    """Builds a single plain-English accuracy sentence."""

    r2_pct = round(r2 * 100, 1)

    if improvement_pct > 0:
        return (
            f"Model explains {r2_pct}% of demand variation "
            f"({r2_label} fit) — predictions off by an average of "
            f"{mape:.1f}%, which is {improvement_pct:.1f}% more accurate "
            f"than simply predicting the regional average."
        )
    else:
        return (
            f"Model explains {r2_pct}% of demand variation "
            f"({r2_label} fit) — predictions off by an average of "
            f"{mape:.1f}%. Note: model does not outperform a naive baseline "
            f"for this location."
        )