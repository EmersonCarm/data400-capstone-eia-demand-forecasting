# Historical EIA Collector Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish and prepare the configurable, paginated, cached EIA downloader for the first PR.

**Architecture:** Keep the current script. Add small cache read/write functions and
route either validated cached records or a complete API download into the existing
processing pipeline. Publish complete cache files through atomic replacement.

**Tech Stack:** Python 3.11, pandas, requests, python-dotenv, standard-library unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-eia-collector-design.md`

## Global Constraints

- One balancing authority and inclusive UTC hour range per run.
- Preserve the committed September 2025 PJM sample and its filenames.
- Cache metadata contains no credentials or echoed API request envelope.
- Keep generated downloads and caches local.
- Preserve existing missing measurements and report their counts.

## Review Focus

- A cache hit must work with HTTP disabled and no EIA key.
- Different regions or dates must never reuse one another's data.
- Truncated or mismatched cache metadata must not be accepted.
- A failed refresh must preserve the previous complete cache.
- Partial API responses must not publish a cache or derived output.

## Task 1: Complete caching and documentation

**Files:** Modify `scripts/pull_eia_sample.py`, `tests/test_pull_eia_sample.py`,
`README.md`, `.gitignore`; create `.env.example` and `ai_use_disclosure.md`.

**Interfaces:** Existing `--ba`, `--start`, and `--end`; new `--refresh` bypasses
cache reuse. Cache helpers consume a Path and a credential-free request identity;
the reader returns data records and the writer accepts complete validated records.

- [x] Add failing offline checks for reuse, refresh, isolation, corrupt caches,
  failed refresh preservation, and exclusion of credentials.
- [x] Implement validated cache loading and atomic cache replacement.
- [x] Update setup, output/cache behavior, local data exclusions, and disclosure.
- [x] Run the complete offline suite and one isolated live/cache check.
- [x] Obtain independent review and resolve material findings.
- [x] Verify the selected diff and prepare it for the first PR.

## Verification record

On November 3, 2026, all 13 offline tests passed. An isolated live PJM request for
September 1–2, 2025 returned 96 records and 48 complete hours; an offline cache hit
without credentials reproduced identical output checksums. Independent review
identified the inherited rejection of an entirely absent series. A regression test
failed for D-only and DF-only responses, then passed after both output columns
were explicitly retained. No other material findings remained.

Cache replacement is atomic; the three derived output files are regenerated
individually and are not a multi-file filesystem transaction.
