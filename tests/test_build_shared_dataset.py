"""Verify the shared dataset contract using small offline regional fixtures."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_shared_dataset.py"


class SharedDatasetTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "The shared dataset builder has not been implemented")
        spec = importlib.util.spec_from_file_location("shared_dataset", SCRIPT)
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.start = pd.Timestamp("2025-01-01T00:00:00Z")
        self.end = pd.Timestamp("2025-01-01T02:00:00Z")
        self.source = pd.DataFrame({
            "timestamp_utc": ["2025-01-01 02:00:00+00:00", "2025-01-01 00:00:00+00:00",
                              "2025-01-01 01:00:00+00:00"],
            "respondent": ["PJM"] * 3,
            "demand_mwh": [None, 10, 0],
            "forecast_mwh": [12, 9, None],
        })
        self.write_input("PJM", self.source)
        erco = self.source.assign(respondent="ERCO", demand_mwh=[22, 20, 21], forecast_mwh=None)
        self.write_input("ERCO", erco)

    def write_input(self, region, frame):
        filename = self.inputs / f"{region.lower()}_20250101T00_20250101T02_hourly.csv"
        frame.to_csv(filename, index=False)
        return filename

    def build(self, regions=("PJM", "ERCO")):
        return self.builder.build_dataset(self.inputs, regions, self.start, self.end)

    def test_stacks_regions_with_exact_schema_and_preserves_zero_and_null(self):
        data, missing, quality = self.build()
        self.assertEqual(list(data.columns),
                         ["ts_utc", "ba", "demand_mwh", "forecast_mwh", "is_imputed"])
        self.assertEqual(data["ba"].tolist(), ["ERCO"] * 3 + ["PJM"] * 3)
        self.assertEqual(str(data["ts_utc"].dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(data["is_imputed"].dtype), "bool")
        self.assertFalse(data["is_imputed"].any())
        pjm = data[data["ba"].eq("PJM")]
        self.assertEqual(pjm["demand_mwh"].iloc[1], 0)
        self.assertTrue(pd.isna(pjm["demand_mwh"].iloc[2]))
        self.assertEqual(data["demand_mwh"].isna().sum(), 1)
        self.assertEqual(data["forecast_mwh"].isna().sum(), 4)
        self.assertEqual(len(missing), 5)
        self.assertEqual(list(missing.columns), ["ts_utc", "ba", "measurement"])
        self.assertEqual(quality["rows_total"], 6)
        self.assertEqual(quality["regions"]["PJM"]["missing_demand_hours"], 1)
        self.assertEqual(quality["regions"]["ERCO"]["missing_forecast_hours"], 3)
        filename = self.inputs / "pjm_20250101T00_20250101T02_hourly.csv"
        pjm_source = next(row for row in quality["sources"] if row["region"] == "PJM")
        self.assertEqual(pjm_source["sha256"], hashlib.sha256(filename.read_bytes()).hexdigest())

    def test_parquet_roundtrip_and_output_hashes_match_the_report(self):
        data, missing, quality = self.build()
        output = self.root / "output"
        self.builder.write_outputs(data, missing, quality, output)
        parquet = output / "demand_hourly.parquet"
        pd.testing.assert_frame_equal(data, pd.read_parquet(parquet, engine="pyarrow"))
        log = pd.read_csv(output / "demand_hourly_missing_hours.csv")
        self.assertEqual(len(log), 5)
        report = json.loads((output / "demand_hourly_quality.json").read_text())
        for filename, checksum in report["output_sha256"].items():
            self.assertEqual(hashlib.sha256((output / filename).read_bytes()).hexdigest(), checksum)

    def test_invalid_sources_are_rejected_before_publication(self):
        duplicate = self.source.copy()
        duplicate.loc[1, "timestamp_utc"] = duplicate.loc[0, "timestamp_utc"]
        outside = self.source.copy()
        outside.loc[0, "timestamp_utc"] = "2025-01-01 03:00:00+00:00"
        naive = self.source.copy()
        naive["timestamp_utc"] = naive["timestamp_utc"].str.replace("+00:00", "", regex=False)
        invalid = self.source.copy()
        invalid["demand_mwh"] = invalid["demand_mwh"].astype(object)
        invalid.loc[0, "demand_mwh"] = "not a number"
        infinite = self.source.copy()
        infinite.loc[0, "demand_mwh"] = float("inf")
        cases = [duplicate, outside, naive, invalid, infinite, self.source.iloc[:2],
                 self.source.assign(respondent="ISNE"), self.source.drop(columns="forecast_mwh")]
        for index, source in enumerate(cases):
            with self.subTest(case=index):
                self.write_input("PJM", source)
                with self.assertRaises(ValueError):
                    self.build()
        self.assertFalse((self.root / "output").exists())

    def test_duplicate_regions_and_invalid_date_windows_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build(("PJM", "PJM"))
        with self.assertRaises(ValueError):
            self.builder.build_dataset(self.inputs, ("PJM",), self.end, self.start)
        with self.assertRaises(ValueError):
            self.builder.build_dataset(self.inputs, ("PJM",), self.start.tz_localize(None), self.end)
        with self.assertRaises(ValueError):
            self.build(("../PJM",))

    def test_serialization_failure_preserves_previous_outputs(self):
        data, missing, quality = self.build()
        output = self.root / "output"
        output.mkdir()
        previous = output / "demand_hourly.parquet"
        previous.write_bytes(b"previous complete dataset")
        with patch.object(pd.DataFrame, "to_parquet", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.builder.write_outputs(data, missing, quality, output)
        self.assertEqual(previous.read_bytes(), b"previous complete dataset")
        self.assertEqual([file.name for file in output.iterdir()], ["demand_hourly.parquet"])


if __name__ == "__main__":
    unittest.main()
