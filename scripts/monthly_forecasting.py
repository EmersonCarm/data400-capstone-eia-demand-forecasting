"""Shared monthly release rules, baseline methods, and forecast-export checks."""

import hashlib
import json
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "config" / "monthly_evaluation.json"
PREDICTION_COLUMNS = ["utility_id", "state", "origin", "target_month", "horizon_months", "model_id",
                      "actual_price_cents_kwh", "predicted_price_cents_kwh", "lower_bound", "upper_bound",
                      "training_label_cutoff", "training_rows", "run_id", "protocol_sha256"]


def load_protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def protocol_hash(protocol):
    return hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def partition_months(partition, protocol):
    start, end = protocol["partitions"][partition]
    return pd.period_range(start, end, freq="M").astype(str).tolist()


def availability_dates(periods, family, protocol):
    return (pd.PeriodIndex(periods, freq="M") + protocol["release_delay_months"][family]).to_timestamp("M")


def available_rows(data, origin, family, protocol):
    return data.loc[availability_dates(data.period, family, protocol) <= pd.Timestamp(origin)].copy()


def require_available(periods, origin, family, protocol):
    if (availability_dates(periods, family, protocol) > pd.Timestamp(origin)).any():
        raise ValueError(f"An {family} observation is unavailable at origin {origin}.")


def training_rows(data, origin, protocol):
    eligible = available_rows(data, origin, "electricity", protocol)
    return eligible.loc[eligible.period.ge(protocol["training_start"])].sort_values("period").copy()


def validate_prices(data, protocol):
    data = data.copy()
    if not {"period", "utility_id", "state", "price_cents_per_kwh"}.issubset(data):
        raise ValueError("Missing required price-table columns.")
    if not data.utility_id.eq(protocol["utility_id"]).all() or not data.state.eq(protocol["state"]).all():
        raise ValueError("Price data must contain only the configured utility and state.")
    expected = pd.period_range(protocol["source_start"], protocol["source_end"], freq="M").astype(str).tolist()
    data = data.sort_values("period").reset_index(drop=True)
    if data.period.tolist() != expected:
        raise ValueError("Expected one price row for every source month.")
    values = pd.to_numeric(data.price_cents_per_kwh, errors="raise")
    if not (np.isfinite(values) & values.gt(0)).all():
        raise ValueError("Price outcomes must be positive and finite.")
    data["price_cents_per_kwh"] = values
    return data


def baseline_predictions(data, partitions, protocol, run_id):
    data = validate_prices(data, protocol)
    target_prices = data.set_index("period").price_cents_per_kwh
    records = []
    for partition in partitions:
        for target in partition_months(partition, protocol):
            month = pd.Period(target, freq="M")
            origin = (month - 1).to_timestamp("M").strftime("%Y-%m-%d")
            eligible = available_rows(data, origin, "electricity", protocol)
            fitting = training_rows(data, origin, protocol)
            seasonal_period = str(month - 12)
            require_available([seasonal_period], origin, "electricity", protocol)
            values = {"last_released": eligible.price_cents_per_kwh.iloc[-1],
                      "seasonal_naive": target_prices.loc[seasonal_period]}
            for model_id, prediction in values.items():
                records.append(dict(utility_id=protocol["utility_id"], state=protocol["state"],
                                    origin=origin, target_month=target, horizon_months=protocol["horizon_months"],
                                    model_id=model_id, actual_price_cents_kwh=target_prices.loc[target],
                                    predicted_price_cents_kwh=prediction, lower_bound=np.nan, upper_bound=np.nan,
                                    training_label_cutoff=fitting.period.iloc[-1], training_rows=len(fitting),
                                    run_id=run_id, protocol_sha256=protocol_hash(protocol)))
    return pd.DataFrame(records, columns=PREDICTION_COLUMNS)


