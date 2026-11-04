# Shared demand dataset

## Approved scope

Combine the four downloaded PJM, ERCO, CISO, and ISNE hourly CSVs for 2019–2025 into
one Parquet table. Rename timestamp_utc to ts_utc and respondent to ba, preserve
numeric values and nulls, and add is_imputed=False. Write a data dictionary and
partner handoff instructions. Keep the first collector PR unchanged.

## Design decisions

Use a separate offline script with configurable regions, UTC start/end hours, input
directory, and output directory. Default to the selected four regions and 2019–2025.
Validate every input against its region and complete expected hour grid before
writing any output. Reject duplicates, invalid numbers, infinite values, unexpected
regions, and incomplete or out-of-range grids. Do not interpolate, fill, or drop rows.

Outputs are demand_hourly.parquet, a detailed missing-measurement CSV, and a quality
JSON with per-region counts, source checksums, and output checksums. Write to a
temporary staging directory, then atomically replace each individual output. This
is not a multi-file filesystem transaction. Add pyarrow to the dedicated project
environment and requirements. Generated data remains ignored by Git.

The new niloy/eia-shared-dataset branch starts from the collector commit. Work stays
in the existing checkout so the already downloaded local files remain available;
the first PR's branch and commit remain unchanged.

## Validation

Test stacking, schema and UTC types, zero versus null, preservation of missing
values, Parquet round trips, incorrect region/grid/value rejection, and preservation
of prior outputs after input or serialization failures. Build the full downloaded
dataset and independently reconcile all rows and missing counts with the source
files. Obtain an independent code review before marking implementation complete.
