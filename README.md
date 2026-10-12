# FlakyDetector     

**Documentation:** [FlakyDetector documentation on Read the Docs](https://flakydetector.readthedocs.io/en/latest/).

Python backend and developer tooling by **Artem Alimpiev**. Application version: **0.2.2**,
following the maintainer's release numbering. This working-tree update is not proof of a published
release, a certified multitenant service or an independently evaluated classifier.
The published `latest` documentation follows the merged default branch; an unmerged candidate
can differ from that website.

FlakyDetector keeps three things separate: **static risks**, **observed execution behavior**,
and **unverified explanations**. A network pattern is not proof of a network call at runtime;
pass-on-retry is not proof of its cause. `no_known_risk` does not mean stable.

## What is included

- Versioned static finding identities, source-free **SARIF 2.1.0**, trusted-baseline policy,
  job summaries and a reusable GitHub Action.
- An opt-in pytest phase recorder, append-only/idempotent events and replayable monitors.
- Exact-test quarantine with an owner, issue, approval, expiry, renewal and revocation audit.
- Separate Finding and Runtime evidence views; unavailable metrics stay unavailable.
- Scoped credentials, source-free API defaults, redacted expiring source views and explicit exports.
- Killable Linux analysis processes with CPU, address-space, wall-time and output limits.
- Selective mock/control-flow, HTTP client and resource-lifetime analysis; conservative impact hints.

[Capabilities and unfinished boundaries](docs/CAPABILITY_MATRIX.md) ·
[Migration](docs/MIGRATION_0.2.2.md) · [Security](SECURITY.md) ·
[SARIF and baseline](docs/SARIF_ACTION.md) · [Monitors](docs/MONITORS.md)

## Run locally

Use Linux, **Python 3.12 or 3.13** and **Node.js 22**. Other runtimes are not covered by the
candidate's complete process/runtime gate. Keep the supplied lockfiles.

```bash
uv sync --locked --extra api --extra dev --extra ml --extra github --extra docs
uv run --frozen flakydetector-serve --host 127.0.0.1 --port 8001 \
  --evidence-db "$HOME/.local/share/flakydetector/evidence-v4.db"
```

In another terminal:

```bash
cd dashboard_frontend
npm ci --ignore-scripts
npm run dev
```

Open `http://127.0.0.1:3000`; API reference is `http://127.0.0.1:8001/api/docs`.
The UI has a Static analysis and a Runtime evidence section, **not an account-management admin**.
No model, cloud service or runtime history is needed for static scanning.
A minimal server installation is `uv sync --locked --extra api`.

### Select files for analysis

Choose **File / ZIP** in the analysis panel, then select one `.py` file or `.zip` archive.
The picker shows all files; the application checks the extension and size after selection
(Python: 1 MB; ZIP: 10 MB). You can also drop a file or ZIP onto the upload area.
Unsupported files show an error and are not submitted. To analyze a directory or several
files, create a ZIP containing the test files and relevant `conftest.py` files first.

The separate **Import execution history** field accepts recorder `.jsonl` events only;
it does not analyze Python source. Both inputs avoid native extension filters, which can
hide entries in desktop file choosers. Canceling selection preserves the previous source;
**Clear file and return to code** restores the pasted-code draft.

After replacing frontend files, restart Vite (or rebuild the Docker image) and reload the
browser with `Ctrl+Shift+R`. The header, `/health` and OpenAPI product version should be `0.2.2`.

Full source views are disabled even locally. Enable best-effort-redacted views explicitly with
`--source-mode redacted`, then request a view in the UI. They expire after 300 seconds by default.
Files already downloaded cannot be revoked or erased by that expiry.

## Combined container

```bash
export FLAKY_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up --build
```

The container serves frontend and API at `http://127.0.0.1:8001`. Enter the token from your
local environment in the UI; do not commit or post it. Compose requires authentication,
publishes only on host loopback, drops capabilities and uses a read-only root filesystem.
The container's internal `0.0.0.0` listener is not a public host-port permission.
Use a TLS ingress and the shared profile before remote deployment.
**One workspace per shared instance** is enforced. Separate trust domains need separately
restricted deployments; the child process is not a filesystem/network sandbox.

## Static scan, SARIF and CI policy

```bash
uv run --frozen flakydetector . --isolated --format sarif \
  --output artifacts/flakydetector.sarif --fail-on high
```

Exit `0`: analysis completed and policy passed; `1`: risk policy violation;
`2`: operational failure, unsupported/incomplete analysis or invalid policy.
`--fail-on none` does not make incomplete analysis successful.
SARIF is always source-free. JSON and text remain supported.

Baseline acceptance is explicit. Create it from a reviewed base checkout, outside the PR's
control, using its exact commit SHA. Reuse the same project root and scan scope.

```bash
uv run --frozen flakydetector . --write-baseline /tmp/flaky-baseline.json \
  --revision "$(git rev-parse HEAD)" --accepted-by ArtemAlimpiev --fail-on none
# In the head checkout, replace BASE_SHA with that exact reviewed base commit.
uv run --frozen flakydetector . --baseline /tmp/flaky-baseline.json \
  --baseline-revision BASE_SHA --new-only --format sarif \
  --output artifacts/flakydetector.sarif
```

The GitHub Action can compute a baseline from trusted base Git objects instead. Do not use
PR-controlled analyzer code in a privileged `pull_request_target` job. Pin the consumer Action
to a reviewed immutable commit **after it has been published**; no `v0.2.2` tag is claimed here.
See [the complete workflow example](docs/SARIF_ACTION.md).

## Record runtime evidence

Run the recorder only against tests you have explicitly authorized to execute.
The web analyzer never executes uploaded tests or pytest collection.

```bash
uv run --frozen pytest tests --flaky-trail \
  --flaky-trail-db /tmp/flaky-events.db \
  --flaky-trail-repo owner/project --flaky-trail-workspace local \
  --flaky-trail-env controlled-services-v1 \
  --flaky-trail-image runner-image-v1 --flaky-trail-seed-id fixed-seeds-v1
uv run --frozen flakydetector-evidence --db /tmp/flaky-events.db \
  --workspace local --repo owner/project report --output /tmp/flaky-runtime.json
```

These identifiers **describe** your controlled setup. They do not freeze the clock, set a seed,
reset a database or attest to external service stability. Missing/dirty/incompatible provenance
cannot produce high-confidence comparable-run conclusions.

Upload source-free event metadata to the configured server, or export it and use the UI:

```bash
uv run --frozen flakydetector-evidence --db /tmp/flaky-events.db \
  --workspace local --repo owner/project upload --url http://127.0.0.1:8001
# Alternative offline export:
uv run --frozen flakydetector-evidence --db /tmp/flaky-events.db \
  --workspace local --repo owner/project export --output /tmp/flaky-events.jsonl
```

Remote upload requires HTTPS, a scoped token in `FLAKY_API_TOKEN` and `--allow-remote`.
Tracebacks are removed from upload/export; event identifiers can themselves be sensitive.
Avoid secrets in parametrized test IDs. In the UI select workspace `local` and the exact repo
`owner/project`. Runtime evidence is real only after you ingest actual recorded events.

## Quarantine, history and analysis limits

[Quarantine guide](docs/QUARANTINE.md) describes exact selectors and TTL. All tests still run;
quarantine changes a gate decision, not the recorded outcome. Static waivers and baselines are
not runtime quarantine. Renewal preserves the original debt age.

History defaults to at most 10,000 events per HTTP replay. Larger histories require paged
export and bounded offline processing; a scalable rollup service is not included.
Pruning is an explicit operation, not a silently installed scheduler:

```bash
uv run --frozen flakydetector-evidence --db /tmp/flaky-events.db \
  --workspace local --repo owner/project prune --retention-days 30
```

This prunes the new execution-event component, **not** every legacy phase table, backups,
lifecycle or quarantine audit table. Define those retention policies at deployment.

## Verify the candidate

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen pytest -q --cov=flakydetector
uv run --frozen python scripts/validate_sarif.py
(cd dashboard_frontend && REQUIRE_RENDER_TESTS=1 npm test && npm run build)
python scripts/build_release.py --output artifacts/flakydetector-0.2.2.zip
python scripts/check_release.py artifacts/flakydetector-0.2.2.zip
python scripts/verify_release.py artifacts/flakydetector-0.2.2.zip \
  --output artifacts/verification --python 3.12
```

The GitHub gate also requires real pytest/xdist/rerunfailures combinations. Missing plugins may
skip local integration cases, but cannot silently pass the mandatory matrix. The SARIF schema
check downloads the official OASIS schema and records its digest. A schema-valid file is not
proof that GitHub accepted an upload; actual Code Scanning ingestion is a separate acceptance test.

Verification belongs beside the exact archive. Historical reports, synthetic rule examples,
JSX transpilation and Node-only tests do not certify Docker, a browser, an installed wheel or
independent precision. No production ML model or calibrated probability was created in this release.

[Repository](https://github.com/Artem7898/flakydetector) · MIT License · Artem Alimpiev
