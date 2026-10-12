# Migration to 0.2.2

Back up the SQLite ledger and configuration; test a separate copy first. Do not replace the only
working checkout. This application update starts from `a421a6ddc6f228efc59e463b45a567edec878c32`.

| Component | Component contract |
|---|---|
| Package | 0.2.2 |
| HTTP AnalysisResponse | 3.0.0; upgrade frontend with backend |
| Feature semantic schema | 3.0.0; 42 dimensions retained but meanings changed |
| Rule set / fingerprint | 3.0.0 / 1 |
| Legacy trail SQLite user_version | 3, retained |
| New event component / event schema | 1 / 1 |
| Event provenance | 4 |
| Baseline | 1, records rules/fingerprint versions and base revision |

Old model manifests are rejected, not silently adapted. No replacement model is trained.
Legacy trail and dataset export behavior remains versioned separately from the new event path.
Existing rows do not become provenance-4 evidence. Record new attempts rather than editing flags.
New raw events are written alongside legacy phase tables; backups/retention must cover both.

## Product numbering correction

The previous generated archive was mislabeled `0.3.0rc1`. The maintainer's product version
is **0.2.2**. This correction does not downgrade the API/feature schema (`3.0.0`), rule set,
legacy database schema or event provenance. Users of that generated archive need matching
frontend/backend files but no database migration for the numbering/upload fix itself.
The product version is reported consistently by package metadata, UI, health, OpenAPI and SARIF.

## Incompatible defaults

Source snapshots are off. Requesting them needs an enabled redacted source policy, permission
and explicit opt-in. Exports are source-free unless separately confirmed and authorized.
API 422 validation errors no longer echo submitted values. Readiness means core service readiness,
not a prevalidated optional ML artifact. Shared RAG search and model-importance HTTP endpoints
return 503 pending isolated serving; offline model/RAG tooling remains available.

Use `flakydetector-serve` rather than copying an old unauthenticated public Uvicorn command.
Compose requires a token of at least 32 characters and publishes host loopback. One workspace
per shared process deployment is enforced. Public multi-tenant hosting is not enabled here.

## Upgrade sequence

1. Install candidate in a separate directory and complete preflight/CI before replacing production.
2. Start with a new event database and explicit workspace/repo identities.
3. Configure credentials/source policy; test allowed and denied paths, including error responses.
4. Recreate a reviewed baseline from the trusted base using the new rule/fingerprint versions.
5. Record controlled runtime observations. New provenance flags describe conditions, not enforce them.
6. Verify source-free exports, monitors, quarantine expiry and actual UI behavior with your workload.
7. Publish/merge only through the protected branch after required gates pass.

Rollback must restore matching frontend/backend/model contracts together. Preserve audit/event
files before rollback; old versions need not understand newly added component tables or responses.
