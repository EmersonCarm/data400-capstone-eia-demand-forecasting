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
git clone <repository-url>
cd <repository-name>
```

### 2. Create a Conda environment

```bash
conda create -n data400 python=3.11 -y
conda activate data400
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the EIA API key

Create a `.env` file in the project's root directory:

```env
EIA_API_KEY=your_api_key_here
```

The `.env` file is excluded from Git using `.gitignore`.

### 5. Download the initial dataset

```bash
python scripts/pull_eia_sample.py
```

The script downloads the initial hourly demand sample, processes it, and generates a basic data-quality report.

## Project Structure

```text
data400-capstone/
├── data/
│   ├── raw/             # Original downloaded data
│   └── processed/       # Cleaned and formatted data
├── scripts/             # Data collection scripts
├── docs/                # Data quality reports
├── .env                 # Private API key (not committed)
├── .gitignore
├── requirements.txt
└── README.md
```

## Planned Analysis

- Explore daily, weekly, and seasonal electricity-demand patterns.
- Build simple historical forecasting baselines.
- Train Ridge Regression and LightGBM models.
- Compare predictions using MAE, RMSE, and MAPE.
- Analyze forecasting errors across different regions and seasons.

## Project Status

**Current Stage:** Initial data collection and project setup.

The first step is verifying access to the EIA dataset and collecting a working sample. Further data processing, exploratory analysis, modeling, and evaluation will follow.

## References

- [U.S. Energy Information Administration](https://www.eia.gov/opendata/)
- Hong, T., & Fan, S. (2016). *Probabilistic electric load forecasting: A tutorial review.* International Journal of Forecasting.