def validate_predictions(predictions, data, partition, protocol):
    data = validate_prices(data, protocol)
    missing = set(PREDICTION_COLUMNS) - set(predictions)
    if missing:
        raise ValueError(f"Missing prediction-export columns: {sorted(missing)}")
    if predictions.empty:
        raise ValueError("Prediction export is empty.")
    frame = predictions.copy()
    if frame.duplicated(["utility_id", "state", "model_id", "origin", "target_month"]).any():
        raise ValueError("Prediction export contains duplicate model-origin-target keys.")
    if not frame.utility_id.eq(protocol["utility_id"]).all() or not frame.state.eq(protocol["state"]).all():
        raise ValueError("Prediction utility/state differs from the study.")
    if not frame.protocol_sha256.eq(protocol_hash(protocol)).all():
        raise ValueError("Prediction protocol hash differs from the current evaluation rules.")
    for field in ("run_id", "model_id"):
        if not frame[field].map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError(f"Missing {field} in prediction export.")
    if frame.groupby("model_id").run_id.nunique().ne(1).any():
        raise ValueError("Each model must provide one run for a comparison.")
    for field in ("actual_price_cents_kwh", "predicted_price_cents_kwh", "horizon_months", "training_rows"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
        if not np.isfinite(frame[field]).all():
            raise ValueError(f"Nonfinite {field} in prediction export.")
    if not frame.horizon_months.eq(1).all():
        raise ValueError("Expected the declared one-month horizon.")
    target_periods = pd.PeriodIndex(frame.target_month, freq="M")
    if target_periods.astype(str).tolist() != frame.target_month.tolist():
        raise ValueError("Target months must use YYYY-MM.")
    expected_origins = (target_periods - 1).to_timestamp("M").strftime("%Y-%m-%d")
    if frame.origin.tolist() != expected_origins.tolist():
        raise ValueError("Forecast origin must be the month-end before its target.")
    cutoff = pd.PeriodIndex(frame.training_label_cutoff, freq="M")
    if cutoff.astype(str).tolist() != frame.training_label_cutoff.tolist():
        raise ValueError("Training label cutoff must use YYYY-MM.")
    if (availability_dates(cutoff, "electricity", protocol) > pd.to_datetime(frame.origin)).any():
        raise ValueError("Training label cutoff is unavailable at the forecast origin.")
    maximum_rows = cutoff.asi8 - pd.Period(protocol["training_start"], freq="M").ordinal + 1
    if ((frame.training_rows < 1) | (frame.training_rows > maximum_rows)
            | (frame.training_rows % 1 != 0)).any():
        raise ValueError("Invalid count of eligible fitting labels.")
    truth = data.set_index("period").price_cents_per_kwh.reindex(frame.target_month)
    if truth.isna().any() or not np.allclose(frame.actual_price_cents_kwh, truth.to_numpy(), rtol=1e-10, atol=1e-12):
        raise ValueError("Exported actual prices do not match source truth.")
    for field in ("lower_bound", "upper_bound"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
        if np.isinf(frame[field]).any():
            raise ValueError("Prediction intervals contain infinite bounds.")
    if (frame.lower_bound.isna() != frame.upper_bound.isna()).any():
        raise ValueError("Supply both interval bounds together.")
    bounded = frame.lower_bound.notna()
    if ((frame.loc[bounded, "lower_bound"] > frame.loc[bounded, "predicted_price_cents_kwh"])
            | (frame.loc[bounded, "upper_bound"] < frame.loc[bounded, "predicted_price_cents_kwh"])).any():
        raise ValueError("Prediction interval does not contain its point forecast.")
    expected_months = partition_months(partition, protocol)
    selected = frame.loc[frame.target_month.isin(expected_months)].copy()
    for model_id in frame.model_id.unique():
        portion = selected.loc[selected.model_id.eq(model_id)]
        if sorted(portion.target_month) != expected_months:
            raise ValueError(f"{model_id} must supply the complete {partition} calendar for matched scoring.")
        if portion.lower_bound.notna().any() and portion.lower_bound.isna().any():
            raise ValueError("Supply intervals for every scored month or leave all bounds empty.")
    return selected.sort_values(["model_id", "target_month"]).reset_index(drop=True)


def calibration_radii(predictions, data, protocol, as_of):
    months = partition_months("calibration", protocol)
    require_available(months, as_of, "electricity", protocol)
    selected = validate_predictions(predictions, data, "calibration", protocol)
    radii = {}
    for model_id, portion in selected.groupby("model_id"):
        errors = (portion.predicted_price_cents_kwh - portion.actual_price_cents_kwh).abs().sort_values()
        rank = ceil((len(errors) + 1) * protocol["nominal_interval_coverage"])
        if rank > len(errors):
            raise ValueError("Insufficient calibration observations for the requested empirical band.")
        radii[model_id] = float(errors.iloc[rank - 1])
    return radii
