# Shared dataset handoff

## What Emerson receives

The shared input for EDA and feature engineering is
`data/processed/demand_hourly.parquet`. It uses the five columns described in
[DATA_DICTIONARY.md](DATA_DICTIONARY.md). Read that dictionary before interpreting
units, hourly labels, or missing values.

Large downloads, caches, and the generated Parquet file stay local. Git contains
the builder, tests, documentation, and the original small public sample. Each team
member can reproduce the dataset with their own EIA key; a key is not needed for
the offline build once the four source CSVs exist.

## Reproduce the selected dataset

Run these commands from the repository root in the checkout containing the shared
dataset builder. Reuse an existing environment if it has already been created.

```bash
conda activate data400-eia
python -m pip install -r requirements.txt
```

Set `EIA_API_KEY` in your local `.env` file as described in the main README. Download
the same region and time window for each input; matching completed caches are reused:

```bash
for region_code in PJM ERCO CISO ISNE; do
  python scripts/pull_eia_sample.py --ba "$region_code" \
    --start 2019-01-01T00 --end 2025-12-31T23 || break
done
```

Then build the shared file offline:

```bash
python scripts/build_shared_dataset.py
```

Defaults are all four regions and the 2019–2025 window. `--regions`, `--start`,
`--end`, `--input-dir`, and `--output-dir` can override them. Source filenames must
match the collector's naming convention and exact requested window. The original
September PJM sample's filename is also supported.

For example, a quick offline check using only the committed sample is:

```bash
python scripts/build_shared_dataset.py --regions PJM \
  --start 2025-09-01T00 --end 2025-09-30T23 --output-dir /tmp/eia-sample-handoff
```

## Read the file in Python

From the repository root:

```python
import pandas as pd

data = pd.read_parquet("data/processed/demand_hourly.parquet", engine="pyarrow")
print(data.head())
print(data.groupby("ba").size())
print(data[["demand_mwh", "forecast_mwh"]].isna().sum())
```

For the verified snapshot, expect 245,472 rows across four regions, 147 missing
demand values, 360 missing forecasts, and all `is_imputed` flags False. Check the
quality JSON for the current build's counts, sources, and checksums rather than
assuming every refreshed download is identical.

## Work boundaries

Emerson can now explore hourly/weekly/seasonal patterns and build lagged features.
Feature operations must group by `ba` so values from different regions are never
used as one another's history. Forecast issue time, local calendar conventions,
training/evaluation windows, and any future missing-value treatment still need
to be agreed by the team. The builder deliberately leaves those modeling decisions
open and preserves the full time grid.
