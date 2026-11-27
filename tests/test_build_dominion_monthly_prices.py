import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openpyxl import Workbook


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_dominion_monthly_prices.py"


class DominionMonthlyPricesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.output = self.directory / "dominion_va_residential_2019_2019.csv"

    def run_builder(self, months, *, sales=2000, residential_units="Thousands Dollars"):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales Ultimate Cust. -States"
        sheet.append(["UTILITY CHARATERISTICS", None, None, None, None, None, None, "RESIDENTIAL", None, None, "COMMERCIAL"])
        sheet.append([None] * 7 + ["Revenue", "Sales", "Customers", "Revenue", "Sales", "Customers"])
        sheet.append(["Year", "Month", "Utility Number", "Utility Name", "State", "Ownership", "Data Status",
                      residential_units, "Megawatthours", "Count", "Thousands Dollars", "Megawatthours", "Count"])
        for month in months:
            sheet.append([2019, month, 19876, "Virginia Electric & Power Co", "VA", "Investor Owned", "Final",
                          250, sales, 1000, 900, 6000, 20])
        sheet.append([2019, 1, 19876, "Virginia Electric & Power Co", "NC"])
        sheet.append([2019, 1, 0, "State Adjustment", "VA"])
        workbook.save(self.directory / "retail_sales_2019.xlsx")
        return subprocess.run([sys.executable, str(SCRIPT), "--start-year", "2019", "--end-year", "2019",
                               "--input-dir", str(self.directory), "--output-dir", str(self.directory)],
                              capture_output=True, text=True)

    def test_builds_sorted_residential_prices_for_the_virginia_utility(self):
        result = self.run_builder(range(12, 0, -1))
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.output.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["period"] for row in rows], [f"2019-{month:02d}" for month in range(1, 13)])
        self.assertEqual({(row["utility_id"], row["state"]) for row in rows}, {("19876", "VA")})
        self.assertEqual(float(rows[0]["price_cents_per_kwh"]), 12.5)
        self.assertEqual(float(rows[0]["kwh_per_customer"]), 2000)
        self.assertEqual(rows[0]["ownership"], "Investor Owned")

    def test_rejects_repeated_month_even_when_row_count_is_correct(self):
        result = self.run_builder([*range(1, 12), 11])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected one row for every month", result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_revenue_units_and_zero_sales(self):
        for options, message in [({"residential_units": "Dollars"}, "residential headers"),
                                 ({"sales": 0}, "sales_mwh")]:
            with self.subTest(options=options):
                result = self.run_builder(range(1, 13), **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
