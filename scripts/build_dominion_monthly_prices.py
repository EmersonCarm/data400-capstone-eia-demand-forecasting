"""Build a monthly Dominion Virginia residential dataset from local EIA-861M workbooks."""

import argparse
import csv
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


ROOT = Path(__file__).resolve().parents[1]
UTILITY_ID = 19876
STATE = "VA"
SHEET_NAME = "Sales Ultimate Cust. -States"
FIELDS = (
    "period", "utility_id", "utility_name", "state", "data_status",
    "revenue_thousand_usd", "sales_mwh", "customers", "price_cents_per_kwh",
    "kwh_per_customer", "ownership", "source_file",
)


def read_year(path, year):
    """Read the residential data after checking the sector and units in the source header."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise ValueError(f"{path.name}: missing worksheet {SHEET_NAME!r}.")
        source_rows = workbook[SHEET_NAME].iter_rows(max_col=10, values_only=True)
        sector, measure, units = (next(source_rows, ()) for _ in range(3))
        if (sector[7:8] != ("RESIDENTIAL",)
                or measure[7:10] != ("Revenue", "Sales", "Customers")
                or units[:7] != ("Year", "Month", "Utility Number", "Utility Name", "State", "Ownership", "Data Status")
                or units[7:10] != ("Thousands Dollars", "Megawatthours", "Count")):
            raise ValueError(f"{path.name}: unexpected residential headers or units.")

        rows = []
        for row_year, month, utility_id, name, state, ownership, status, revenue, sales, customers in source_rows:
            if (utility_id, state) != (UTILITY_ID, STATE):
                continue
            if row_year != year or type(month) is not int or not 1 <= month <= 12:
                raise ValueError(f"{path.name}: unexpected year or month in a Dominion Virginia row.")
            period = f"{year}-{month:02d}"
            for field, value in zip(FIELDS[5:8], (revenue, sales, customers)):
                if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                    raise ValueError(f"{path.name}: expected a positive numeric {field} for {period}.")
            if int(customers) != customers:
                raise ValueError(f"{path.name}: expected a whole customer count for {period}.")
            rows.append((period, UTILITY_ID, name, STATE, status, revenue, sales, int(customers),
                         100 * revenue / sales, 1000 * sales / customers, ownership, path.name))
    finally:
        workbook.close()

    rows.sort(key=lambda row: row[0])
    if [row[0] for row in rows] != [f"{year}-{month:02d}" for month in range(1, 13)]:
        raise ValueError(f"{path.name}: expected one row for every month of {year}.")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data" / "raw" / "eia861m")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed")
    args = parser.parse_args()
    if not 2017 <= args.start_year <= args.end_year <= 2025:
        parser.error("Choose an ordered year range within 2017–2025.")

    rows = []
    try:
        for year in range(args.start_year, args.end_year + 1):
            stem = "retail_sales" if year <= 2020 else "sales_ult_cust"
            rows.extend(read_year(args.input_dir / f"{stem}_{year}.xlsx", year))

        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / f"dominion_va_residential_{args.start_year}_{args.end_year}.csv"
        stream = NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".tmp",
                                    dir=args.output_dir, delete=False)
        temporary = Path(stream.name)
        try:
            with stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                writer.writerows(rows)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    except FileNotFoundError as error:
        parser.error(f"Missing workbook: {error.filename}. See the EIA-861M download instructions in the README.")
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Saved {len(rows)} monthly rows ({rows[0][0]} through {rows[-1][0]}) to {output}")


if __name__ == "__main__":
    main()
