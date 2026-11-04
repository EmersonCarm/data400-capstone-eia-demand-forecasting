"""Build the shared Parquet dataset from downloaded regional hourly CSVs.

This step is offline: it does not need an EIA key or modify source downloads.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGIONS = ("PJM", "ERCO", "CISO", "ISNE")
SOURCE_COLUMNS = {"timestamp_utc", "respondent", "demand_mwh", "forecast_mwh"}
OUTPUT_COLUMNS = ["ts_utc", "ba", "demand_mwh", "forecast_mwh", "is_imputed"]


def parse_hour(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a valid UTC hour in YYYY-MM-DDTHH format.") from None


def build_dataset(input_dir, regions, start, end):
    """Validate and stack CSV snapshots without filling or dropping measurements."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if pd.isna(start) or pd.isna(end) or start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Start and end must be timezone-aware hours.")
    start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
    if start > end or start != start.floor("h") or end != end.floor("h"):
        raise ValueError("Use an ordered start/end range aligned to complete UTC hours.")
    regions = [region.upper() for region in regions]
    if not regions or len(set(regions)) != len(regions):
        raise ValueError("Provide at least one region and no duplicate region codes.")
    if any(not region.isascii() or not region.isalnum() for region in regions):
        raise ValueError("Region codes must contain only letters and digits.")
    expected = pd.date_range(start, end, freq="h")
    frames, sources = [], []

    for region in regions:
        if region == "PJM" and start == pd.Timestamp("2025-09-01T00:00:00Z") and end == pd.Timestamp("2025-09-30T23:00:00Z"):
            filename = "pjm_2025_09_hourly.csv"
        else:
            filename = f"{region.lower()}_{start:%Y%m%dT%H}_{end:%Y%m%dT%H}_hourly.csv"
        source_bytes = (Path(input_dir) / filename).read_bytes()
        try:
            frame = pd.read_csv(BytesIO(source_bytes), dtype=str, keep_default_na=False)
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"{region}: could not read the regional CSV: {error}") from None
        if set(frame.columns) != SOURCE_COLUMNS:
            raise ValueError(f"{region}: expected exactly these source columns: {sorted(SOURCE_COLUMNS)}")
        if not frame["respondent"].eq(region).all():
            raise ValueError(f"{region}: the source contains a different or missing region code.")
        if not frame["timestamp_utc"].str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True).all():
            raise ValueError(f"{region}: source timestamps must include an explicit timezone.")
        try:
            frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], format="ISO8601", utc=True)
            for column in ("demand_mwh", "forecast_mwh"):
                values = frame[column].mask(frame[column].eq(""), float("nan"))
                frame[column] = pd.to_numeric(values, errors="raise").astype("float64")
                if frame[column].isin([float("inf"), -float("inf")]).any():
                    raise ValueError(f"{column} contains infinite values")
        except (ValueError, TypeError) as error:
            raise ValueError(f"{region}: invalid timestamp or measurement: {error}") from None
        if frame["timestamp_utc"].duplicated().any():
            raise ValueError(f"{region}: duplicate hourly timestamps.")
        frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
        if not pd.DatetimeIndex(frame["timestamp_utc"]).equals(expected):
            raise ValueError(f"{region}: source must contain exactly the requested complete hourly grid.")
        frame = frame.rename(columns={"timestamp_utc": "ts_utc", "respondent": "ba"})
        frame["ba"] = frame["ba"].astype("string")
        frame["is_imputed"] = False
        frames.append(frame[OUTPUT_COLUMNS])
        sources.append({"region": region, "file": filename,
                        "sha256": hashlib.sha256(source_bytes).hexdigest()})

    data = pd.concat(frames, ignore_index=True).sort_values(["ba", "ts_utc"]).reset_index(drop=True)
    missing = pd.concat([
        data.loc[data[column].isna(), ["ts_utc", "ba"]].assign(measurement=column)
        for column in ("demand_mwh", "forecast_mwh")
    ], ignore_index=True).sort_values(["ba", "ts_utc", "measurement"]).reset_index(drop=True)
    quality = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_utc": start.strftime("%Y-%m-%dT%H"),
        "end_utc": end.strftime("%Y-%m-%dT%H"),
        "rows_total": len(data),
        "hours_per_region": len(expected),
        "missing_demand_hours": int(data["demand_mwh"].isna().sum()),
        "missing_forecast_hours": int(data["forecast_mwh"].isna().sum()),
        "missing_measurement_entries": len(missing),
        "imputed_rows": 0,
        "regions": {
            region: {"rows": len(portion),
                     "missing_demand_hours": int(portion["demand_mwh"].isna().sum()),
                     "missing_forecast_hours": int(portion["forecast_mwh"].isna().sum())}
            for region, portion in data.groupby("ba", sort=True)
        },
        "sources": sources,
        "schema": {column: str(data[column].dtype) for column in OUTPUT_COLUMNS},
    }
    return data, missing, quality


def write_outputs(data, missing, quality, output_dir):
    """Stage all serializations, then atomically replace individual output files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".shared-dataset-", dir=output_dir) as directory:
        staging = Path(directory)
        data.to_parquet(staging / "demand_hourly.parquet", engine="pyarrow", compression="zstd", index=False)
        missing.to_csv(staging / "demand_hourly_missing_hours.csv", index=False)
        report = dict(quality, output_sha256={
            filename: hashlib.sha256((staging / filename).read_bytes()).hexdigest()
            for filename in ("demand_hourly.parquet", "demand_hourly_missing_hours.csv")
        })
        (staging / "demand_hourly_quality.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        for filename in ("demand_hourly.parquet", "demand_hourly_missing_hours.csv", "demand_hourly_quality.json"):
            (staging / filename).replace(output_dir / filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="+", default=DEFAULT_REGIONS, type=str.upper)
    parser.add_argument("--start", type=parse_hour, default="2019-01-01T00")
    parser.add_argument("--end", type=parse_hour, default="2025-12-31T23")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data" / "processed")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed")
    args = parser.parse_args()
    try:
        data, missing, quality = build_dataset(args.input_dir, args.regions, args.start, args.end)
        write_outputs(data, missing, quality, args.output_dir)
    except FileNotFoundError as error:
        parser.error(f"Missing regional input: {error.filename}. Download the same region and date range first.")
    except (ValueError, OSError, ImportError) as error:
        parser.error(str(error))
    print(f"Shared dataset saved: {args.output_dir / 'demand_hourly.parquet'}")
    print(f"Rows: {quality['rows_total']}; regions: {', '.join(sorted(quality['regions']))}")
    print(f"Missing demand hours: {quality['missing_demand_hours']}; missing forecast hours: {quality['missing_forecast_hours']}")
    print("No values were imputed. Missing-hour log and quality report saved beside the dataset.")


if __name__ == "__main__":
    main()
