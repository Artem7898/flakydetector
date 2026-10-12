# HTTP API 3.0.0

Use the running service's `/api/docs` or `/api/openapi.json` for the exact Pydantic schemas.
Frontend and backend must be upgraded together. Paths below are prefixed by `/api/v1`.
Every sensitive route is workspace-scoped; tokens carry capabilities. In local mode, loopback
operator access is convenient, but source return is still disabled unless explicitly enabled.

| Method/path | Capability | Contract |
|---|---|---|
| POST /analyze | analyze + findings:read | file_content, file_path, optional log_content/use_ml_classifier |
| POST /analyze/file | analyze + findings:read | bounded .py multipart file |
| POST /analyze/directory | analyze + findings:read | bounded .zip, processed in killable child |
| POST /export | export; source:read additionally for source | analysis, format=json/sarif, include_source, confirm_source |
| POST /events | events:write | up to 2,000 versioned events; ID conflicts return 409 |
| GET /events | events:read | repo, cursor, limit; next_cursor pagination |
| GET /monitors | events:read | repo; observations and attempts; at most 10,000-event replay |
| GET /stats/{repo} | events:read | explicit populations, nullable metrics and exploratory changes |
| POST /quarantine | quarantine:write | repo/nodeid/source_hash/owner/issue/reason/ttl_days |
| GET /quarantine | events:read | repo; exact scoped entries |
| POST /quarantine/{id}/renew | quarantine:write | expected_version, reason, ttl_days |
| POST /quarantine/{id}/revoke | quarantine:write | expected_version, reason |
| GET /quarantine/{id}/audit | events:read | versioned actor/entry audit |
| POST /lifecycle | lifecycle:write | finding lifecycle/review events; actor set by server |

`workspace=local` is the query default. HTTP history needs `--evidence-db` or `FLAKY_EVIDENCE_DB`;
without it, history endpoints return 503 instead of invented metrics. Ordinary ingest does not
accept arbitrary collector identities or external infrastructure corroboration.
`/features/importance` and `/search_similar` currently return 503 with a bounded explanation;
use offline model reports/adapters until isolated provider serving is implemented.

## Analysis response

The response preserves explicit file/candidate/evidence counts, diagnostics and request identity.
`findings` is the canonical versioned static IR. Each finding has rule ID/version, stable identity,
location including Unicode columns, test associations, facts, limitations and suggestions.
Snapshots and snippets are disabled by default. Digests identify original source without returning
it. With permitted redacted viewing, `source_access`, `source_expires_at` and `source_grant` describe
an expiring projection; a redacted content hash need not equal the original digest.

`risk_detected` is static evidence. Runtime observations come from separate events/monitors.
The UI never infers an observed flake from a high risk score. Matching static evidence by exact
source-file hash is a content association, not authenticated repo identity or causal attribution.

## Errors and exports

401 missing/invalid token; 403 missing scope or workspace; 410 expired source view;
413 input/replay limit; 422 invalid/incomplete input; 503 unavailable history/capacity;
504 hard analysis deadline. Pydantic errors do not echo submitted values. Structured analysis
errors use the same source policy as success. Sensitive responses use Cache-Control: no-store.

Export JSON returns `classification` and `analysis`. SARIF returns a source-free SARIF object.
Source-bearing export requires an unmodified server grant, source permission and confirmation;
changing payload/expiry or restarting the server invalidates the grant. No permanent source
repository, encryption-at-rest service or login administration panel is created by this API.
