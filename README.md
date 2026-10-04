# FlakyDetector 0.2.1rc1

**Audit-remediation release candidate for the supplied 0.2.0 audit, not a stable release.** Python backend by Artem Alimpiev.

FlakyDetector inspects Python test source, preserves attributable evidence and optionally records pytest attempts. A static pattern is **not** proof of intermittent failure. `no_known_risk` is not “stable”; `risk_score` is a heuristic index, not a probability. No evaluated production model or real-world accuracy claim is shipped.

This candidate changes data-integrity boundaries, release checks and the analysis workspace. See [the implementation status](docs/IMPLEMENTATION_STATUS.RU.md), [migration guide](docs/MIGRATION_0.2.1.md), [limitations](docs/LIMITATIONS.md) and [benchmark protocol](docs/BENCHMARK.md). Historical validation in `docs/history/0.2.0/` does not certify these bytes. Verification of a final ZIP is produced **beside** the ZIP and includes its SHA-256.

## Run the application

Python 3.12+ and Node.js 22. The supplied lock files are retained; dependencies must be available from your package registries.

```bash
uv sync --locked --extra api --extra dev --extra ml --extra github
uv run --frozen uvicorn flakydetector.dashboard.main:app --host 127.0.0.1 --port 8001
```

In another terminal:

```bash
cd dashboard_frontend
npm ci --ignore-scripts
npm run dev
```

Open `http://127.0.0.1:3000`. API docs: `http://127.0.0.1:8001/api/docs`.
For a minimal application without development or ML dependencies, use `uv sync --locked --extra api` instead. Static analysis needs no model or API token; optional integrations are unavailable unless explicitly configured.

For the combined application:

```bash
docker compose up --build
```

The combined container serves the UI and API at `http://127.0.0.1:8001`. The Docker scenario must still pass the artifact-bound smoke gate on a Docker-capable host. A Dockerfile is not a build result.

## Workspace

Paste code or choose a Python file / ZIP. Switching back clears the upload without discarding the code draft. Editing the source, file, mode or ML settings marks the old analysis as outdated. Requests use immutable snapshots and latest-request identifiers; stale replies cannot replace newer results.

The output distinguishes selected/parsed/rejected files, static test candidates, affected tests, unique risk locations and evidence links. An evidence card opens the exact captured source and highlights the finding. Exports **include source code**: review them before sharing. The token remains in memory and is not exported.

The optional search panel labels retrieved explanations as unverified hypotheses. Changing a query marks its old result as outdated. Run-history statistics remain unavailable rather than being replaced with fabricated zeroes.

## CLI and HTTP

```bash
uv run --frozen flakydetector tests/corpus --format json --fail-on none
uv run --frozen flakydetector /path/to/project/tests --format json --fail-on high
```

CLI accepts a file, directory or ZIP. Directory/ZIP selection includes `test_*.py`, `*_test.py` and ancestor `conftest.py`. Submitted Python is parsed, never imported/executed. Uploaded ZIP entries are read in memory.

Exit codes: `0` completed and passed the selected rule policy; `1` policy violation; `2` error, incomplete or degraded analysis. `--fail-on none` disables the risk gate, not errors.

HTTP endpoints share `AnalyzeService`:

- `POST /api/v1/analyze`: JSON `file_content`, optional `file_path`, `log_content`, `use_ml_classifier`.
- `POST /api/v1/analyze/file` and `/directory`: multipart `.py` or `.zip`; optional `use_ml` query parameter.
- `GET /health`, `/ready`, `/api/v1/features/importance`, `/api/v1/search_similar`.

`GET /api/v1/stats/{repository}` explicitly returns 501. Model/RAG endpoints report unavailability instead of inventing a result. See [API contract 2.1](docs/api_reference.md).

## Record comparable pytest observations

The plugin is opt-in. Prefer a new database for newly recorded v3 evidence:

```bash
uv run --frozen pytest tests --flaky-trail \
  --flaky-trail-db ./flaky_trails_v3.db \
  --flaky-trail-repo example/project \
  --flaky-trail-env local-services-v1-seed-42
```

Use a non-secret `--flaky-trail-env` identity for controlled external service/data/seed state. The recorder stores the effective pytest configuration fingerprint, collection order, worker identity and attempt phases. This is comparability under **recorded** context, not a proof that every external input is controlled.

Schema-2 databases migrate additively to schema 3. Existing rows retain `provenance_version=0`; they are preserved but cannot silently become trusted training labels. Re-record executions rather than editing old provenance flags.

```bash
uv run --frozen python scripts/extract_dataset.py \
  --db flaky_trails_v3.db --source-root . \
  --output /tmp/flaky-observations.jsonl --min-runs 5
```

The feature vector remains 42-dimensional but its semantic schema is **2.1.0**. Old model manifests are rejected. Training additionally requires reviewed labels, matching source and independent repository/target-clone splits. This candidate does not generate or substitute a synthetic production benchmark.

## Verify and package

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen pytest -q
(cd dashboard_frontend && REQUIRE_RENDER_TESTS=1 npm test && npm run build)
uv build
uv run --frozen python scripts/installed_wheel_smoke.py
python scripts/build_release.py --output artifacts/flakydetector-0.2.1rc1.zip
python scripts/check_release.py artifacts/flakydetector-0.2.1rc1.zip
python scripts/verify_release.py artifacts/flakydetector-0.2.1rc1.zip \
  --output artifacts/verification --python 3.12
```

The verifier extracts **the final ZIP**, runs real commands, records failures/blocks and verifies the shipped source files were not altered. `--without-docker` is explicitly a partial verification. Real React rendering is mandatory in the complete gate; a local Node-only run reports the rendering test as skipped when npm dependencies are unavailable.

To run the container gate alone:

```bash
python scripts/container_smoke.py artifacts/flakydetector-0.2.1rc1.zip \
  --report artifacts/container-smoke.json
```

The release manifest detects drift/corruption, not publisher authenticity. Use the accompanying checksum to identify the archive you tested. Review optional live-provider, retry-plugin and browser checks separately from the core gates.

[Repository](https://github.com/Artem7898/flakydetector) · MIT License · Artem Alimpiev

### Optional real-browser smoke

With the local application already running and Playwright/Chromium installed in a separate tooling environment:

```bash
python scripts/browser_smoke.py --url http://127.0.0.1:8001 --output artifacts/browser
```

Use port 3000 for the Vite dev server. This gate exercises real HTTP analysis, source navigation, stale results, settings changes, file/clear transitions and syntax-error rendering. It writes screenshots only when actually run; missing tooling is recorded as blocked. It is not included in the core locked Python dependencies and must not be described as passed merely because its script exists.
