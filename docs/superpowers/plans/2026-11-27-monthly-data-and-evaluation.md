# Monthly data and evaluation implementation plan

> Use the executing-plans workflow for the four reviewable tasks below.

The goal is to finish Niloy's independent data, baseline, and evaluation work for
the residential electricity price study. The current proposal assigns Emerson
exploratory analysis, feature development, and modeling. Continue on the existing
`niloy/dominion-monthly-prices` branch, based on main at `f851a1a`.

The specification is the November 8 proposal in
`/Users/niloysaha/Downloads/Data Center Growth and Residential Electricity Costs - Project Proposal.pdf`
and the detailed local plan in `outputs/project-plan/`.

## Shared requirements

- Use utility 19876 and state VA together and the 2017–2025 monthly calendar.
- Preserve exact downloaded bytes, source URLs, checksums, and known retrieval dates.
- Keep source downloads, generated tables, predictions, and reports local and Git ignored.
- Use the detailed plan's three-month electricity release delay and one-month
  weather, CPI, and gas delays as explicit assumptions for a final-vintage backtest.
- January 2024 forecasts issued December 31, 2023 may use electricity through
  September 2023. Fitting labels obey the same release rule.
- Use 2021 validation and October 2022–September 2023 calibration. Reserve
  2024–2025 final evaluation until Emerson's procedure is fixed.
- Compare models on identical, complete months. Reject duplicate, incomplete,
  nonfinite, and misdated forecast exports instead of silently scoring subsets.

## Review focus

- Weather quality flags and missing dates must affect monthly coverage counts.
- Previously downloaded workbooks have an unknown retrieval time and must be labeled.
- Refreshed downloads must preserve the prior complete manifest and source snapshots on failure.
- Changed future price observations must leave earlier baseline forecasts unchanged.
- A prediction export must reconcile with source truth and declared forecast origins.

### Task 1: Commit the verified monthly price builder

Files include the existing new builder, its tests, requirements, README, and this plan.

- [x] Run the 21 existing checks and the real 2019 and 2017–2025 builds.
- [x] Verify that current main matches the branch base and inspect the staged diff.
- [x] Commit as `Build verified Dominion Virginia monthly prices`.

### Task 2: Collect and validate supporting monthly data

Create `scripts/pull_monthly_sources.py`, `scripts/build_monthly_study.py`,
and `tests/test_monthly_study.py`. Reuse the price builder's `read_year` validation.

The collector produces an atomic manifest referencing immutable source snapshots.
The offline study builder consumes it and produces the 108-month study table,
324 station-month summaries, annual PJM context, and a quality report with hashes.

- [x] Write and run failing coverage, NOAA-quality, CPI/gas parsing, and cache tests.
- [x] Implement the source collector and offline normalization.
- [x] Run the tests, collect real sources, rebuild offline, and verify output hashes.
- [x] Commit as `Collect reproducible weather and economic study data`.

### Task 3: Implement release-aware baselines and independent evaluation

Create `config/monthly_evaluation.json`, `scripts/monthly_forecasting.py`,
`scripts/run_price_baselines.py`, `scripts/evaluate_price_forecasts.py`,
and `tests/test_monthly_forecasting.py`.

The shared forecasting module exposes availability and fitting-label selection.
The baseline CLI exports validation and calibration forecasts by default. The
independent evaluator reads saved exports and source truth, checks matched months,
and reports MAE, RMSE, bias, year/season errors, and interval coverage where supplied.

- [x] Write and run failing origin-cutoff, future-mutation, and paired-scoring tests.
- [x] Implement the fixed protocol, two baselines, and prediction-export validation.
- [x] Run real validation and calibration, and verify January 2024's eligible history.
- [x] Commit as `Add release-aware price baselines and forecast evaluation`.

### Task 4: Document the teammate interface and review the branch

Update README and add `docs/MONTHLY_DATA_GUIDE.md` with source definitions,
commands, availability assumptions, exact forecast columns, and remaining owners.

- [x] Run the full checks, reproduce saved metrics from prediction exports, and review the whole branch.
- [x] Record the source-data limitations and the precise teammate input needed next.
- [x] Commit as `Document monthly data and model evaluation handoff`.

## Final review corrections

The independent branch review identified source-promotion validation, development-data
boundaries, individual forecast-file validation, missing-date rejection, and runtime
provenance gaps. Each correction has a regression check. Prepared prices also retain
the EIA ownership field required by the detailed data contract. The suite passes 39
tests. Real source snapshots, development/calendar boundaries, hashes, and saved
validation metrics were checked offline. Final Ridge evaluation awaits Emerson.
