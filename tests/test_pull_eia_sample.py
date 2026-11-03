"""Exercise the collector with saved EIA records and no network requests."""

import contextlib
import csv
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class CollectorArgumentsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "scripts" / "pull_eia_sample.py"
        self.script.parent.mkdir()
        shutil.copyfile(ROOT / "scripts" / "pull_eia_sample.py", self.script)
        with (ROOT / "data/raw/pjm_2025_09_eia_long.csv").open(newline="") as source:
            self.records = list(csv.DictReader(source))

    def run_collector(self, arguments=(), records=None, pages=None, allow_exit=False,
                      api_key="offline-test-key"):
        records = self.records if records is None else records
        if pages is None:
            pages = [{"total": str(len(records)), "data": records}]
        responses = [
            SimpleNamespace(status_code=200, json=lambda page=page: {
                "response": page,
                "request": {"params": {"api_key": "offline-test-key"}},
            })
            for page in pages
        ]
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"EIA_API_KEY": api_key}),
            patch("sys.argv", [str(self.script), *arguments]),
            patch("requests.get", side_effect=responses) as request,
            contextlib.redirect_stdout(output),
        ):
            try:
                runpy.run_path(str(self.script), run_name="__main__")
            except SystemExit as stopped:
                if allow_exit:
                    raise
                self.fail(f"Collector exited before completing: {stopped}")
        return [call.kwargs["params"] for call in request.call_args_list], output.getvalue()

    def prime_cache(self):
        self.run_collector()
        cache_path = self.root / ".cache/eia/pjm_2025_09.json"
        self.assertTrue(cache_path.exists(), "A successful download should create a cache")
        return cache_path

    def test_cache_rebuilds_outputs_without_http_or_api_key(self):
        cache_path = self.prime_cache()
        processed = self.root / "data/processed/pjm_2025_09_hourly.csv"
        expected = processed.read_bytes()
        processed.unlink()
        requests, output = self.run_collector(pages=[], api_key="")
        self.assertEqual(requests, [])
        self.assertEqual(processed.read_bytes(), expected)
        self.assertIn("Using cached download", output)
        self.assertNotIn("offline-test-key", cache_path.read_text())
        self.assertNotIn("api_key", cache_path.read_text())

    def test_refresh_downloads_and_replaces_cache(self):
        cache_path = self.prime_cache()
        revised = [dict(row) for row in self.records]
        revised[0]["value"] = "12345"
        requests, _ = self.run_collector(["--refresh"], records=revised)
        self.assertEqual(len(requests), 1)
        self.assertEqual(json.loads(cache_path.read_text())["records"][0]["value"], "12345")
        with (self.root / "data/raw/pjm_2025_09_eia_long.csv").open(newline="") as source:
            self.assertEqual(next(csv.DictReader(source))["value"], "12345")

    def test_failed_refresh_preserves_previous_cache_and_outputs(self):
        cache_path = self.prime_cache()
        before = cache_path.read_bytes()
        processed = self.root / "data/processed/pjm_2025_09_hourly.csv"
        original_output = processed.read_bytes()
        with self.assertRaisesRegex(SystemExit, "stopped returning rows"):
            self.run_collector(["--refresh"], pages=[
                {"total": "1440", "data": self.records[:100]},
                {"total": "1440", "data": []},
            ], allow_exit=True)
        self.assertEqual(cache_path.read_bytes(), before)
        self.assertEqual(processed.read_bytes(), original_output)
        self.assertEqual(list(cache_path.parent.glob("*.tmp")), [])

    def test_caches_are_separate_for_regions_and_date_ranges(self):
        self.prime_cache()
        for ba, start, end in (
            ("PJM", "2025-09-01T01", "2025-09-01T02"),
            ("MISO", "2025-09-01T00", "2025-09-30T23"),
        ):
            records = [dict(row, respondent=ba) for row in self.records
                       if start <= row["period"] <= end]
            requests, _ = self.run_collector(
                ["--ba", ba, "--start", start, "--end", end], records=records
            )
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["facets[respondent][]"], ba)
            self.assertEqual(requests[0]["start"], start)
        self.assertEqual(len(list((self.root / ".cache/eia").glob("*.json"))), 3)

    def test_corrupt_or_mismatched_cache_requires_explicit_refresh(self):
        cache_path = self.prime_cache()
        original = json.loads(cache_path.read_text())
        truncated = dict(original, records=original["records"][:-1])
        mismatched = dict(original, request=dict(original["request"], respondent="MISO"))
        for content in ("{", json.dumps(truncated), json.dumps(mismatched)):
            with self.subTest(content=content[:40]):
                cache_path.write_text(content)
                with self.assertRaisesRegex(SystemExit, "--refresh"):
                    self.run_collector(pages=[], api_key="", allow_exit=True)
                self.assertEqual(cache_path.read_text(), content)
        self.run_collector(["--refresh"])
        self.assertEqual(json.loads(cache_path.read_text())["total"], 1440)

    def test_cache_records_must_match_requested_region_and_dates(self):
        cache_path = self.prime_cache()
        original = cache_path.read_text()
        for update in ({"respondent": "MISO"}, {"period": "2026-01-01T00"}):
            data = json.loads(original)
            data["records"][0].update(update)
            cache_path.write_text(json.dumps(data))
            with self.assertRaises(SystemExit):
                self.run_collector(pages=[], api_key="", allow_exit=True)

    def test_entirely_missing_series_are_reported_and_can_be_cached(self):
        arguments = ["--start", "2025-09-01T01", "--end", "2025-09-01T01"]
        report = self.root / "docs/pjm_20250901T01_20250901T01_quality.json"
        processed = self.root / "data/processed/pjm_20250901T01_20250901T01_hourly.csv"
        for present, absent_column, absent_count in (
            ("D", "forecast_mwh", "missing_forecast_hours"),
            ("DF", "demand_mwh", "missing_actual_demand_hours"),
        ):
            with self.subTest(present=present):
                records = [row for row in self.records
                           if row["period"] == "2025-09-01T01" and row["type"] == present]
                self.run_collector(arguments + ["--refresh"], records=records)
                requests, _ = self.run_collector(arguments, pages=[], api_key="")
                self.assertEqual(requests, [])
                self.assertEqual(json.loads(report.read_text())[absent_count], 1)
                with processed.open(newline="") as source:
                    rows = list(csv.DictReader(source))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][absent_column], "")

    def test_defaults_reproduce_committed_sample(self):
        self.run_collector()
        for filename in (
            "data/raw/pjm_2025_09_eia_long.csv",
            "data/processed/pjm_2025_09_hourly.csv",
            "docs/sample_quality.json",
        ):
            with self.subTest(filename=filename):
                self.assertEqual(
                    (self.root / filename).read_bytes(), (ROOT / filename).read_bytes()
                )

    def test_custom_region_and_hours_control_request_and_outputs(self):
        records = [
            dict(row, respondent="MISO", **{"respondent-name": "Test authority"})
            for row in self.records
            if row["period"] in {"2025-09-01T01", "2025-09-01T02"}
            and not (row["period"] == "2025-09-01T02" and row["type"] == "DF")
        ]
        requests, output = self.run_collector(
            ["--ba", "miso", "--start", "2025-09-01T01", "--end", "2025-09-01T02"],
            records,
        )
        params = requests[0]
        self.assertEqual(params["facets[respondent][]"], "MISO")
        self.assertEqual(params["start"], "2025-09-01T01")
        self.assertEqual(params["end"], "2025-09-01T02")
        prefix = "miso_20250901T01_20250901T02"
        with (self.root / f"data/processed/{prefix}_hourly.csv").open(newline="") as source:
            hourly = list(csv.DictReader(source))
        self.assertEqual(
            [row["timestamp_utc"] for row in hourly],
            ["2025-09-01 01:00:00+00:00", "2025-09-01 02:00:00+00:00"],
        )
        self.assertEqual([row["respondent"] for row in hourly], ["MISO", "MISO"])
        self.assertEqual([float(row["demand_mwh"]) for row in hourly], [88503, 85101])
        self.assertEqual(hourly[1]["forecast_mwh"], "")
        quality = json.loads((self.root / f"docs/{prefix}_quality.json").read_text())
        self.assertEqual(quality["respondent"], "MISO")
        self.assertEqual(quality["start_utc"], "2025-09-01T01")
        self.assertEqual(quality["end_utc"], "2025-09-01T02")
        self.assertEqual(quality["hourly_rows_expected"], 2)
        self.assertEqual(quality["missing_actual_demand_hours"], 0)
        self.assertEqual(quality["missing_forecast_hours"], 1)
        self.assertTrue((self.root / f"data/raw/{prefix}_eia_long.csv").exists())
        self.assertFalse((self.root / "docs/sample_quality.json").exists())
        self.assertIn(f"data/processed/{prefix}_hourly.csv", output)

    def test_collects_more_than_5000_records_across_pages(self):
        records = []
        for block in range(4):
            for row in self.records:
                hour = datetime.strptime(row["period"], "%Y-%m-%dT%H")
                hour += timedelta(days=30 * block)
                records.append(dict(row, period=hour.strftime("%Y-%m-%dT%H")))
        requests, _ = self.run_collector(
            ["--end", "2025-12-29T23"],
            pages=[
                {"total": "5760", "data": records[:5000]},
                {"total": "5760", "data": records[5000:]},
            ],
        )
        self.assertEqual([params["offset"] for params in requests], [0, 5000])
        for params in requests:
            self.assertEqual(params["length"], 5000)
            self.assertEqual(params["sort[1][column]"], "type")
            self.assertEqual(params["sort[1][direction]"], "asc")
        prefix = "pjm_20250901T00_20251229T23"
        quality = json.loads((self.root / f"docs/{prefix}_quality.json").read_text())
        self.assertEqual(quality["records_received_long_format"], 5760)
        self.assertEqual(quality["hourly_rows_expected"], 2880)
        self.assertEqual(quality["missing_actual_demand_hours"], 0)
        self.assertEqual(quality["missing_forecast_hours"], 0)
        self.assertEqual(quality["duplicate_hour_type_rows"], 0)
        with (self.root / f"data/raw/{prefix}_eia_long.csv").open(newline="") as source:
            downloaded = list(csv.DictReader(source))
        self.assertEqual(len(downloaded), 5760)
        self.assertEqual(downloaded[-1]["period"], "2025-12-29T23")

    def test_short_pages_advance_by_the_number_of_received_records(self):
        requests, _ = self.run_collector(pages=[
            {"total": "1440", "data": self.records[:701]},
            {"total": "1440", "data": self.records[701:1402]},
            {"total": "1440", "data": self.records[1402:]},
        ])
        self.assertEqual([params["offset"] for params in requests], [0, 701, 1402])
        self.assertEqual(
            (self.root / "data/processed/pjm_2025_09_hourly.csv").read_bytes(),
            (ROOT / "data/processed/pjm_2025_09_hourly.csv").read_bytes(),
        )

    def test_incomplete_or_changed_pages_leave_no_partial_output(self):
        for second_page, message in (
            ({"total": "1440", "data": []}, "stopped returning rows"),
            ({"total": "1439", "data": self.records[100:200]}, "total changed"),
            ({"data": self.records[100:200]}, "valid total row count"),
        ):
            with self.subTest(second_page_total=second_page.get("total")):
                with self.assertRaisesRegex(SystemExit, message):
                    self.run_collector(pages=[
                        {"total": "1440", "data": self.records[:100]},
                        second_page,
                    ], allow_exit=True)
                self.assertFalse((self.root / "data").exists())
                self.assertFalse((self.root / "docs").exists())

    def test_invalid_inputs_exit_before_request_or_file_writes(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"response": {"total": "1440", "data": self.records}},
        )
        for arguments in (
            ["--start", "2025-02-30T00"],
            ["--start", "2025-10-01T00", "--end", "2025-09-30T23"],
            ["--ba", "../PJM"],
        ):
            with self.subTest(arguments=arguments):
                with (
                    patch.dict(os.environ, {"EIA_API_KEY": "offline-test-key"}),
                    patch("requests.get", return_value=response) as request,
                    patch("sys.argv", [str(self.script), *arguments]),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as stopped,
                ):
                    runpy.run_path(str(self.script), run_name="__main__")
                self.assertEqual(stopped.exception.code, 2)
                request.assert_not_called()
                self.assertFalse((self.root / "data").exists())


if __name__ == "__main__":
    unittest.main()
