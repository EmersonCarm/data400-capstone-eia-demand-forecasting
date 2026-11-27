"""Score saved price forecasts against source truth on a common monthly calendar."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from monthly_forecasting import ROOT, load_protocol, protocol_hash, validate_predictions
from pull_monthly_sources import atomic_write


def error_metrics(portion):
    errors = portion.predicted_price_cents_kwh - portion.actual_price_cents_kwh
    metrics = dict(months=len(portion), mae_cents_per_kwh=float(errors.abs().mean()),
                   rmse_cents_per_kwh=float(np.sqrt((errors ** 2).mean())),
                   mean_error_cents_per_kwh=float(errors.mean()),
                   mae_dollars_at_1000_kwh=float(errors.abs().mean() * 10),
                   negative_point_forecasts=int(portion.predicted_price_cents_kwh.lt(0).sum()))
    if portion.lower_bound.notna().all():
        covered = portion.actual_price_cents_kwh.between(portion.lower_bound, portion.upper_bound)
        metrics.update(interval_covered_months=int(covered.sum()), interval_total_months=len(portion),
                       interval_coverage=float(covered.mean()),
                       mean_interval_width_cents_per_kwh=float((portion.upper_bound - portion.lower_bound).mean()),
                       negative_lower_bounds=int(portion.lower_bound.lt(0).sum()))
    return metrics


def evaluate_predictions(predictions, data, partition, protocol):
    selected = validate_predictions(predictions, data, partition, protocol)
    periods = pd.PeriodIndex(selected.target_month, freq="M")
    selected["year"] = periods.year
    selected["season"] = np.where(np.isin(periods.month, protocol["warm_season_months"]), "warm", "cool")
    selected["error_cents_per_kwh"] = selected.predicted_price_cents_kwh - selected.actual_price_cents_kwh
    selected["absolute_error_cents_per_kwh"] = selected.error_cents_per_kwh.abs()
    models = {}
    for model_id, portion in selected.groupby("model_id"):
        models[model_id] = dict(overall=error_metrics(portion),
                               by_year={str(year): error_metrics(group) for year, group in portion.groupby("year")},
                               by_season={season: error_metrics(group) for season, group in portion.groupby("season")})
    paired = []
    for baseline in protocol["baseline_models"]:
        reference = selected.loc[selected.model_id.eq(baseline)].set_index("target_month").absolute_error_cents_per_kwh
        if reference.empty:
            continue
        for model_id, portion in selected.loc[selected.model_id.ne(baseline)].groupby("model_id"):
            for row in portion.itertuples():
                paired.append(dict(model_id=model_id, baseline_id=baseline, target_month=row.target_month,
                                   absolute_error_difference_cents_per_kwh=float(row.absolute_error_cents_per_kwh - reference.loc[row.target_month])))
    return dict(partition=partition, protocol_sha256=protocol_hash(protocol), models=models,
                paired_absolute_error_differences=paired,
                forecast_errors=selected[["model_id", "origin", "target_month", "error_cents_per_kwh",
                                          "absolute_error_cents_per_kwh"]].to_dict("records"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, nargs="+", required=True)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "processed" / "monthly" / "study_monthly.csv")
    parser.add_argument("--partition", choices=("validation", "calibration", "test"), default="validation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        predictions = pd.concat([pd.read_csv(path) for path in args.predictions], ignore_index=True)
        report = evaluate_predictions(predictions, pd.read_csv(args.data), args.partition, load_protocol())
        report["source_sha256"] = hashlib.sha256(args.data.read_bytes()).hexdigest()
        report["prediction_files_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.predictions}
        content = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            atomic_write(args.output, content.encode())
        else:
            print(content)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    if args.output:
        print(f"Saved {args.partition} scores for {len(report['models'])} models to {args.output}")


if __name__ == "__main__":
    main()
