# Analysis API contract 2.1.0

OpenAPI is served at `/api/docs`. CLI and HTTP use `AnalyzeService`; both serialize the same Pydantic response. The public contract changes together with the frontend in 0.2.1rc1.

## Input

`POST /api/v1/analyze` accepts JSON `file_content`, `file_path` (default test filename), `log_content` and `use_ml_classifier` (false by default). File/ZIP endpoints are `/api/v1/analyze/file` and `/api/v1/analyze/directory`, multipart field `file`, optional `use_ml` query parameter. Static analysis never executes submitted Python. Include ancestor `conftest.py` to resolve supplied fixtures.

## Output identity

`analysis_id` identifies a result; `request_fingerprint` is a SHA-256 digest of canonical sorted source inputs, log and ML mode. `source_snapshots` contains `{file_path, sha256, content}` for every supplied source. This deliberately returns source code; apply API access policy to exports and logs. Auth tokens are never part of the snapshot.

`schema_version=2.1.0`, `feature_schema_version=2.1.0`; `model_version` may be null. `status` is `ok`, `partial` or `error`; `degraded_reason` and structured `diagnostics` describe incomplete operation. Diagnostics preserve `code`, `message`, `file_path`, optional `line` and level.

## Measurement units

| Field | Meaning |
|---|---|
| `files_selected` | Target files selected, excluding context-only conftest files |
| `files_parsed` / `files_rejected` | Successfully parsed / rejected selected targets |
| `context_files_selected` | Context-only files supplied for fixture resolution |
| `test_candidates` | Static test definitions following the supported default-naming approximation |
| `collected_tests` | Null until actual collection evidence is integrated |
| `discovery_mode` | `static_default_pytest` |
| `unique_risk_locations` | Distinct static source locations and rule identities counted as risk; log evidence is counted separately as links |
| `tests_with_risk` | Candidate tests with attributable static/log risk evidence |
| `evidence_links` | Pattern and anomaly links across all result groups |
| `diagnostic_groups` | Module/helper/unattributed-log result groups, not tests |
| `total_files_analyzed` | Compatibility alias for successfully parsed target files |
| `total_patterns_found` | Compatibility alias for evidence links, not unique defects |

The sum of parsed and rejected files equals selected targets. One risky shared fixture affecting two tests contributes one unique source location, two affected tests and two evidence links.

## Results

`result_kind` is `test_candidate`, `module`, `helper` or `unattributed_log`. Each result has patterns, logs, fixtures, diagnostics and recommendations as arrays. Verdict is `risk_detected`, `no_known_risk` or `inconclusive`. `risk_score` is a heuristic index; `model_score` is an optional uncalibrated classifier score; `calibrated_probability` remains null unless a separately validated calibration is actually available.

Foreign logs are not attached to a lone test. Full nodeids must match file and test/class identity. Raw log entries retain their nodeid. Parameter suffixes map to the static definition only for display; the execution ledger retains exact identities.

## Failure behavior

Structured analysis errors may be returned under HTTP 422 `detail` with this schema. Request-validation errors are not analysis responses. Missing optional components report degradation or 503; repository stats remain explicit 501. The frontend validates nested data before rendering and has an error boundary; neither is a guarantee against every possible browser failure.

Runtime validators reject unsupported schema, missing arrays, malformed source/locations, nonnumeric or nonfinite scores and inconsistent counters. Tests use real backend payload fixtures plus negative mutations. The React render gate is mandatory in CI when npm dependencies are installed.
