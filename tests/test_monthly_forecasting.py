from pathlib import Path
from importlib.metadata import version
import json
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import monthly_forecasting as forecasting
import evaluate_price_forecasts as evaluation
from evaluate_price_forecasts import evaluate_predictions


class MonthlyForecastingTests(unittest.TestCase):
    def setUp(self):
        self.protocol = forecasting.load_protocol()
        self.data = pd.DataFrame({"period": pd.period_range("2017-01", "2025-12", freq="M").astype(str),
                                  "utility_id": 19876, "state": "VA",
                                  "price_cents_per_kwh": np.arange(1, 109, dtype=float)})

    def test_january_origin_cuts_off_both_inputs_and_fitting_labels(self):
        available = forecasting.available_rows(self.data, "2023-12-31", "electricity", self.protocol)
        self.assertEqual(available.period.iloc[-1], "2023-09")
        fitting = forecasting.training_rows(self.data, "2020-12-31", self.protocol)
        self.assertEqual(len(fitting), 33)
        self.assertEqual(fitting.period.iloc[-1], "2020-09")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            forecasting.require_available(["2023-10"], "2023-12-31", "electricity", self.protocol)
        forecasting.require_available(["2023-11"], "2023-12-31", "weather", self.protocol)

    def test_baselines_ignore_unavailable_and_future_price_changes(self):
        predictions = forecasting.baseline_predictions(self.data, ["test"], self.protocol, "fixture")
        january = predictions[predictions.target_month.eq("2024-01")].set_index("model_id")
        self.assertEqual(january.loc["last_released", "predicted_price_cents_kwh"], 81)
        self.assertEqual(january.loc["seasonal_naive", "predicted_price_cents_kwh"], 73)
        changed = self.data.copy()
        changed.loc[changed.period.ge("2023-10"), "price_cents_per_kwh"] = 9999
        altered = forecasting.baseline_predictions(changed, ["test"], self.protocol, "fixture")
        altered_january = altered[altered.target_month.eq("2024-01")].set_index("model_id")
        pd.testing.assert_series_equal(january.predicted_price_cents_kwh, altered_january.predicted_price_cents_kwh)

    def test_saved_forecasts_are_scored_on_identical_months_with_known_errors(self):
        predictions = forecasting.baseline_predictions(self.data, ["validation"], self.protocol, "fixture")
        report = evaluate_predictions(predictions, self.data, "validation", self.protocol)
        last = report["models"]["last_released"]["overall"]
        self.assertEqual(last["months"], 12)
        self.assertEqual(last["mae_cents_per_kwh"], 4)
        self.assertEqual(last["rmse_cents_per_kwh"], 4)
        self.assertEqual(last["mean_error_cents_per_kwh"], -4)
        self.assertEqual(last["mae_dollars_at_1000_kwh"], 40)
        self.assertEqual(report["models"]["seasonal_naive"]["overall"]["mae_cents_per_kwh"], 12)
        with self.assertRaisesRegex(ValueError, "complete"):
            evaluate_predictions(predictions.iloc[1:], self.data, "validation", self.protocol)

    def test_evaluation_rejects_duplicates_wrong_truth_and_future_cutoffs(self):
        predictions = forecasting.baseline_predictions(self.data, ["validation"], self.protocol, "fixture")
        duplicate = pd.concat([predictions, predictions.iloc[:1]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_predictions(duplicate, self.data, "validation", self.protocol)
        for field, value in [("actual_price_cents_kwh", 999),
                             ("training_label_cutoff", "2020-12"),
                             ("origin", "2021-01-31"),
                             ("predicted_price_cents_kwh", np.inf),
                             ("protocol_sha256", "changed")]:
            bad = predictions.copy()
            bad.loc[0, field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate_predictions(bad, self.data, "validation", self.protocol)

    def test_calibration_waits_for_all_labels_and_uses_only_calibration_errors(self):
        predictions = forecasting.baseline_predictions(self.data, ["validation", "calibration"], self.protocol, "fixture")
        with self.assertRaisesRegex(ValueError, "available"):
            forecasting.calibration_radii(predictions, self.data, self.protocol, "2023-11-30")
        radii = forecasting.calibration_radii(predictions, self.data, self.protocol, "2023-12-31")
        self.assertEqual(radii, {"last_released": 4, "seasonal_naive": 12})

    def test_interval_coverage_is_recomputed_from_saved_bounds(self):
        predictions = forecasting.baseline_predictions(self.data, ["validation"], self.protocol, "fixture")
        predictions["lower_bound"] = predictions.predicted_price_cents_kwh - 5
        predictions["upper_bound"] = predictions.predicted_price_cents_kwh + 5
        report = evaluate_predictions(predictions, self.data, "validation", self.protocol)
        last = report["models"]["last_released"]["overall"]
        self.assertEqual(last["interval_covered_months"], 12)
        self.assertEqual(last["mean_interval_width_cents_per_kwh"], 10)
        self.assertEqual(report["models"]["seasonal_naive"]["overall"]["interval_covered_months"], 0)
        predictions.loc[0, "upper_bound"] = predictions.loc[0, "lower_bound"] - 1
        with self.assertRaisesRegex(ValueError, "interval"):
            evaluate_predictions(predictions, self.data, "validation", self.protocol)

    def test_missing_dates_cannot_bypass_availability_or_label_count_checks(self):
        predictions = forecasting.baseline_predictions(self.data, ["validation"], self.protocol, "fixture")
        predictions["training_label_cutoff"] = "NaT"
        predictions["training_rows"] = 999
        with self.assertRaises(ValueError):
            evaluate_predictions(predictions, self.data, "validation", self.protocol)
        for periods, origin in [([pd.NaT], "2023-12-31"), (["2023-09"], None),
                                (["2023-09"], "NaT")]:
            with self.subTest(periods=periods, origin=origin), self.assertRaises(ValueError):
                forecasting.require_available(periods, origin, "electricity", self.protocol)

    def test_each_supplied_forecast_file_must_have_its_own_complete_schema_and_rows(self):
        baseline = forecasting.baseline_predictions(self.data, ["validation"], self.protocol, "fixture")
        ridge = baseline.loc[baseline.model_id.eq("last_released")].copy()
        ridge["model_id"] = "ridge"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline_path, ridge_path = directory / "baseline.csv", directory / "ridge.csv"
            self.data.to_csv(directory / "truth.csv", index=False)
            command = [sys.executable, evaluation.__file__, "--data", str(directory / "truth.csv"),
                       "--predictions", str(baseline_path), str(ridge_path),
                       "--output", str(directory / "metrics.json")]
            baseline.to_csv(baseline_path, index=False)
            ridge.iloc[:0].to_csv(ridge_path, index=False)
            empty = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(empty.returncode, 0)
            self.assertIn("empty", empty.stderr)
            ridge.drop(columns=["lower_bound", "upper_bound"]).to_csv(ridge_path, index=False)
            incomplete = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertIn("columns", incomplete.stderr)
            baseline["run_id"] = "20261127"
            ridge["run_id"] = "20261127"
            baseline.to_csv(baseline_path, index=False)
            ridge.to_csv(ridge_path, index=False)
            complete = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(complete.returncode, 0, complete.stderr)
            report = json.loads((directory / "metrics.json").read_text())
            self.assertEqual(set(report["models"]), {"last_released", "seasonal_naive", "ridge"})

    def test_run_metadata_records_the_actual_environment_and_revision(self):
        metadata = forecasting.runtime_metadata()
        self.assertEqual(metadata["python"], sys.version.split()[0])
        self.assertEqual(metadata["packages"]["pandas"], version("pandas"))
        self.assertIn("git_revision", metadata)


if __name__ == "__main__":
    unittest.main()
