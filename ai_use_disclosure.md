# AI assistance disclosure

## Tool and purpose

OpenAI Codex assisted with repository inspection, interpreting the team's proposed
task split, and implementing the first historical EIA downloader task. The requests
covered configurable region/date inputs, pagination, caching with explicit refresh,
offline tests, and setup documentation. Codex also helped explain the changes.

## Verification recorded so far

- Niloy ran the collector against EIA for the original September 2025 PJM sample,
  a two-day subset, and the full 2025 PJM year, and shared the resulting reports.
- Automated checks exercise the script with controlled API responses and temporary
  output directories. Run them with `python -m unittest discover -s tests -v`.
- Some test fixtures relabel regions or shift timestamps from the public sample.
  These are software-test fixtures, not research observations or model results.
- The full-year downloaded files were inspected for counts, duplicates, and missing
  forecasts. No model performance or causal conclusions have been established.
- Codex ran an isolated two-day live download followed by a cache hit with HTTP
  disabled and no API key. The derived output checksums matched, and the saved
  cache contained neither the key nor its request field. An independent agent
  reviewed the downloader and identified a missing-series edge case that was fixed
  with a failing-then-passing regression test.

This disclosure does not claim that the team has completed its final human code,
source, or scientific-method review. The team remains responsible for that review
and for updating this record as subsequent work is performed.

## Shared dataset follow-up

After the team selected PJM, ERCO, CISO, and ISNE, Codex used the collector to obtain
2019–2025 records, checked source and processed values, and generated local coverage
summaries and missing-measurement logs. Codex then assisted with the offline shared
Parquet builder, behavioral tests, data dictionary, and partner handoff guide.
No missing values were filled. Definitions were checked against EIA documentation;
Parquet setup was checked against official pandas and Apache Arrow documentation.
All 18 offline tests passed, and the full Parquet data was reconciled against the
four source CSVs, including null positions and source/output checksums. An
independent agent review found no blocking issues in the shared-data changes.
