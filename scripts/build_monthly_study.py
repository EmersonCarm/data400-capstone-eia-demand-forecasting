"""Normalize cached study sources, retaining weather coverage and source provenance."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

import numpy as np
from openpyxl import load_workbook
import pandas as pd

from build_dominion_monthly_prices import FIELDS, read_year
from monthly_forecasting import availability_dates, load_protocol, protocol_hash
from pull_monthly_sources import DEFAULT_DIRECTORY, ROOT, STATIONS, atomic_write, read_manifest, source_requests


MONTHS = pd.period_range("2017-01", "2025-12", freq="M").astype(str).tolist()


def check_months(frame):
    if frame["period"].duplicated().any():
        raise ValueError("Source contains duplicate months.")
    frame = frame.sort_values("period").reset_index(drop=True)
    if frame["period"].tolist() != MONTHS:
        raise ValueError("Source must cover every month of 2017–2025 exactly once.")
    return frame


def normalize_weather(records, station, start="2017-01", end="2025-12"):
    frame = pd.DataFrame(records)
    if frame.empty or not frame["STATION"].eq(station).all():
        raise ValueError("Weather records have a missing or unexpected station.")
    frame["date"] = pd.to_datetime(frame["DATE"], format="%Y-%m-%d", errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError("Weather contains duplicate station-date keys.")
    calendar = pd.date_range(pd.Period(start).start_time, pd.Period(end).end_time.normalize(), freq="D")
    if not frame["date"].isin(calendar).all():
        raise ValueError("Weather contains dates outside the requested calendar.")
    frame = frame.set_index("date").reindex(calendar)
    good = pd.Series(True, index=calendar)
    for field in ("TMAX", "TMIN"):
        values = pd.to_numeric(frame.get(field, pd.Series(index=calendar, dtype=float)), errors="coerce")
        attributes = frame.get(f"{field}_ATTRIBUTES", pd.Series(index=calendar, dtype=str))
        flag_ok = attributes.fillna("").map(lambda value: len(value.split(",")) >= 3 and not value.split(",")[1].strip())
        good &= np.isfinite(values) & values.between(-100, 70) & flag_ok
        frame[field] = values
    good &= frame["TMAX"].ge(frame["TMIN"])
    mean = ((frame["TMAX"] + frame["TMIN"]) / 2).where(good)
    daily = pd.DataFrame({"valid": good.astype(int), "tmean_c": mean,
                          "hdd_c_days": (18.33 - mean).clip(lower=0),
                          "cdd_c_days": (mean - 18.33).clip(lower=0)})
    monthly = daily.groupby(calendar.to_period("M")).agg(
        valid_days=("valid", "sum"), tmean_c=("tmean_c", "mean"),
        hdd_c_days=("hdd_c_days", "sum"), cdd_c_days=("cdd_c_days", "sum"))
    monthly["expected_days"] = monthly.index.days_in_month
    monthly["coverage_fraction"] = monthly["valid_days"] / monthly["expected_days"]
    monthly["meets_coverage"] = monthly["coverage_fraction"].ge(.95)
    monthly.loc[~monthly["meets_coverage"], ["tmean_c", "hdd_c_days", "cdd_c_days"]] = np.nan
    monthly["period"] = monthly.index.astype(str)
    monthly["station_id"] = station
    return monthly.reset_index(drop=True)


def normalize_cpi(payload):
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS did not report a successful request.")
    series = payload["Results"]["series"]
    if len(series) != 1 or series[0]["seriesID"] != "CUUR0000SA0":
        raise ValueError("Expected national non-seasonally-adjusted CPI-U series CUUR0000SA0.")
    rows = []
    for item in series[0]["data"]:
        period = item["period"]
        if period == "M13":
            continue
        if period not in {f"M{month:02d}" for month in range(1, 13)}:
            raise ValueError("Unexpected BLS period.")
        value = np.nan if item["value"] == "-" else float(item["value"])
        note = " | ".join(footnote.get("text", "") for footnote in item.get("footnotes", []) if footnote)
        rows.append(dict(period=f"{int(item['year']):04d}-{period[1:]}", cpi_u=value, cpi_note=note))
    frame = check_months(pd.DataFrame(rows))
    reported = frame.cpi_u.dropna()
    if not (np.isfinite(reported) & reported.gt(0)).all():
        raise ValueError("CPI must contain positive finite values.")
    return frame


class GasTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        elif tag == "tr":
            self.rows.append(self.row)


def normalize_gas(html):
    if "Henry Hub Natural Gas Spot Price" not in html or "Dollars per Million Btu" not in html:
        raise ValueError("Unexpected gas series or units.")
    parser = GasTable()
    parser.feed(html)
    records = []
    for row in parser.rows:
        if row and row[0] in {str(year) for year in range(2017, 2026)}:
            if len(row) != 13:
                raise ValueError("Expected twelve monthly gas values per year.")
            for month, value in enumerate(row[1:], 1):
                records.append(dict(period=f"{row[0]}-{month:02d}", henry_hub_usd_mmbtu=float(value)))
    frame = check_months(pd.DataFrame(records))
    if not np.isfinite(frame.henry_hub_usd_mmbtu).all():
        raise ValueError("Gas contains nonfinite values.")
    return frame


def normalize_pjm(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook["DOM - Dominion Energy"].iter_rows(values_only=True)
        if next(rows) != ("Zone", "Year", "Metric", "Load MW"):
            raise ValueError("Unexpected PJM workbook headers.")
        records = [dict(zone=zone, year=year, metric=metric, historical_july_peak_mw=value,
                        provider="Dominion Energy", report_vintage=2026,
                        geographic_mapping="context_only_unverified_utility_crosswalk")
                   for zone, year, metric, value in rows if metric == "Historical July Peak" and 2017 <= year <= 2025]
    finally:
        workbook.close()
    frame = pd.DataFrame(records).sort_values("year").reset_index(drop=True)
    if frame.year.tolist() != list(range(2017, 2026)) or not frame.zone.eq("DOM Energy").all():
        raise ValueError("Expected nine distinct Dominion Energy historical July peaks.")
    if not (np.isfinite(frame.historical_july_peak_mw) & frame.historical_july_peak_mw.ge(0)).all():
        raise ValueError("Invalid PJM peak values.")
    return frame


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
        outputs = {"study_monthly.csv": data.to_csv(index=False).encode(),
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
