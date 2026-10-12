# 0.2.2 capability and acceptance matrix

This file describes code in the candidate, not a statement that all external gates passed.
Consult the archive-bound verification delivered beside the source ZIP. Synthetic examples
cannot certify independent precision, calibrated confidence or production isolation.

| Backlog | Implemented scope | Boundary / remaining acceptance |
|---|---|---|
| 001 mock control-flow | Branch reachability/intersection, selected lifetime/undo and paired regressions | Not a complete Python CFG or interprocedural mock engine |
| 002 security profile | Local/shared validation, scoped tokens, source grants, workspace authorization | One workspace per shared instance; no user-account admin/OIDC service |
| 003 privacy | Source-free defaults, redaction hooks, safe errors, confirmed expiring source exports | Best-effort secrets; exported files cannot be remotely erased |
| 004 process/input | Killable resource-limited Linux child; bounded ZIP/path validation | Not a full FS/network sandbox; hardened container/ingress acceptance remains |
| 005 Finding IR | Stable IDs, 23 rule IDs, evidence/limitations, fixture associations | Arbitrary rename/refactor identity not guaranteed |
| 006 SARIF | Source-free 2.1.0 emitter and mandatory official-schema CI script | Official-schema download and actual GitHub ingestion must run |
| 007 baseline | Trusted revision/scope, new/worsened/existing/resolved/inconclusive policy | Static waiver governance and automated long-lived baseline review are separate |
| 008 consumer Action | Trusted analyzer isolation, trusted-base scan, summary/annotations/artifact/upload | Live consumer/fork/private-repository runs; no automatic PR-comment lifecycle |
| 009 events | Versioned raw events, idempotency/conflicts, provenance components and HTTP ingest | Operator context not independent attestation; no arbitrary telemetry source trust |
| 010 integrations | Serial subprocess tests and required real plugin CI matrix | xdist/retry matrix results must be produced in a full environment |
| 011 monitor core | Retry, same-commit intermittence, first-attempt failure-window | No causal inference or automatic definition of stable tests |
| 012 extended monitors | Controlled order/image, timing and suspected infra correlation | Exploratory statistics; verified external infra adapter not included |
| 013 quarantine | Exact selector, owner/TTL/approval, renew/revoke/audit, post-execution gate | No two-person workflow or automatically provisioned quarantine lane |
| 014 AST semantics | Selected HTTP clients/task handles/env/cwd/cache/DB/file/random/polling cases | Dynamic SDKs, general Faker/NumPy inference, alias/lifetime paths remain limited |
| 015 impact | Fixture reverse dependencies, changed tests, conservative full fallback | Never permission to silently skip the runtime regression suite |
| 016 UX | Static Finding and Runtime views, reasons, source rights, exact content matching | Browser E2E and accessibility review remain deployment gates |
| 017 metrics/SLO | Explicit populations/nulls, lifecycle medians/debt, UTC daily, bounded change hints | No streaming rollup/time-window query service; 10k-event HTTP replay ceiling |
| 018 corpus | Source/review/split validation and labeled synthetic regression examples | No independent reviewed production corpus, confidence intervals or new calibration |
| 019 triage | Claim-level evidence/quotes/counterevidence/abstention, explicit provider calls | Quote presence is not semantic entailment; live-provider evaluation not certified |

## Not done by shipping this code

No stable release, PyPI upload, remote deployment, GitHub Code Scanning ingestion, new repository
ruleset, historical-data relabeling, independent benchmark result or model training is performed.
Documentation and CHANGELOG identify candidate behavior; old 0.2.0 reports stay historical.
The existing CI gate is extended, not disabled. A release with failed/missing required gates
must not be merged by an administrator bypass.
