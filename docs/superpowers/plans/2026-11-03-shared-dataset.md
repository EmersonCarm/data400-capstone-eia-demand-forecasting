# Shared Dataset Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver the documented shared Parquet dataset and a reproducible offline build.

**Architecture:** One script validates and stacks regional CSV snapshots, creates a
missing-measurement log and quality report, and stages output files before replacement.

**Tech Stack:** Python 3.11, pandas 2.x, pyarrow 26.x, unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-shared-dataset-design.md`

## Global Constraints

- Schema: ts_utc, ba, demand_mwh, forecast_mwh, is_imputed.
- Preserve all original measurements and nulls; no imputation or row dropping.
- Keep PR #1 and existing source downloads unchanged.
- Do not require network access or an EIA key to build from downloaded files.

## Review Focus

- Mismatched regions, dates, duplicate or missing hours must fail before publishing.
- Zero must remain a valid value and distinct from a missing value.
- Entirely missing series must remain nullable columns with explicit counts.
- Input/serialization failure must preserve existing outputs.
- Timestamp timezone and numeric/boolean types must survive Parquet round trips.

## Task 1: Build and document the shared dataset

Files: create `scripts/build_shared_dataset.py`, `tests/test_build_shared_dataset.py`,
`docs/DATA_DICTIONARY.md`, and `docs/DATASET_HANDOFF.md`; update requirements,
README, and AI-use disclosure.

Interface: build_dataset(input_dir, regions, start, end) returns a DataFrame, a
missing-measurement DataFrame, and a quality dict. write_outputs(data, missing,
quality, output_dir) writes the three artifacts. main() exposes the CLI.

- [x] Write behavioral tests and watch them fail for the missing builder.
- [x] Implement input validation, stacking, staged Parquet/log/report output.
- [x] Document definitions, missing-value policy, source revisions, and partner usage.
- [x] Run all tests and build/read back the real four-region dataset.
- [x] Obtain independent review and resolve material findings with regression tests.
- [x] Verify the selected diff and prepare the result for review.

## Verification record

All 18 offline tests passed. The real Parquet file contains 245,472 rows with the
five requested columns, UTC timestamps, 147 missing demand values, 360 missing
forecasts, and no imputed rows. Independent reconciliation matched every timestamp
and numeric value to the four original CSVs, verified all input/output hashes, and
confirmed 507 distinct entries in the missing-measurement log. The committed small
PJM sample also built successfully into a separate temporary output directory.

PyArrow 26.0.1 was installed in the dedicated data400-eia environment. Dependency
floors follow its documented pandas/NumPy compatibility; the existing environment
already satisfies them. The package integrity check passed.

Independent review found no blocking issues. An optional extension of the
serialization-failure test to later CSV/JSON write stages was deferred; the current
test covers Parquet write failure, and all stages precede publication in the code.
