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
