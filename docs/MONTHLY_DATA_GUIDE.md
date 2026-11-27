# Monthly study data and evaluation guide

## Reproduce the study

Activate `data400-eia` and install `requirements.txt`, then run from the repository root.

```bash
python scripts/pull_monthly_sources.py
python scripts/build_monthly_study.py
python scripts/run_price_baselines.py
python -m unittest discover -s tests -v
```

The source collector needs internet access on the first run. Subsequent runs use
`data/raw/monthly_sources/manifest.json` and verify every referenced checksum.
The study build, baseline export, and evaluation run offline. Generated files stay
under Git-ignored `data/raw/` and `data/processed/`. Source downloads require no key.

Each source snapshot is stored by its SHA-256 content hash. The manifest records
the source request, original filename, snapshot path, checksum, and retrieval time.
The first run can import the nine existing `data/raw/eia861m/` workbooks. Their
retrieval timestamps are unknown and their provenance records that limitation.
`python scripts/pull_monthly_sources.py --refresh` downloads all 15 sources again
and publishes the new manifest only after every download succeeds. Earlier
snapshot bytes remain available if a refresh fails. Capture a manifest together
with its referenced source files when preserving an experiment.

## Study files and field definitions

The study calendar is January 2017–December 2025. The primary key is
`utility_id`, `state`, and `period`. Every outcome row uses EIA utility 19876 and VA.

| File under `data/processed/monthly/` | Contents |
| --- | --- |
| `study_monthly.csv` | 108 outcome months and contemporaneous controls for exploration and subsequent lag construction |
| `weather_station_monthly.csv` | 324 station-month summaries with valid-day counts and coverage checks |
| `pjm_large_load_context.csv` | Nine annual Dominion Energy historical July peaks, with source metric and mapping status |
| `quality.json` | Coverage counts, source metadata, protocol hash, and output checksums |

| Study field | Definition |
| --- | --- |
| `period` | Calendar month in `YYYY-MM` format |
| `utility_id`, `utility_name`, `state` | EIA reporting identity, restricted to 19876 and VA |
| `data_status`, `source_file` | EIA reporting status and original workbook name |
| `revenue_thousand_usd` | Residential revenue in thousands of nominal dollars |
| `sales_mwh` | Residential electricity sales in MWh |
| `customers` | Residential customer count reported for that month |
| `price_cents_per_kwh` | `100 * revenue_thousand_usd / sales_mwh` |
| `kwh_per_customer` | `1000 * sales_mwh / customers` |
| `weather_stations_valid` | Number of stations meeting the monthly coverage threshold |
| `weather_tmean_c` | Equal-weight average monthly mean temperature across the three qualifying stations |
| `weather_hdd_c_days`, `weather_cdd_c_days` | Equal-weight heating/cooling degree-day sums with base 18.33 degrees Celsius |
| `cpi_u`, `cpi_note` | National all-items CPI-U, without seasonal adjustment, and published footnote text |
| `henry_hub_usd_mmbtu` | Monthly Henry Hub natural gas spot price in dollars per million Btu |
| `real_price_2017_cents_per_kwh` | Nominal price multiplied by mean 2017 CPI divided by that month's CPI |
| `electricity_available_date` | Assumed observation month-end plus three calendar months |
| `controls_available_date` | Assumed observation month-end plus one calendar month for the current control sources |

Use the contemporaneous controls for exploratory analysis. Construct forecast
inputs separately with the availability functions described below. The
inflation-adjusted price is a descriptive series. The primary forecast target is
nominal `price_cents_per_kwh`.

Annual average prices should be computed from annual sums of residential revenue
and sales using the same unit conversion. Customer counts represent monthly
stocks. Summing those counts does not produce an annual count of unique customers.

### Weather processing

The stations are Dulles `USW00093738`, Richmond `USW00013740`, and Norfolk
`USW00013737`. Raw JSON includes NOAA measurement, quality, and source flags.
Production processing requires an empty quality flag, finite temperatures within
the accepted -100 to 70 Celsius range, and maximum temperature at least minimum
temperature. Each daily mean uses both accepted measurements. Duplicate dates
or unexpected station IDs cause a validation failure.

