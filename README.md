# DATA 400 Capstone: Data Center Growth and Residential Electricity Costs

**Team Members:** Emerson Carmine and Niloy Saha  
**Course:** DATA 400 – Fall 2026  
**Institution:** Dickinson College

## Project Overview

How have residential electricity prices in Virginia changed alongside data-center growth,
and how accurately can we forecast monthly prices? The primary dataset follows Dominion's
Virginia residential customers from 2017 through 2025. The historical case study examines
price and usage trends alongside documented large-load growth. The forecast targets overall
residential prices. The project reserves 2024–2025 for the final forecast evaluation.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/EmersonCarm/data400-capstone-eia-demand-forecasting.git
cd data400-capstone-eia-demand-forecasting
```

### 2. Create a Conda environment

```bash
conda create -n data400-eia python=3.11 -y
conda activate data400-eia
```

For later sessions, activate the existing environment with `conda activate data400-eia`.

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Build the monthly study data

```bash
python scripts/pull_monthly_sources.py
python scripts/build_monthly_study.py
```

The collector downloads public EIA, NOAA, BLS, and PJM sources without an API key.
It reuses a complete, checksum-verified source manifest on subsequent runs.
Use `--refresh` to capture current source revisions. The offline builder writes
`data/processed/monthly/study_monthly.csv` with 108 Dominion Virginia residential
months, weather and economic controls, and assumed availability dates. Separate
files hold station weather coverage, annual PJM context, and quality checks.
Raw data and generated outputs are ignored by Git.

Emerson's initial exploration and model development use
`data/processed/monthly/study_development.csv`, containing the 60 months through
December 2021. Full-window outcome analysis follows the model-procedure freeze or
is performed by the independent evaluator.

The [monthly data and evaluation guide](docs/MONTHLY_DATA_GUIDE.md) explains units,
missing values, source provenance, and the model export Emerson will supply.
It includes the small, standalone 2019 price-builder example.

### 5. Run and score the fixed baselines

```bash
python scripts/run_price_baselines.py
```

This writes validation and calibration forecasts to a printed run directory
under `data/processed/monthly/baselines/`. Substitute that directory for `RUN_DIR`:

```bash
python scripts/evaluate_price_forecasts.py \
  --predictions RUN_DIR/baseline_validation.csv \
  --partition validation --output RUN_DIR/validation_metrics.json
```

The fixed protocol is in `config/monthly_evaluation.json`. Forecasts use the last
released electricity observation and the same month one year earlier. Availability
dates implement declared reporting-delay assumptions for a final-vintage backtest.
The default run covers 2021 validation and October 2022–September 2023 calibration.
The guide describes the later 2024–2025 comparison once the model procedure is fixed.

## Hourly grid-demand data

The earlier EIA-930 work covers PJM, ERCO (Texas), CISO (California), and ISNE (New England)
for 2019–2025. It provides grid-demand context for the capstone. The [hourly data dictionary](docs/DATA_DICTIONARY.md)
and [handoff guide](docs/DATASET_HANDOFF.md) explain the fields and download commands.

### Configure the EIA API key

Copy `.env.example` to `.env` in the project's root directory and set your EIA key:

```env
EIA_API_KEY=your_api_key_here
```

The `.env` file is excluded from Git using `.gitignore`.
You can also supply `EIA_API_KEY` through your environment. A key is required for
downloads and refreshes; an existing matching cache can be read without a key.

### Download the initial hourly sample

```bash
python scripts/pull_eia_sample.py
```

The script downloads the initial hourly demand sample, processes it, and generates a basic data-quality report.

To choose one balancing authority and an inclusive UTC hour range:

```bash
python scripts/pull_eia_sample.py --ba PJM --start 2025-09-01T00 --end 2025-09-02T23
```

Custom output filenames include the authority and exact date range. Running without
arguments preserves the original September 2025 PJM sample and its filenames.
Use `python scripts/pull_eia_sample.py --help` to see the options. The collector
automatically pages through requests larger than 5,000 records and prints progress.
It stops before saving files if a later page is empty or the reported total changes.

### Reuse or refresh an hourly download

Successful downloads create a validated JSON cache under `.cache/eia/`. Repeating
the same region and date range reads that cache, makes no API requests, and
regenerates the raw CSV, hourly CSV, and quality report. Cache entries are snapshots
and have no automatic expiry. Use `--refresh` when you want current EIA revisions:

```bash
python scripts/pull_eia_sample.py --ba PJM --start 2025-01-01T00 --end 2025-12-31T23 --refresh
```

The first run after this upgrade downloads once to create the cache; existing CSVs
alone do not count as a cache. A corrupt or mismatched cache requires `--refresh`.
Failed downloads leave the previous complete cache in place. Cache files store
only data rows and public request metadata, without the key or echoed request envelope.

Generated downloads and caches stay local and are ignored by Git. The original
September 2025 PJM sample remains committed. Missing measurements stay blank in
the CSV and are counted in the quality report; the collector does not impute them.

### Build the shared hourly dataset

After downloading the four regional CSVs for the same 2019–2025 window, run:

```bash
python scripts/build_shared_dataset.py
```

This offline step creates `data/processed/demand_hourly.parquet`, a detailed
missing-hour CSV, and a quality JSON with input/output checksums. It preserves
missing values and sets `is_imputed=False`. The verified snapshot has 245,472 rows.
See [DATASET_HANDOFF.md](docs/DATASET_HANDOFF.md) for the download loop and an example
of reading the Parquet file in pandas. Install the updated requirements first;
PyArrow is required for Parquet output.

## Run checks

Run the offline data pipeline checks:

```bash
python -m unittest discover -s tests -v
```

## Project Structure

```text
data400-capstone/
├── data/
│   ├── raw/             # Original downloaded data
│   └── processed/       # Cleaned and formatted data
├── scripts/             # Data collection and preparation scripts
├── docs/                # Data quality reports
├── tests/               # Offline pipeline tests
├── .cache/eia/          # Local download caches (not committed)
├── .env                 # Private API key (not committed)
├── .env.example         # Placeholder configuration
├── .gitignore
├── requirements.txt
├── ai_use_disclosure.md
└── README.md
```

## Planned Analysis

- Examine monthly prices and residential electricity use alongside documented large-load trends.
- Compare Ridge regression with the last published price and the price from the same month a year earlier.
- Evaluate forecasts in time order, accounting for reporting delays. Report MAE and RMSE on the reserved test months.

## Project Status

Niloy's monthly data pipeline, release rules, two baselines, and independent scoring
tools are implemented. The study has 108 months, 324 station-month weather summaries,
and nine years of separately labeled PJM context. The current BLS snapshot has a
missing October 2025 CPI value with its source footnote preserved.

Emerson's exploratory analysis, feature development, and model forecasts are the
next inputs for the model comparison. The final evaluation uses the fixed procedure
and identical test months. The earlier hourly pipeline remains available for
grid-demand context.

## References

- [EIA monthly utility sales and revenue data](https://www.eia.gov/electricity/data/eia861m/)
- [EIA Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/about)
- [Virginia JLARC study of data centers](https://jlarc.virginia.gov/landing-2024-data-centers-in-virginia.asp)
- Hong, T., & Fan, S. (2016). *Probabilistic electric load forecasting: A tutorial review.* International Journal of Forecasting.
