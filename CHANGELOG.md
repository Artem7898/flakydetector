# Changelog

Changes to FlakyDetector are recorded here. Entries describe implementation, not an
accuracy benchmark or a guarantee that every release gate has passed.

## [Unreleased]

### Documentation

- Build Sphinx documentation as a required check of the final source ZIP on both
  CI Python versions; keep the existing `CI gate` mandatory.
- Read the documentation version from `pyproject.toml` and add explicit MyST
  navigation for all current pages, including limitations and historical claims.
- Install hashed documentation requirements exported from `uv.lock` on Read the
  Docs, without installing or importing the application or ML integrations.
- Exclude archived raw verification logs and requirements from Markdown parsing;
  keep all archived evidence unchanged.
- Document `main` / `latest`, GitHub integration, PR previews and the unrelated
  retained `v1.0.0` tag. Hosted settings/build success are not claimed by this edit.

### Release status

- Prepare **0.2.1rc1**, an audit-remediation candidate based on the supplied 0.2.0
  source. A Git commit or pull request does not publish a stable package or a
  GitHub Release. No release date is assigned before publication.
- Keep historical 0.2.0 verification under `docs/history/0.2.0/`; it does not
  certify this candidate. Fresh evidence must identify the final archive SHA-256.

### Fixed

- **PR #6 CI follow-up:** remove loop-variable capture from the log matcher;
  normalize Python imports/formatting with the pinned Ruff version. Keep all
  lint, typing, test, packaging and container checks mandatory.
- Retry transient readiness connection resets under a monotonic deadline,
  check that the container is still running, and retain diagnostics until
  cleanup. Non-transient HTTP errors and readiness timeouts still fail.
- Print verifier subprocess output in the CI log as well as preserving the
  per-check evidence files; record the failing container-smoke stage.

- **F01 — mock binding:** distinguish imported origins from supported runtime
  lookup namespaces; add paired wrong/right patch regressions.
- **F02 — log attribution:** remove the single-test fallback. Unmatched logs stay
  in a diagnostic group instead of changing another test's result.
- **F03 — execution provenance:** include effective pytest configuration,
  overrides, plugin identities and collection order in the recorded context.
  Preserve legacy observations without silently trusting their comparability.
- **F04 — clone isolation:** normalize the selected test AST rather than the
  entire module when checking for clones across dataset splits.
- **F06/F12 — execution outcomes:** retain empty-reason XFAIL/XPASS distinctions
  and retry tracebacks after pytest report outcomes are rewritten.
- **F07/F08 — accounting:** separate static candidates, parsed/rejected/context
  files, unique risk locations, affected tests and evidence links.
- **F09/F10 — workspace contract:** bind results to request/source snapshots;
  mark stale results, reject stale responses, validate nested payloads, and open
  captured source at the finding location.
- **F05/F11 — delivery:** include the MIT license, build allowlisted source ZIPs,
  validate complete manifests and provide final-archive/wheel/container checks.

### Added

- Migration guidance for the revised API, feature semantics and observation
  ledger; explicit analysis limitations and a reviewed-corpus benchmark protocol.
- A stable **CI gate** check depending on packaging and both Python 3.12/3.13
  final-artifact verification jobs. Failed or skipped prerequisite jobs do not
  turn this check green.
- Correct FlakyDetector citation metadata in `CITATION.cff`, replacing metadata
  copied from Scientific API Gateway. No unrelated DOI or release date is reused.

### Changed

- Application version: **0.2.1rc1**. API schema: **2.1.0**. Feature semantic
  schema: **2.1.0**, still 42 features. SQLite ledger schema: **3**.
- Upgrade frontend and backend together. Back up an existing ledger before its
  additive migration; re-record observations for trusted v3 provenance. Reassess
  older model manifests instead of assuming dimension equality is compatibility.
- Align Read the Docs with Python 3.12+ and the `docs` dependency extra.
- Generate `RELEASE_MANIFEST.json` for source archives rather than maintaining a
  stale hand-edited copy in the Git working tree. Keep generated training output,
  local environments and release-verification output out of the source branch.

### Not claimed by this candidate

- No calibrated flakiness probability, new production model, independent
  real-world accuracy result, administrator UI or user/role management.
- Browser smoke, live-provider integrations and real retry-plugin compatibility
  are separate checks; the existence of their code is not evidence of a pass.
- The GitHub Release titled "Scientific API Gateway v1.0.1 ..." (tag `v1.0.0`)
  is unrelated to FlakyDetector. Removing that release is repository maintenance,
  not a FlakyDetector feature release; it must not delete the tag or rewrite Git
  history as a side effect.

[Unreleased]: https://github.com/Artem7898/flakydetector/compare/c87bc3e463e2afa5960841a862c173e8f0d7bcbb...main
