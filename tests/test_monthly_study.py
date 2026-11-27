import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_monthly_study as study
import pull_monthly_sources as sources


class MonthlyStudyTests(unittest.TestCase):
    def weather(self):
        return [dict(DATE=f"2017-01-{day:02d}", STATION="USW00093738",
                     TMAX="20", TMIN="10", TMAX_ATTRIBUTES=",,W", TMIN_ATTRIBUTES=",,W")
                for day in range(1, 32)]

    def test_weather_quality_flags_and_absent_dates_determine_coverage(self):
        rows = self.weather()
        rows[0]["TMAX_ATTRIBUTES"] = ",X,W"
        monthly = study.normalize_weather(rows, "USW00093738", "2017-01", "2017-01")
        january = monthly.iloc[0]
        self.assertEqual(january["valid_days"], 30)
        self.assertAlmostEqual(january["hdd_c_days"], 99.9)
        self.assertEqual(january["cdd_c_days"], 0)
        monthly = study.normalize_weather(rows[:-1], "USW00093738", "2017-01", "2017-01")
        self.assertEqual(monthly.iloc[0]["valid_days"], 29)
        self.assertTrue(pd.isna(monthly.iloc[0]["hdd_c_days"]))

    def test_duplicate_station_dates_and_wrong_station_are_rejected(self):
        for rows in [self.weather() + self.weather()[:1],
                     [dict(self.weather()[0], STATION="USW00013740")]]:
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                study.normalize_weather(rows, "USW00093738", "2017-01", "2017-01")

    def test_missing_temperature_column_produces_missing_monthly_weather(self):
        rows = self.weather()
        for row in rows:
            del row["TMAX"]
        monthly = study.normalize_weather(rows, "USW00093738", "2017-01", "2017-01")
        self.assertEqual(monthly.iloc[0].valid_days, 0)
        self.assertTrue(pd.isna(monthly.iloc[0].tmean_c))

    def test_cpi_excludes_annual_average_and_rejects_duplicate_months(self):
        rows = [{"year": str(year), "period": f"M{month:02d}", "value": "250.5"}
                for year in range(2017, 2026) for month in range(1, 13)]
        rows.append({"year": "2025", "period": "M13", "value": "999"})
        payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
            {"seriesID": "CUUR0000SA0", "data": rows}]}}
        result = study.normalize_cpi(payload)
        self.assertEqual(len(result), 108)
        self.assertEqual(result.iloc[-1]["cpi_u"], 250.5)
        rows[0]["value"] = "-"
        rows[0]["footnotes"] = [{"code": "X", "text": "Data unavailable"}]
        missing = study.normalize_cpi(payload).iloc[0]
        self.assertTrue(pd.isna(missing.cpi_u))
        self.assertEqual(missing.cpi_note, "Data unavailable")
        rows.append(rows[0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            study.normalize_cpi(payload)

    def test_gas_uses_month_columns_and_preserves_units(self):
        html = '<title>Henry Hub Natural Gas Spot Price (Dollars per Million Btu)</title><table>'
        html += ''.join('<tr><td>' + str(year) + '</td>' + ''.join(
            f'<td>{month / 2}</td>' for month in range(1, 13)) + '</tr>' for year in range(2017, 2026))
        html += '</table>'
        result = study.normalize_gas(html)
        self.assertEqual(len(result), 108)
        self.assertEqual(result.loc[result.period.eq("2017-02"), "henry_hub_usd_mmbtu"].item(), 1)
        with self.assertRaisesRegex(ValueError, "units"):
            study.normalize_gas(html.replace("Million Btu", "kWh"))

    def test_cache_is_offline_and_failed_refresh_preserves_manifest_and_bytes(self):
        spec = {"id": "example", "url": "https://example.com/data.json", "method": "GET",
                "body": None, "filename": "data.json", "kind": "json"}
        response = requests.Response()
        response.status_code = 200
        response._content = b'[{"value":1}]'
        session = Mock()
        session.request.return_value = response
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = sources.collect_sources(directory, [spec], session)
            manifest_bytes = (directory / "manifest.json").read_bytes()
            session.request.side_effect = requests.ConnectionError("offline")
            self.assertEqual(sources.collect_sources(directory, [spec], session), first)
            with self.assertRaises(requests.ConnectionError):
                sources.collect_sources(directory, [spec], session, refresh=True)
            self.assertEqual((directory / "manifest.json").read_bytes(), manifest_bytes)
            entry = first["sources"][0]
            self.assertEqual(hashlib.sha256((directory / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
            (directory / entry["path"]).write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "checksum"):
                sources.collect_sources(directory, [spec], session)


if __name__ == "__main__":
    unittest.main()
