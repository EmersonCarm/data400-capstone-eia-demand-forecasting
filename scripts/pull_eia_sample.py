"""Download hourly demand and forecasts for one balancing authority from EIA-930.

Run from repository root:
    python scripts/pull_eia_sample.py

Downloads require EIA_API_KEY in the environment or repository-root .env file.
Matching cached downloads can be reused offline. Use --refresh to fetch updates.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import pandas as pd
import requests
from dotenv import load_dotenv


def read_cache(cache_path, request):
    """Read a complete download for exactly this public request identity."""
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("Could not read the cached download. Run with --refresh to replace it.") from None
    if (
        not isinstance(cached, dict)
        or cached.get("version") != 1
        or cached.get("request") != request
        or type(cached.get("total")) is not int
        or not isinstance(cached.get("records"), list)
        or cached["total"] <= 0
        or len(cached["records"]) != cached["total"]
        or any(not isinstance(row, dict) for row in cached["records"])
    ):
        raise SystemExit("Cached download is incomplete or does not match this request. Run with --refresh.")
    return cached["records"]


def write_cache(cache_path, request, records):
    """Atomically publish validated records, without the API request envelope."""
    cached = {
        "version": 1,
        "request": request,
        "total": len(records),
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    temporary_path = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=cache_path.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(cached, temporary, allow_nan=False)
            temporary.write("\n")
        temporary_path.replace(cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


parser = argparse.ArgumentParser(
    description="Download hourly electricity demand and forecasts from EIA."
)
parser.add_argument("--ba", default="PJM", type=str.upper, help="Balancing authority code")
parser.add_argument("--start", default="2025-09-01T00", help="Inclusive start UTC hour (YYYY-MM-DDTHH)")
parser.add_argument("--end", default="2025-09-30T23", help="Inclusive end UTC hour (YYYY-MM-DDTHH)")
parser.add_argument("--refresh", action="store_true", help="Download again and replace the matching cache")
args = parser.parse_args()

if not args.ba.isascii() or not args.ba.isalnum():
    parser.error("--ba must contain only letters and digits.")

hour_format = "%Y-%m-%dT%H"
try:
    start_utc = datetime.strptime(args.start, hour_format).replace(tzinfo=timezone.utc)
    end_utc = datetime.strptime(args.end, hour_format).replace(tzinfo=timezone.utc)
except ValueError:
    parser.error("--start and --end must be valid UTC hours in YYYY-MM-DDTHH format.")
if start_utc > end_utc:
    parser.error("--start must be earlier than or equal to --end.")
args.start = start_utc.strftime(hour_format)
args.end = end_utc.strftime(hour_format)

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
api_key = os.getenv("EIA_API_KEY")

raw_folder = ROOT / "data" / "raw"
processed_folder = ROOT / "data" / "processed"
docs_folder = ROOT / "docs"
# Keep the committed sample's filenames for the original default request.
is_original_sample = (
    args.ba == "PJM" and args.start == "2025-09-01T00" and args.end == "2025-09-30T23"
)
prefix = (
    "pjm_2025_09"
    if is_original_sample
    else f"{args.ba.lower()}_{start_utc:%Y%m%dT%H}_{end_utc:%Y%m%dT%H}"
)
raw_path = raw_folder / f"{prefix}_eia_long.csv"
processed_path = processed_folder / f"{prefix}_hourly.csv"
quality_path = docs_folder / (
    "sample_quality.json" if is_original_sample else f"{prefix}_quality.json"
)
cache_path = ROOT / ".cache" / "eia" / f"{prefix}.json"

url = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
cache_request = {
    "endpoint": url,
    "frequency": "hourly",
    "respondent": args.ba,
    "types": ["D", "DF"],
    "start": args.start,
    "end": args.end,
}
params = {
    "api_key": api_key,
    "frequency": "hourly",        # UTC hours
    "data[0]": "value",
    "facets[respondent][]": args.ba,
    "facets[type][]": ["D", "DF"],  # actual demand and forecast
    "start": args.start,
    "end": args.end,
    "sort[0][column]": "period",
    "sort[0][direction]": "asc",
    "sort[1][column]": "type",
    "sort[1][direction]": "asc",
    "offset": 0,
    "length": 5000,
}

cache_hit = cache_path.exists() and not args.refresh
if cache_hit:
    records = read_cache(cache_path, cache_request)
    print(f"Using cached download: {cache_path.relative_to(ROOT)} ({len(records)} records).")
else:
    if not api_key:
        raise SystemExit("Missing EIA_API_KEY. Put EIA_API_KEY=... in a .env file in the repository root.")
    records = []
    total = None
    while total is None or len(records) < total:
        page_params = {**params, "offset": len(records)}
        try:
            response = requests.get(url, params=page_params, timeout=60)
        except requests.RequestException:
            raise SystemExit("Could not reach the EIA API. Check your connection and try again.") from None

        # Do not print request URLs: an EIA API key appears in their query parameters.
        if response.status_code != 200:
            raise SystemExit(f"EIA request returned HTTP {response.status_code}. Check the key, filters, or API availability.")

        try:
            payload = response.json().get("response", {})
        except (ValueError, AttributeError):
            raise SystemExit("EIA returned an invalid JSON response. Retry the request.") from None
        if not isinstance(payload, dict):
            raise SystemExit("EIA returned an invalid data response. Retry the request.")
        page = payload.get("data", [])
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise SystemExit("EIA returned invalid data rows. Retry the request.")
        try:
            page_total = int(payload["total"])
            if page_total < 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise SystemExit("EIA response did not include a valid total row count.") from None
        if total is None:
            total = page_total
        elif page_total != total:
            raise SystemExit(f"EIA's total changed from {total} to {page_total} during download. Retry the request.")

        if not page:
            if not records:
                raise SystemExit("The EIA API returned zero data rows. Check the respondent, dates, and type facets.")
            raise SystemExit(f"EIA stopped returning rows after {len(records)} of {total} records. No files were saved.")
        if len(records) + len(page) > total:
            raise SystemExit("EIA returned more rows than its reported total. Retry the request.")
        records.extend(page)
        print(f"Downloaded {len(records)} of {total} records.")

raw = pd.DataFrame(records)
required = {"period", "respondent", "type", "value"}
missing_fields = required - set(raw.columns)
if missing_fields:
    raise SystemExit(f"Missing EIA columns: {sorted(missing_fields)}")
if not raw["respondent"].eq(args.ba).all():
    raise SystemExit("EIA records include an unexpected balancing authority. Check the data or use --refresh.")
if not raw["type"].isin(["D", "DF"]).all():
    raise SystemExit("EIA records include an unexpected measurement type. Check the data or use --refresh.")

raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
raw["timestamp_utc"] = pd.to_datetime(raw["period"], format="%Y-%m-%dT%H", utc=True, errors="coerce")
if raw["timestamp_utc"].isna().any():
    raise SystemExit("At least one hourly timestamp could not be interpreted. Inspect the EIA date format.")
if ((raw["timestamp_utc"] < start_utc) | (raw["timestamp_utc"] > end_utc)).any():
    raise SystemExit("EIA records include hours outside the requested range. Check the data or use --refresh.")

repeated = int(raw.duplicated(subset=["period", "respondent", "type"]).sum())
if repeated:
    raise SystemExit(f"Found {repeated} duplicate hour/authority/type records. Investigate before pivoting.")

for folder in (raw_folder, processed_folder, docs_folder):
    folder.mkdir(parents=True, exist_ok=True)

raw.to_csv(raw_path, index=False)

wide = raw.pivot(index="timestamp_utc", columns="type", values="value")
wide = wide.reindex(columns=["D", "DF"])
wide = wide.rename(columns={"D": "demand_mwh", "DF": "forecast_mwh"})
expected = pd.date_range(start_utc, end_utc, freq="h")
wide = wide.reindex(expected).rename_axis("timestamp_utc").reset_index()
wide.insert(1, "respondent", args.ba)
wide = wide[["timestamp_utc", "respondent", "demand_mwh", "forecast_mwh"]]
wide.to_csv(processed_path, index=False)

quality = {
    "source": "EIA Open Data v2: electricity/rto/region-data (Form EIA-930)",
    "respondent": args.ba,
    "start_utc": args.start,
    "end_utc": args.end,
    "hourly_rows_expected": len(expected),
    "records_received_long_format": len(raw),
    "actual_demand_rows": int((raw["type"] == "D").sum()),
    "forecast_rows": int((raw["type"] == "DF").sum()),
    "missing_actual_demand_hours": int(wide["demand_mwh"].isna().sum()),
    "missing_forecast_hours": int(wide["forecast_mwh"].isna().sum()),
    "duplicate_hour_type_rows": repeated,
}
quality_path.write_text(json.dumps(quality, indent=2) + "\n")
if not cache_hit:
    write_cache(cache_path, cache_request, records)

print("\nEIA sample saved successfully.")
print(json.dumps(quality, indent=2))
print("\nProcessed sample preview:")
print(wide.head().to_string(index=False))
print("\nFiles written:")
for output_path in (raw_path, processed_path, quality_path):
    print(f"  {output_path.relative_to(ROOT)}")
