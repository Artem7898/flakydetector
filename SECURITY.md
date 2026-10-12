# FlakyDetector security boundary

This candidate is for trusted local use or one workspace per hardened shared deployment.
It is **not a certified hostile multitenant sandbox**. Report a suspected vulnerability
privately to `alimpievne@gmail.com`; do not post credentials or customer source in public issues.

## Secure defaults

- The supported launcher defaults to host loopback. Remote bind needs explicit opt-in plus auth.
- Shared-profile validation also exists in the application factory, not just the launcher.
- Local mode checks actual peer and Host; it does not trust forwarded client headers.
- Source snapshots, snippets and raw logs are omitted from normal responses/exports.
- No raw request/response-body access logging is installed. Sensitive responses use `no-store`.
- Shared raw-source persistence is not implemented. New HTTP events store no traceback.
- Every shared instance accepts grants for one workspace only. Scope checks happen server-side.

## Scoped credentials

`FLAKY_CREDENTIALS_FILE` points to an operator-owned JSON array:

```json
[
  {"subject":"ci-recorder","sha256":"REPLACE_WITH_SHA256_OF_A_RANDOM_TOKEN",
   "workspaces":["local"],"scopes":["events:write"]},
  {"subject":"reviewer","sha256":"REPLACE_WITH_ANOTHER_TOKEN_SHA256",
   "workspaces":["local"],"scopes":["analyze","findings:read","events:read","export"]}
]
```

The placeholder above is deliberately invalid. Use SHA-256 hex digests of high-entropy random
bearer tokens, not hashes of human passwords. Restrict the credential file to its service owner.
The full capability set is `analyze`, `findings:read`, `source:read`, `export`, `events:write`,
`events:read`, `quarantine:write`, `lifecycle:write`. This is scoped token access, not a login/user
administration service. Credential rotation needs a restart. `FLAKY_API_TOKEN` is the simpler
single operator grant for workspace `local`; do not give that broad credential to untrusted CI.

## Source views and export

Enable `FLAKY_SOURCE_MODE=redacted` or the matching launcher flag explicitly. A request also
needs `include_source=true` and `source:read`. A short-lived HMAC grant binds the projected
response to its principal, scope, content and expiry; tampering or restarting invalidates it.
Source export additionally requires `export` and explicit confirmation. Reanalyze to obtain a
new view; export cannot extend an old one. Normal JSON/SARIF exports contain no source.
Downloaded bytes, clipboard contents, browser extensions and proxies are outside revocation.
Metadata, nodeids, file paths and hashes may still disclose information; use non-secret IDs.

Redaction detects common assignment secrets, tokens, URL credentials and PEM private keys;
it is best-effort, not a proof of secrecy. Operator `Settings.redactors` hooks may add rules.
Hook failure withholds the result. Apply infrastructure logging restrictions separately.
No encrypted source-at-rest service is included because shared source persistence is disabled.
Do not quietly add disk snapshots without encryption/key-management/retention design.

## Input and worker limits

Default limits: 1 MB/file, 10 MB archive, 20 MB declared expansion, 500 non-directory members,
1,000 total ZIP entries, ratio 100, path depth 24 and length 512, 50,000 AST nodes.
Paths are relative/NFC-normalized; traversal, absolute paths, symlinks and duplicate normalized
members are rejected. ZIP contents are read in memory inside the analysis child, never extracted.
Nested archives are not recursively scanned. Non-test context beyond supported fixtures is not
implicitly executed or collected. Do not add `pytest --collect-only` to the HTTP path.

Linux children have CPU (20 s), address-space (1 GiB), wall-clock (30 s), output and file limits,
a minimal environment, private temporary cwd and a maximum concurrency of two. Cancellation
and deadline kill the child process group rather than merely cancelling a future. ML limits
may need explicit workload adjustment. The process still has the service user's filesystem
and network permissions: use restricted mounts, no secrets, no egress where appropriate,
read-only containers, non-root execution and independent deployments for trust domains.
Large requests are buffered within a limit; an ingress must also enforce rate/concurrency/body
and slow-upload time limits. Ordinary authentication does not prevent a malicious authorized
user consuming its allowance. End-to-end denial-of-service testing remains required.

## Retention

No automatic retention scheduler is installed. Run the evidence CLI prune command in your own
scheduled job. It deletes the new event component and its idempotency records, not legacy phase
trails, backups or governance audit tables. Define and test their policies separately. Local
recorders can retain redacted traces; protect those files and backups as sensitive data.
