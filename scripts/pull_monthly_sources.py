"""Cache public 2017–2025 study sources and publish a checksum manifest."""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from zipfile import BadZipFile, ZipFile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from build_dominion_monthly_prices import read_year
from monthly_source_parsers import normalize_cpi, normalize_gas, normalize_pjm, normalize_weather


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "data" / "raw" / "monthly_sources"
STATIONS = ("USW00093738", "USW00013740", "USW00013737")


def source_requests():
    specs = []
    for year in range(2017, 2026):
        stem = "retail_sales" if year <= 2020 else "sales_ult_cust"
        filename = f"{stem}_{year}.xlsx"
        specs.append(dict(id=f"electricity_{year}", method="GET", body=None,
                          url=f"https://www.eia.gov/electricity/data/eia861m/archive/xls/{filename}",
                          filename=filename, kind="xlsx"))
    for station in STATIONS:
        params = dict(dataset="daily-summaries", stations=station, startDate="2017-01-01",
                      endDate="2025-12-31", dataTypes="TMAX,TMIN", units="metric", format="json",
                      includeAttributes="true", includeStationName="true")
        specs.append(dict(id=f"weather_{station}", method="GET", body=None,
                          url="https://www.ncei.noaa.gov/access/services/data/v1?" + urlencode(params),
                          filename=f"{station}.json", kind="json"))
    specs.extend([
        dict(id="cpi", method="POST", url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
             body=dict(seriesid=["CUUR0000SA0"], startyear="2017", endyear="2025"),
             filename="cpi.json", kind="json"),
        dict(id="gas", method="GET", body=None,
             url="https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm", filename="henry_hub.html", kind="html"),
        dict(id="pjm", method="GET", body=None,
             url="https://www.pjm.com/-/media/DotCom/planning/res-adeq/load-forecast/2026-accuracy-report.xlsx",
             filename="2026-accuracy-report.xlsx", kind="xlsx"),
    ])
    return specs


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_manifest(directory):
    """Read only the exact immutable bytes referenced by a completed manifest."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported source manifest schema.")
    ids = [entry["id"] for entry in manifest["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source IDs in the manifest.")
    for entry in manifest["sources"]:
        path = (directory / entry["path"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Source path escapes the manifest directory.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Source checksum mismatch for {entry['id']}.")
    return manifest


def validate_source_snapshot(spec, path):
    """Use the offline builder's parsers before promoting a new source manifest."""
    try:
        if spec["id"].startswith("electricity_"):
            read_year(path, int(spec["id"].split("_")[-1]))
        elif spec["id"].startswith("weather_"):
            normalize_weather(json.loads(path.read_bytes()), spec["id"].removeprefix("weather_"))
        elif spec["id"] == "cpi":
            normalize_cpi(json.loads(path.read_bytes()))
        elif spec["id"] == "gas":
            normalize_gas(path.read_text(encoding="utf-8-sig"))
        elif spec["id"] == "pjm":
            normalize_pjm(path)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid source contents for {spec['id']}: {error}") from error


def collect_sources(directory, specs, session, *, legacy_dir=None, refresh=False):
    directory = Path(directory)
    if (directory / "manifest.json").exists() and not refresh:
        manifest = read_manifest(directory)
        saved = [{key: entry[key] for key in spec} for entry, spec in zip(manifest["sources"], specs)]
        if len(manifest["sources"]) != len(specs) or saved != specs:
            raise ValueError("Cached requests differ from this study. Use --refresh.")
        return manifest

    entries = []
    for spec in specs:
        legacy = Path(legacy_dir) / spec["filename"] if legacy_dir else None
        if not refresh and spec["id"].startswith("electricity_") and legacy and legacy.exists():
            content = legacy.read_bytes()
            retrieved = None
            provenance = "imported_local_retrieval_time_unknown"
        else:
            response = session.request(spec["method"], spec["url"], json=spec["body"], timeout=(15, 90))
            response.raise_for_status()
            content = response.content
            retrieved = datetime.now(timezone.utc).isoformat()
            provenance = "downloaded"
        if spec["kind"] == "xlsx":
            with ZipFile(BytesIO(content)) as archive:
                if "xl/workbook.xml" not in archive.namelist() or archive.testzip():
                    raise ValueError(f"Invalid workbook for {spec['id']}.")
        elif spec["kind"] == "json":
            payload = json.loads(content)
            if spec["id"] == "cpi" and payload.get("status") != "REQUEST_SUCCEEDED":
                raise ValueError(f"BLS request failed: {payload.get('message')}")
        elif b"Henry Hub Natural Gas Spot Price" not in content:
            raise ValueError("Unexpected EIA gas response.")
        digest = hashlib.sha256(content).hexdigest()
        filename = f"{digest}{Path(spec['filename']).suffix}"
        atomic_write(directory / filename, content)
        validate_source_snapshot(spec, directory / filename)
        entries.append(dict(spec, path=filename, sha256=digest, retrieved_at_utc=retrieved,
                            provenance=provenance))
        print(f"Cached {spec['id']}", flush=True)

    manifest = dict(schema_version=1, sources=entries)
    atomic_write(directory / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        with requests.Session() as session:
            retries = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                            allowed_methods=("GET", "POST"))
            session.mount("https://", HTTPAdapter(max_retries=retries))
            manifest = collect_sources(args.output_dir, source_requests(), session,
                                       legacy_dir=ROOT / "data" / "raw" / "eia861m", refresh=args.refresh)
    except (OSError, ValueError, BadZipFile, requests.RequestException) as error:
        parser.error(str(error))
    print(f"Verified {len(manifest['sources'])} sources in {args.output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
