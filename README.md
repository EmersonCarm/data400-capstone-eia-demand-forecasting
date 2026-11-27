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

### 4. Build the monthly residential price dataset

Download the annual workbooks under **Sales and revenue → Detailed data → Year** on the
[EIA-861M data page](https://www.eia.gov/electricity/data/eia861m/). Save them under
`data/raw/eia861m/` with their original names. EIA uses `retail_sales_YYYY.xlsx` for
2017–2020 and `sales_ult_cust_YYYY.xlsx` for 2021–2025.

To try the 12-month sample, start with the
[2019 workbook](https://www.eia.gov/electricity/data/eia861m/archive/xls/retail_sales_2019.xlsx):

```bash
python scripts/build_dominion_monthly_prices.py --start-year 2019 --end-year 2019
```

After downloading all nine workbooks, run the builder without flags for the full
108-month dataset:

```bash
python scripts/build_dominion_monthly_prices.py
```

The builder runs offline and writes `data/processed/dominion_va_residential_2017_2025.csv`
for the full range. Each row is one month of residential service for EIA utility
19876 in Virginia. The builder checks the source units and requires all months to
be present exactly once. It calculates average price in cents per kWh as `100 ×
revenue_thousand_usd / sales_mwh`, and kWh per customer as `1000 × sales_mwh / customers`.
Each row includes the source filename and EIA reporting status. The raw workbooks and
generated CSVs are ignored by Git.

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

The Dominion Virginia dataset has 108 monthly observations for 2017–2025. The next
step is to document the time split and build the two price baselines. The earlier
hourly Parquet snapshot covers four regions and includes a missing-measurement log.

## References

- [EIA monthly utility sales and revenue data](https://www.eia.gov/electricity/data/eia861m/)
- [EIA Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/about)
- [Virginia JLARC study of data centers](https://jlarc.virginia.gov/landing-2024-data-centers-in-virginia.asp)
- Hong, T., & Fan, S. (2016). *Probabilistic electric load forecasting: A tutorial review.* International Journal of Forecasting.
