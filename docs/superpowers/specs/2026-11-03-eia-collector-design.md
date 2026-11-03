# Historical EIA collector

## Intent and scope

Complete the team's first downloader task: one balancing authority and an inclusive
UTC hour range per run, pagination, validated raw and hourly outputs, cache reuse,
and an explicit refresh. The existing September 2025 PJM sample remains reproducible.

## Approach

Use a separate JSON download cache under `.cache/eia/`, containing a format version,
the public request identity, the total record count, retrieval time, and data rows.
This keeps download completeness independent of derived CSV outputs. Reusing raw
CSV files was considered, but those files alone do not record a completed API query.
The cache excludes credentials and the API's echoed request envelope.

Cache reuse requires matching metadata and a complete row count, and works without
an API key. Invalid caches stop with instructions to refresh. A refresh downloads
and validates all pages before atomically replacing the previous cache. Missing
measurements remain missing and appear in the quality report.

## Boundaries

Keep a single collector script and use the existing dependencies. Keep generated
downloads and caches local; retain the committed sample in Git. Add offline tests,
setup instructions, and an accurate AI-use disclosure. Multi-region consolidation,
Parquet, imputation policy, modeling, and evaluation belong to subsequent tasks.

## Validation

Check pagination, cache hits without HTTP or credentials, refresh replacement,
failed refresh preservation, cache integrity, and query isolation. Run one small
live request in an isolated temporary project, then repeat it with HTTP disabled.
