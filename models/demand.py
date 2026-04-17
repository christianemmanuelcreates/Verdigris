from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from data.warehouse import query
from models.metrics import explain

LOGGER = logging.getLogger(__name__)

# Minimum years of data required for Prophet
PROPHET_MIN_YEARS = 5

# Years to forecast forward
FORECAST_YEARS = 5

# Stable trend threshold — less than 0.5% change per year
STABLE_THRESHOLD = 0.5


def forecast(state_abbr: str) -> dict:
    """
    Produces a 5-year electricity demand forecast for a U.S. state.

    Primary method: Prophet time-series on warehouse eia_consumption data.
    Fallback: cross-sectional regression if fewer than 5 years available.

    Pulls data from the warehouse — zero API calls.

    Returns:
    {
        "state": str,
        "historical_years": int,
        "model_type": "prophet" | "cross_sectional_fallback",
        "trend_direction": "increasing" | "decreasing" | "stable",
        "trend_pct_per_year": float,
        "forecast_5yr_mwh": [float x 5],
        "forecast_lower": [float x 5],
        "forecast_upper": [float x 5],
        "forecast_years": [int x 5],
        "model_r2": float,
        "model_rmse": float,
        "model_mape": float,
        "baseline_mape": float,
        "metrics": dict        # output of models.metrics.explain()
    }
    """
    state = state_abbr.upper().strip()

    # Pull historical consumption from warehouse
    rows = query(f"""
        SELECT year, consumption_mwh
        FROM eia_consumption
        WHERE state_abbr = '{state}'
          AND sector = 'total'
          AND consumption_mwh IS NOT NULL
        ORDER BY year ASC
    """)

    if not rows:
        LOGGER.error("No consumption data for state %s", state)
        return _error_response(state, f"No warehouse data for {state}")

    df = pd.DataFrame(rows)
    historical_years = len(df)

    if historical_years >= PROPHET_MIN_YEARS:
        return _prophet_forecast(state, df, historical_years)
    else:
        LOGGER.warning(
            "Only %d years of data for %s — using cross-sectional fallback",
            historical_years, state
        )
        return _cross_sectional_fallback(state, df, historical_years)


def _prophet_forecast(
    state: str,
    df: pd.DataFrame,
    historical_years: int,
) -> dict:
    """Fits Prophet and returns a 5-year forecast."""
    try:
        from prophet import Prophet
    except ImportError:
        return _error_response(
            state,
            "Prophet not installed — run: pip install prophet"
        )

    # Prophet requires columns ds (datetime) and y (value)
    prophet_df = pd.DataFrame({
        "ds": pd.to_datetime(df["year"].astype(str) + "-07-01"),
        "y": df["consumption_mwh"].astype(float),
    })

    # Train/test split — hold out last 20% for evaluation
    n_test = max(1, int(len(prophet_df) * 0.2))
    train_df = prophet_df.iloc[:-n_test]
    test_df = prophet_df.iloc[-n_test:]

    # Fit model on training data
    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,  # conservative — energy demand is slow-moving
    )

    try:
        model.fit(train_df)
    except Exception as exc:
        LOGGER.error("Prophet fit failed for %s: %s", state, exc)
        return _error_response(state, f"Prophet fit failed: {exc}")

    # Evaluate on test set
    test_future = model.make_future_dataframe(
        periods=n_test, freq="YS", include_history=False
    )
    test_forecast = model.predict(test_future)

    y_true = test_df["y"].values
    y_pred = test_forecast["yhat"].values[:len(y_true)]

    r2, rmse, mape = _calculate_metrics(y_true, y_pred)
    baseline_mape = _baseline_mape(train_df["y"].values, y_true)

    # Refit on full dataset for final forecast
    model_full = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
    )
    model_full.fit(prophet_df)

    # Forecast 5 years forward
    future = model_full.make_future_dataframe(
        periods=FORECAST_YEARS, freq="YS", include_history=False
    )
    forecast_df = model_full.predict(future)

    forecast_years = [
        int(str(d)[:4]) for d in forecast_df["ds"].values
    ]
    forecast_mwh = [round(float(v), 2) for v in forecast_df["yhat"].values]
    forecast_lower = [round(float(v), 2) for v in forecast_df["yhat_lower"].values]
    forecast_upper = [round(float(v), 2) for v in forecast_df["yhat_upper"].values]

    # Trend direction from Prophet trend component
    trend_vals = model_full.predict(prophet_df)["trend"].values
    if len(trend_vals) >= 2:
        trend_change = (trend_vals[-1] - trend_vals[0]) / trend_vals[0] * 100
        years_span = len(trend_vals)
        trend_pct_per_year = round(trend_change / years_span, 2)
    else:
        trend_pct_per_year = 0.0

    if trend_pct_per_year > STABLE_THRESHOLD:
        trend_direction = "increasing"
    elif trend_pct_per_year < -STABLE_THRESHOLD:
        trend_direction = "decreasing"
    else:
        trend_direction = "stable"

    metrics = explain(r2, rmse, mape, baseline_mape)

    return {
        "state": state,
        "historical_years": historical_years,
        "model_type": "prophet",
        "trend_direction": trend_direction,
        "trend_pct_per_year": trend_pct_per_year,
        "forecast_5yr_mwh": forecast_mwh[:FORECAST_YEARS],
        "forecast_lower": forecast_lower[:FORECAST_YEARS],
        "forecast_upper": forecast_upper[:FORECAST_YEARS],
        "forecast_years": forecast_years[:FORECAST_YEARS],
        "model_r2": round(r2, 4),
        "model_rmse": round(rmse, 2),
        "model_mape": round(mape, 2),
        "baseline_mape": round(baseline_mape, 2),
        "metrics": metrics,
    }


