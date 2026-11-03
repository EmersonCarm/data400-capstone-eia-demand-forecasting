# DATA 400 Capstone: Electricity Demand Forecasting

**Team Members:** Emerson Carmine and Niloy Saha  
**Course:** DATA 400 – Fall 2026  
**Institution:** Dickinson College

## Project Overview

This project aims to predict hourly electricity demand using historical electricity consumption data. We will explore how past usage, seasonal patterns, and calendar-related factors can help forecast future electricity demand.

Our goal is to compare traditional forecasting methods with machine learning models and evaluate how accurately they predict electricity usage.

### Research Question

How accurately can historical electricity usage and calendar patterns predict future hourly electricity demand?

## Dataset

We use publicly available electricity data from the **U.S. Energy Information Administration (EIA)**.

- **Source:** [EIA Open Data API](https://www.eia.gov/opendata/)
- **Dataset:** EIA-930 Hourly Electric Grid Monitor
- **Initial Region:** PJM (Pennsylvania–New Jersey–Maryland Interconnection)
- **Initial Sample:** September 2025
- **Variables:** Hourly electricity demand, demand forecasts, and timestamps

We plan to expand the dataset to multiple balancing authorities and several years of historical data.

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

### 4. Configure the EIA API key

Copy `.env.example` to `.env` in the project's root directory and set your EIA key:

```env
EIA_API_KEY=your_api_key_here
```

The `.env` file is excluded from Git using `.gitignore`.
You can also supply `EIA_API_KEY` through your environment. A key is required for
downloads and refreshes; an existing matching cache can be read without a key.

### 5. Download the initial dataset

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

### 6. Reuse or refresh a download

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

### 7. Run checks

Run the offline collector checks without an API key or network access:

```bash
python -m unittest discover -s tests -v
```

## Project Structure

```text
data400-capstone/
├── data/
│   ├── raw/             # Original downloaded data
│   └── processed/       # Cleaned and formatted data
├── scripts/             # Data collection scripts
├── docs/                # Data quality reports
├── tests/               # Offline collector tests
├── .cache/eia/          # Local download caches (not committed)
├── .env                 # Private API key (not committed)
├── .env.example         # Placeholder configuration
├── .gitignore
├── requirements.txt
├── ai_use_disclosure.md
└── README.md
```

## Planned Analysis

- Explore daily, weekly, and seasonal electricity-demand patterns.
- Build simple historical forecasting baselines.
- Train Ridge Regression and LightGBM models.
- Compare predictions using MAE, RMSE, and MAPE.
- Analyze forecasting errors across different regions and seasons.

## Project Status

**Current Stage:** Configurable historical data collection.

The collector supports one balancing authority per run, inclusive UTC hour ranges,
pagination, cache reuse, explicit refreshes, and quality reports. A full-year PJM
2025 download was checked: all 8,760 actual-demand hours are present, with 25 missing
operator-forecast hours. Multi-region consolidation, the shared Parquet dataset,
exploratory analysis, modeling, and evaluation will follow.

## References

- [U.S. Energy Information Administration](https://www.eia.gov/opendata/)
- Hong, T., & Fan, S. (2016). *Probabilistic electric load forecasting: A tutorial review.* International Journal of Forecasting.
