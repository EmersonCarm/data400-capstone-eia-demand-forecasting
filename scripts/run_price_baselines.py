"""Export fixed price baselines, calibration bands, and a forecast-origin audit."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from monthly_forecasting import (PROTOCOL_PATH, ROOT, available_rows, baseline_predictions,
                                 calibration_radii, load_protocol, protocol_hash, runtime_metadata, training_rows)
from pull_monthly_sources import atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "processed" / "monthly" / "study_monthly.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed" / "monthly" / "baselines")
    parser.add_argument("--partitions", nargs="+", choices=("validation", "calibration", "test"),
                        default=["validation", "calibration"])
    args = parser.parse_args()
    if len(set(args.partitions)) != len(args.partitions):
        parser.error("Do not repeat partitions.")
    try:
        data = pd.read_csv(args.data)
        protocol = load_protocol()
        runtime = runtime_metadata()
        digest = hashlib.sha256(args.data.read_bytes() + PROTOCOL_PATH.read_bytes()
                                + Path(__file__).read_bytes()
                                + (ROOT / "scripts" / "monthly_forecasting.py").read_bytes()
                                + json.dumps(runtime, sort_keys=True).encode()
                                + ",".join(args.partitions).encode()).hexdigest()
        run_id = digest[:16]
        output_dir = args.output_dir / run_id
        partitions = sorted(set(args.partitions) | {"calibration"})
        predictions = baseline_predictions(data, partitions, protocol, run_id)
        radii = calibration_radii(predictions, data, protocol, protocol["calibration_available_date"])
        test = predictions.target_month.ge(protocol["partitions"]["test"][0])
        radius = predictions.model_id.map(radii)
        predictions.loc[test, "lower_bound"] = predictions.loc[test, "predicted_price_cents_kwh"] - radius[test]
        predictions.loc[test, "upper_bound"] = predictions.loc[test, "predicted_price_cents_kwh"] + radius[test]
        origin = "2023-12-31"
        audit = dict(origin=origin, target_month="2024-01", protocol_sha256=protocol_hash(protocol),
                     latest_electricity_period=available_rows(data, origin, "electricity", protocol).period.max(),
                     latest_control_period=available_rows(data, origin, "weather", protocol).period.max(),
                     eligible_training_labels=len(training_rows(data, origin, protocol)),
                     initial_validation_training_labels=len(training_rows(data, "2020-12-31", protocol)))
        outputs = {"protocol.json": PROTOCOL_PATH.read_bytes(),
                   "calibration_radii.json": (json.dumps(radii, indent=2) + "\n").encode(),
                   "january_2024_origin_audit.json": (json.dumps(audit, indent=2) + "\n").encode()}
        for partition in args.partitions:
            start, end = protocol["partitions"][partition]
            portion = predictions.loc[predictions.target_month.between(start, end)]
            outputs[f"baseline_{partition}.csv"] = portion.to_csv(index=False).encode()
        manifest = dict(run_id=run_id, protocol_sha256=protocol_hash(protocol),
                        runtime=runtime,
                        source_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
                        output_sha256={name: hashlib.sha256(content).hexdigest() for name, content in outputs.items()})
        outputs["run.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
        for name, content in outputs.items():
            path = output_dir / name
            if path.exists() and path.read_bytes() != content:
                raise ValueError(f"Existing run artifact differs: {path}")
        for name, content in outputs.items():
            atomic_write(output_dir / name, content)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"Saved baseline run {run_id} to {output_dir}")
    print(f"January 2024 electricity cutoff: {audit['latest_electricity_period']}; controls cutoff: {audit['latest_control_period']}")


if __name__ == "__main__":
    main()