def _cross_sectional_fallback(
    state: str,
    df: pd.DataFrame,
    historical_years: int,
) -> dict:
    """
    Simple fallback when fewer than 5 years of data exist.
    Uses linear trend from available data to project forward.
    """
    from sklearn.linear_model import LinearRegression
    import numpy as np

    years = df["year"].values.reshape(-1, 1)
    values = df["consumption_mwh"].values

    model = LinearRegression()
    model.fit(years, values)

    # Basic metrics on training data
    y_pred = model.predict(years)
    r2 = float(model.score(years, values))
    rmse = float(np.sqrt(np.mean((values - y_pred) ** 2)))
    mape = float(np.mean(np.abs((values - y_pred) / values)) * 100)
    baseline_mape = float(
        np.mean(np.abs((values - np.mean(values)) / values)) * 100
    )

    last_year = int(df["year"].max())
    forecast_years = list(range(last_year + 1, last_year + FORECAST_YEARS + 1))
    future_years = np.array(forecast_years).reshape(-1, 1)
    forecast_mwh = [round(float(v), 2) for v in model.predict(future_years)]

    # Simple confidence band — ±10% of forecast
    forecast_lower = [round(v * 0.90, 2) for v in forecast_mwh]
    forecast_upper = [round(v * 1.10, 2) for v in forecast_mwh]

    slope = float(model.coef_[0])
    mean_val = float(np.mean(values))
    trend_pct_per_year = round((slope / mean_val) * 100, 2)

    if trend_pct_per_year > STABLE_THRESHOLD:
        trend_direction = "increasing"
    elif trend_pct_per_year < -STABLE_THRESHOLD:
        trend_direction = "decreasing"
    else:
        trend_direction = "stable"

    metrics = explain(r2, rmse, mape, baseline_mape)

    return {
        "state": state,
        "historical_years": historical_years,
        "model_type": "cross_sectional_fallback",
        "trend_direction": trend_direction,
        "trend_pct_per_year": trend_pct_per_year,
        "forecast_5yr_mwh": forecast_mwh,
        "forecast_lower": forecast_lower,
        "forecast_upper": forecast_upper,
        "forecast_years": forecast_years,
        "model_r2": round(r2, 4),
        "model_rmse": round(rmse, 2),
        "model_mape": round(mape, 2),
        "baseline_mape": round(baseline_mape, 2),
        "metrics": metrics,
    }


def _calculate_metrics(
    y_true: Any,
    y_pred: Any,
) -> tuple[float, float, float]:
    """Returns R², RMSE, MAPE for a set of predictions."""
    import numpy as np

    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)

    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    nonzero = y_true != 0
    if nonzero.any():
        mape = float(
            np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100
        )
    else:
        mape = 0.0

    return r2, rmse, mape


def _baseline_mape(train_values: Any, test_values: Any) -> float:
    """MAPE of the naive baseline — predicting the training mean."""
    import numpy as np

    train_mean = float(np.mean(train_values))
    test_values = np.array(test_values, dtype=float)
    nonzero = test_values != 0
    if not nonzero.any():
        return 0.0
    return float(
        np.mean(
            np.abs((test_values[nonzero] - train_mean) / test_values[nonzero])
        ) * 100
    )


def _error_response(state: str, error: str) -> dict:
    """Returns a consistent error structure."""
    return {
        "state": state,
        "historical_years": 0,
        "model_type": "error",
        "trend_direction": None,
        "trend_pct_per_year": None,
        "forecast_5yr_mwh": [],
        "forecast_lower": [],
        "forecast_upper": [],
        "forecast_years": [],
        "model_r2": None,
        "model_rmse": None,
        "model_mape": None,
        "baseline_mape": None,
        "metrics": None,
        "error": error,
    }