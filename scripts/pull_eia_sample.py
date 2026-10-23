"""Download a one-month hourly PJM demand + forecast working sample from EIA-930.

Run from repository root:
    python scripts/pull_eia_sample.py

Requires EIA_API_KEY in the repository-root .env file.
"""

import json
import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
api_key = os.getenv("EIA_API_KEY")
if not api_key:
    raise SystemExit("Missing EIA_API_KEY. Put EIA_API_KEY=... in a .env file in the repository root.")

url = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
params = {
    "api_key": api_key,
    "frequency": "hourly",        # UTC hours
    "data[0]": "value",
    "facets[respondent][]": "PJM",
    "facets[type][]": ["D", "DF"],  # actual demand and forecast
    "start": "2025-09-01T00",
    "end": "2025-09-30T23",
    "sort[0][column]": "period",
    "sort[0][direction]": "asc",
    "offset": 0,
    "length": 5000,
}

try:
    response = requests.get(url, params=params, timeout=60)
except requests.RequestException as exc:
    raise SystemExit("Could not reach the EIA API. Check your connection and try again.") from None

# Do not print request URLs: an EIA API key appears in their query parameters.
if response.status_code != 200:
    raise SystemExit(f"EIA request returned HTTP {response.status_code}. Check the key, filters, or API availability.")

payload = response.json().get("response", {})
records = payload.get("data", [])
if not records:
    raise SystemExit("The EIA API returned zero data rows. Check the respondent, dates, and type facets.")

total = int(payload.get("total", len(records)))
if total > len(records):
    raise SystemExit(f"This sample needs pagination: received {len(records)} of {total} rows.")

raw = pd.DataFrame(records)
required = {"period", "respondent", "type", "value"}
missing_fields = required - set(raw.columns)
if missing_fields:
    raise SystemExit(f"Missing EIA columns: {sorted(missing_fields)}")

raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
raw["timestamp_utc"] = pd.to_datetime(raw["period"], format="%Y-%m-%dT%H", utc=True, errors="coerce")
if raw["timestamp_utc"].isna().any():
    raise SystemExit("At least one hourly timestamp could not be interpreted. Inspect the EIA date format.")

repeated = int(raw.duplicated(subset=["period", "respondent", "type"]).sum())
if repeated:
    raise SystemExit(f"Found {repeated} duplicate hour/authority/type records. Investigate before pivoting.")

if not {"D", "DF"}.issubset(set(raw["type"])):
    raise SystemExit("The sample did not include both demand (D) and forecast (DF).")

raw_folder = ROOT / "data" / "raw"
processed_folder = ROOT / "data" / "processed"
docs_folder = ROOT / "docs"
for folder in (raw_folder, processed_folder, docs_folder):
    folder.mkdir(parents=True, exist_ok=True)

raw.to_csv(raw_folder / "pjm_2025_09_eia_long.csv", index=False)

wide = raw.pivot(index="timestamp_utc", columns="type", values="value")
wide = wide.rename(columns={"D": "demand_mwh", "DF": "forecast_mwh"})
expected = pd.date_range("2025-09-01T00:00:00Z", "2025-09-30T23:00:00Z", freq="h")
wide = wide.reindex(expected).rename_axis("timestamp_utc").reset_index()
wide.insert(1, "respondent", "PJM")
wide = wide[["timestamp_utc", "respondent", "demand_mwh", "forecast_mwh"]]
wide.to_csv(processed_folder / "pjm_2025_09_hourly.csv", index=False)

quality = {
    "source": "EIA Open Data v2: electricity/rto/region-data (Form EIA-930)",
    "respondent": "PJM",
    "start_utc": "2025-09-01T00",
    "end_utc": "2025-09-30T23",
    "hourly_rows_expected": len(expected),
    "records_received_long_format": len(raw),
    "actual_demand_rows": int((raw["type"] == "D").sum()),
    "forecast_rows": int((raw["type"] == "DF").sum()),
    "missing_actual_demand_hours": int(wide["demand_mwh"].isna().sum()),
    "missing_forecast_hours": int(wide["forecast_mwh"].isna().sum()),
    "duplicate_hour_type_rows": repeated,
}
(docs_folder / "sample_quality.json").write_text(json.dumps(quality, indent=2) + "\n")

print("\nEIA sample saved successfully.")
print(json.dumps(quality, indent=2))
print("\nProcessed sample preview:")
print(wide.head().to_string(index=False))
print("\nFiles written:")
print("  data/raw/pjm_2025_09_eia_long.csv")
print("  data/processed/pjm_2025_09_hourly.csv")
print("  docs/sample_quality.json")
