# Shared hourly electricity demand: data dictionary

## Dataset and observation

`data/processed/demand_hourly.parquet` contains one row per balancing authority
(region) and reported hour. The key is **(ba, ts_utc)**. Rows are sorted by region
code and UTC timestamp. The default build covers January 1, 2019 at 00:00 UTC
through December 31, 2025 at 23:00 UTC, inclusive: 61,368 rows per region and
245,472 rows across the four selected regions, including rows with missing values.

| Code | Balancing authority |
|---|---|
| PJM | PJM Interconnection, LLC |
| ERCO | Electric Reliability Council of Texas, Inc. (ERCOT) |
| CISO | California Independent System Operator |
| ISNE | ISO New England |

These are balancing-authority service areas, not state boundaries. The API code
for ERCOT is ERCO.

## Columns

| Column | Stored type | Unit | Meaning | Missing allowed? |
|---|---|---|---|---|
| `ts_utc` | Timezone-aware datetime, UTC | Hour-ending timestamp | End of the reported hourly interval, normalized to UTC | No |
| `ba` | String | Region code | One of the selected balancing authorities | No |
| `demand_mwh` | Float64 | Megawatt-hours (MWh) | EIA-reported grid demand, from source measurement type D | Yes |
| `forecast_mwh` | Float64 | Megawatt-hours (MWh) | The operator's published day-ahead demand forecast for the same hour, source type DF | Yes |
| `is_imputed` | Boolean | None | Whether this project filled any measurement in the row | No; currently always False |

The input CSV names `timestamp_utc` and `respondent` become `ts_utc` and `ba`.
Demand and forecast values are preserved without rescaling. Units follow the
downloaded API `value-units` field, which is `megawatthours` for these records.

EIA uses an hour-ending convention. For example, a label of 01:00 UTC refers to
the hour ending at 01:00. Calendar features should use a deliberately chosen
regional local timezone and retain this interval convention; UTC hour alone is
not local clock hour in every region.

## Missing values and cleaning policy

- Blank measurements in the source CSV become null/NaN in Parquet. They are not
  converted to zero. A reported zero remains zero.
- No values are interpolated, forward-filled, replaced, or dropped by the builder.
  Consequently, `is_imputed` is False even on a row containing missing values.
  This flag records whether a replacement happened, not whether a value is missing.
- A completely absent demand or forecast series remains a nullable column.
- The builder requires the complete requested hourly grid in each source file.
  Missing observations must be represented by blank measurements, as the collector
  does. Duplicate hours, absent rows, unexpected regions, timezone-less timestamps,
  nonnumeric measurement tokens, and infinite values are rejected.
- No smoothing, outlier removal, feature engineering, or train/test split is
  performed here. Validation confirms table integrity, not scientific/model quality.

The downloaded 2019–2025 snapshot has the following missing measurements:

| Region | Missing demand hours | Missing forecast hours |
|---|---:|---:|
| PJM | 117 | 215 |
| ERCO | 1 | 48 |
| CISO | 24 | 97 |
| ISNE | 5 | 0 |
| **Total** | **147** | **360** |

These counts include source rows with unusable/null values as well as absent
source records. They describe this downloaded snapshot and may change after an EIA
refresh. No cause for the gaps has been established. For model evaluation, missing
actual demand cannot serve as an observed target. Operator-forecast comparisons
should use the same available hours for every compared method.

## Related output files

- `demand_hourly_missing_hours.csv`: `ts_utc`, `ba`, and `measurement` identify each
  missing measurement. There are 507 entries in this snapshot; an hour missing both
  measurements creates two entries. This log does not infer why a value is missing.
- `demand_hourly_quality.json`: requested window, row counts, per-region missing
  counts, dtypes, source-file SHA-256 checksums, and output-file checksums. Use this
  to identify the exact inputs used for a build. Source files are hashed as read.
- Each output is replaced atomically after all serializations succeed. Publication
  across the three files is not a single filesystem transaction. The quality JSON
  contains hashes that can detect a mismatched dataset/log pair after an interruption.

## Source and limits

Source: [EIA-930 data documentation](https://www.eia.gov/electricity/930-content/about.html),
via EIA Open Data v2 `electricity/rto/region-data/data/`, hourly frequency, types D/DF.
EIA derives demand from metered net generation and interchange; it is reported grid
load, not appliance-level consumption. The forecast column is an operator-produced
forecast rather than a measured target. This table does not establish what caused
demand growth or provide a model-performance result.

See [DATASET_HANDOFF.md](DATASET_HANDOFF.md) for reproducible build and read commands.
