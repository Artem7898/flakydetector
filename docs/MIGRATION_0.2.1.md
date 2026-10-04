# Migration: 0.2.0 → 0.2.1rc1

This is an unpublished candidate. Keep an untouched copy of 0.2.0 and its data. Back up the SQLite ledger while no test writers are running (use SQLite backup for a live database rather than copying only the main file of a WAL database). Test the candidate on the backup first.

## Runtime/API

Upgrade backend and frontend together. API schema is 2.1.0: new nested snapshots, request fingerprint, result kinds and measurement-unit counters are required. The old UI is not a supported consumer. CLI JSON consumers must also adapt.

`total_files_analyzed` now means successfully parsed target files, excluding context-only conftest files. `total_patterns_found` remains evidence-link count, not unique defects. Prefer the explicit new fields. `collected_tests=null` is intentional: static analysis does not execute pytest collection.

`source_snapshots` contains uploaded source, not only snippets. Access controls and export handling must treat responses as source-code data. No arbitrary server-filesystem read endpoint is introduced.

## Ledger

Storage schema 3 adds `provenance_version` and per-run/per-worker execution contexts. Old rows keep provenance 0 and are exported as inconclusive with no training label. Existing raw attempts/phases remain available. Do not promote old provenance based on hashes that did not capture effective pytest settings.

Prefer a new ledger for controlled recording. Keep the environment identity stable only when external service/data/seed conditions are truly comparable. Effective-config capture is conservative; unknown values cannot silently create trustworthy labels. Path or option changes may split groups unnecessarily; false merging is considered worse than extra groups.

## Features and models

Feature count is still 42. Semantics changed with log attribution, discovery and mock handling, so feature schema/hash moved to 2.1.0. An old manifest must not be edited to pass validation. Re-extract reviewed datasets, re-split by repository and target clone, train, evaluate and calibrate separately.

Historical datasets without v3 provenance remain useful for investigation, not automatic training. A matching feature vector alone does not establish a source clone.

## Verification

Old logs are in `docs/history/0.2.0/`. Generate new evidence against a final ZIP using `scripts/verify_release.py`. Its output records the archive and manifest hashes and must not be confused with the old reports. Full verification needs networked registries, locked development dependencies, npm packages and Docker. Real retry and browser scenarios are additional explicitly recorded gates.
