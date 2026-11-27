"""Normalize cached study sources, retaining weather coverage and source provenance."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_dominion_monthly_prices import FIELDS, read_year
from monthly_forecasting import availability_dates, load_protocol, protocol_hash
from pull_monthly_sources import DEFAULT_DIRECTORY, ROOT, STATIONS, atomic_write, read_manifest, source_requests


from monthly_source_parsers import check_months, normalize_cpi, normalize_gas, normalize_pjm, normalize_weather


def development_table(data):
    """Expose source history and validation outcomes for initial model development."""
    return data.loc[data.period.le(load_protocol()["partitions"]["validation"][1])].copy()


def build_study(directory):
    directory = Path(directory)
    manifest = read_manifest(directory)
    entries = {entry["id"]: entry for entry in manifest["sources"]}
    specs = {spec["id"]: spec for spec in source_requests()}
    if set(entries) != set(specs) or any(any(entries[key][field] != value for field, value in spec.items())
                                        for key, spec in specs.items()):
        raise ValueError("Manifest requests do not match this study's source definitions.")
    price_rows = []
    for year in range(2017, 2026):
        entry = entries[f"electricity_{year}"]
        price_rows.extend([(*row[:-1], entry["filename"]) for row in read_year(directory / entry["path"], year)])
    prices = check_months(pd.DataFrame(price_rows, columns=FIELDS))
    station_months = pd.concat([
        normalize_weather(json.loads((directory / entries[f"weather_{station}"]["path"]).read_bytes()), station)
        for station in STATIONS], ignore_index=True)
    weather = station_months.groupby("period").agg(
        weather_stations_valid=("meets_coverage", "sum"), weather_tmean_c=("tmean_c", "mean"),
        weather_hdd_c_days=("hdd_c_days", "mean"), weather_cdd_c_days=("cdd_c_days", "mean"))
    weather.loc[weather.weather_stations_valid.ne(3), ["weather_tmean_c", "weather_hdd_c_days", "weather_cdd_c_days"]] = np.nan
    cpi = normalize_cpi(json.loads((directory / entries["cpi"]["path"]).read_bytes()))
    gas = normalize_gas((directory / entries["gas"]["path"]).read_text(encoding="utf-8-sig"))
    data = prices.merge(weather, on="period", validate="one_to_one").merge(
        cpi, on="period", validate="one_to_one").merge(gas, on="period", validate="one_to_one")
    base_cpi = cpi.loc[cpi.period.str.startswith("2017-"), "cpi_u"].mean()
    data["real_price_2017_cents_per_kwh"] = data.price_cents_per_kwh * base_cpi / data.cpi_u
    protocol = load_protocol()
    data["electricity_available_date"] = availability_dates(data.period, "electricity", protocol).strftime("%Y-%m-%d")
    data["controls_available_date"] = availability_dates(data.period, "weather", protocol).strftime("%Y-%m-%d")
    pjm = normalize_pjm(directory / entries["pjm"]["path"])
    quality = dict(months=len(data), first_period=data.period.iloc[0], last_period=data.period.iloc[-1],
                   utility_id=19876, state="VA", missing_target_months=int(data.price_cents_per_kwh.isna().sum()),
                   station_months=len(station_months), station_months_below_95_percent=int((~station_months.meets_coverage).sum()),
                   missing_weather_proxy_months=int(data.weather_tmean_c.isna().sum()), pjm_context_years=len(pjm),
                   missing_cpi_months=data.loc[data.cpi_u.isna(), "period"].tolist(),
                   source_manifest_sha256=hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
                   sources=manifest["sources"], release_delays_are_assumptions=True,
                   protocol_sha256=protocol_hash(protocol),
                   backtest_vintage="lagged_final_vintage", cpi_base="2017 annual mean",
                   weather_proxy="Equal weight across all three qualifying station-months; missing when any station fails.")
    return data, station_months, pjm, quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed" / "monthly")
    args = parser.parse_args()
    try:
        data, weather, pjm, report = build_study(args.input_dir)
        development = development_table(data)
        report["development_months"] = len(development)
        outputs = {"study_monthly.csv": data.to_csv(index=False).encode(),
                   "study_development.csv": development.to_csv(index=False).encode(),
                   "weather_station_monthly.csv": weather.to_csv(index=False).encode(),
                   "pjm_large_load_context.csv": pjm.to_csv(index=False).encode()}
        report["output_sha256"] = {name: hashlib.sha256(content).hexdigest() for name, content in outputs.items()}
        for name, content in outputs.items():
            atomic_write(args.output_dir / name, content)
        atomic_write(args.output_dir / "quality.json", (json.dumps(report, indent=2, allow_nan=False) + "\n").encode())
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"Saved {len(data)} study months, {len(weather)} station-months and {len(pjm)} PJM context years.")
    print(f"Weather station-months below coverage threshold: {report['station_months_below_95_percent']}")


if __name__ == "__main__":
    main()