Station-months require at least 95% of calendar days to have accepted temperature
pairs. Otherwise their temperature and degree-day summaries remain missing. Degree
days sum the accepted days without rescaling for missing days. A station-month
with 30 accepted days out of 31 therefore retains its 30-day sum and reports the
coverage count. The three-station proxy requires all three station-months to pass.
This proxy gives each station equal weight. The raw flags and station-level table
allow Emerson to inspect quality and compare station choices. [NOAA API documentation](https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation), [GHCN daily flags](https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt)

### Economic controls and geographic scope

CPI uses BLS `CUUR0000SA0`, retaining M01–M12 and excluding M13 annual averages.
The November 27 source capture reports October 2025 as unavailable due to the 2025
lapse in appropriations. Its value remains missing and the source footnote is in
`cpi_note`. Any modeling imputer must be fitted using eligible training rows at
each origin. [BLS API documentation](https://www.bls.gov/developers/api_signature_v2.htm)

Henry Hub is a national fuel-market control in dollars per million Btu. Its
relationship to Dominion's fuel costs must be assessed in the analysis. [EIA Henry Hub data](https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm)

The PJM parser selects `Historical July Peak` rows from `DOM - Dominion Energy`
in the 2026 accuracy workbook. The table preserves `DOM Energy`, provider, metric,
units, report vintage, and an unverified utility-crosswalk status. It contains
annual historical large-load peak context. Its scope and annual frequency differ
from the residential utility-month outcome. Keep it in separate descriptive plots
until geographic definitions can be reconciled. It has no role in the initial
forecast inputs. [PJM source workbook](https://www.pjm.com/-/media/DotCom/planning/res-adeq/load-forecast/2026-accuracy-report.xlsx)

## Forecast timing and fixed evaluation calendar

`config/monthly_evaluation.json` records the protocol. Each forecast is issued at
month-end for the following month's nominal average electricity price.

The availability rules assume three calendar months after electricity month-end,
and one calendar month after weather, CPI, and gas month-end. Historical source
vintages and release dates have not been reconstructed. This experiment is a
lagged final-vintage backtest. The rules control the periods entering a forecast
under the declared delay assumptions. Source revisions remain a limitation.

| Calendar | Use |
| --- | --- |
| 2017 | Source history and lag warmup |
| 2018–2020 | Initial model development and release-eligible fitting labels |
| 2021 | Twelve sequential validation targets for feature/model selection |
| January–September 2022 | Release wait and fixed-procedure refitting |
| October 2022–September 2023 | Twelve calibration targets for empirical error bands |
| October–December 2023 | Calibration release wait |
| 2024–2025 | Twenty-four final test targets after the model procedure is fixed |

The last validation label becomes eligible March 31, 2022. The last calibration
label becomes eligible December 31, 2023. Keep model selection within validation.
Re-estimate model parameters monthly using newly eligible labels after choosing
features, preprocessing, hyperparameters, refit schedule, and interval method.

For a January 2024 forecast issued December 31, 2023, the most recent electricity
observation is September 2023. The most recent controls are November 2023 under
the one-month assumption. At the first validation origin, December 31, 2020, only
33 fitting labels from January 2018–September 2020 are eligible.

Emerson can import these functions after adding `scripts/` to the Python path.

```python
from monthly_forecasting import load_protocol, training_rows, require_available

protocol = load_protocol()
eligible = training_rows(data, "2023-12-31", protocol)
require_available(["2023-09"], "2023-12-31", "electricity", protocol)
# Calling require_available with October 2023 raises a validation error.
```

`available_rows(data, origin, family, protocol)` selects source rows for a family.
`require_available(periods, origin, family, protocol)` checks every constituent
month used in a feature. The family is `electricity`, `weather`, `cpi`, or `gas`.
Apply the rule at each historical training row's own forecast origin when building
the training feature matrix. Fit scalers and imputers only within that origin's
eligible training set. The evaluator audits declared export metadata. Reviewing
the feature/model code is also necessary to verify what the model actually used.

## Baseline forecasts and saved prediction format

`last_released` repeats the most recently available price. `seasonal_naive` uses
the target month one year earlier. The default CLI exports validation and
calibration predictions, an origin audit, the protocol, empirical calibration
radii, and a run manifest. The printed run ID hashes the input table, protocol,
forecast implementation, and requested partitions. Existing artifacts with
different bytes under the same run ID cause an error.

The calibration radius for each model is the finite-sample nominal 90% order
statistic from its 12 absolute calibration errors. For 12 observations, this is
the largest error. Test bounds are forecast plus/minus that fixed radius. Retain
negative bounds and flag them in the scores. Interpret the result as an empirical
error band because dependence and later rate changes can affect coverage.

Each forecast export has these columns. Emerson's model supplies the same fields.

| Column | Required value |
| --- | --- |
| `utility_id`, `state` | 19876 and VA |
| `origin`, `target_month` | Previous month-end in `YYYY-MM-DD` and target in `YYYY-MM` |
| `horizon_months` | 1 |
| `model_id` | A stable name such as `ridge` |
| `actual_price_cents_kwh` | Source nominal price, reconciled by the evaluator |
| `predicted_price_cents_kwh` | Saved point forecast in cents/kWh |
| `lower_bound`, `upper_bound` | Both empty, or finite bounds for every scored month |
| `training_label_cutoff` | Latest fitting label used, in `YYYY-MM`; fixed baselines record the latest eligible history month |
| `training_rows` | Number of fitting labels used; fixed baselines record the available fitting-history count |
| `run_id` | One nonempty run identifier per model in a comparison |
| `protocol_sha256` | `protocol_hash(load_protocol())` from `monthly_forecasting` |

The export must contain every target month for the chosen partition exactly once
per model. Duplicate keys, a future label cutoff, an incorrect origin, nonfinite
predictions, mixed populations, mismatched source truth, or a changed protocol
cause evaluation to fail. The source table and prediction-file hashes are saved
with each evaluation.

Substitute the baseline run directory printed by the CLI for `RUN_DIR`.

```bash
python scripts/evaluate_price_forecasts.py \
  --predictions RUN_DIR/baseline_validation.csv \
  --partition validation --output RUN_DIR/validation_metrics.json

python scripts/evaluate_price_forecasts.py \
  --predictions RUN_DIR/baseline_validation.csv PATH_TO_RIDGE_VALIDATION.csv \
  --partition validation --output data/processed/monthly/model_validation_metrics.json
```

Metrics include MAE, RMSE, signed bias, a 1,000-kWh expenditure-error conversion,
year and season breakdowns, and paired monthly absolute-error differences. Warm
months are May–September. Cool months are October–April. Interval scores include
the covered count, total count, fraction covered, and mean width when bounds are
provided for every scored month. All methods use the same scoring calendar.

After Emerson fixes the Ridge procedure and produces its calibration forecasts,
use `calibration_radii` on those saved forecasts, truth, and the frozen protocol
with `as_of="2023-12-31"`. It rejects an earlier date when labels remain unavailable.
Then generate the baseline test forecasts using the fixed baseline definitions.

```bash
python scripts/run_price_baselines.py --partitions test
```

Compare that run's `baseline_test.csv` with Emerson's 24 saved test forecasts using
`evaluate_price_forecasts.py --partition test`. Preserve the original run files
and configuration when interpreting any later exploratory changes.

## Current handoff and remaining work

Niloy has prepared the source cache, monthly panel, quality checks, timing rules,
two baselines, and independent evaluator. A 2021 validation run gave MAE 0.946756
cents/kWh for `last_released` and 0.522696 for `seasonal_naive`. These are validation
results from the captured sources. Final test performance awaits the fixed model.

Emerson can begin exploratory analysis using `study_monthly.csv` and the separate
PJM context file. The next input Niloy needs is Emerson's feature/model code and
12 validation forecasts in the documented format. Emerson should also provide
the selected feature list, Ridge settings, preprocessing, and refit procedure
chosen from validation. Review those before calibration and final testing. The
later comparison needs 12 calibration forecasts and 24 test forecasts from the
fixed procedure. Both team members still own interpretation and the final report,
presentation, and poster.

## Standalone price sample

The original price-only builder remains available for a small initial check.
Save the 2019 workbook with its original name in `data/raw/eia861m/`, then run
`python scripts/build_dominion_monthly_prices.py --start-year 2019 --end-year 2019`.
Running it without flags requires all nine original annual workbook names and
writes the complete price-only CSV. [2019 EIA workbook](https://www.eia.gov/electricity/data/eia861m/archive/xls/retail_sales_2019.xlsx)
