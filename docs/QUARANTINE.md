# Quarantine is a policy exception, not a rewritten result

An entry binds workspace, repository, exact nodeid and source hash, owner, issue, reason,
approver, creation/expiry and version. Default TTL is seven days; each approval is bounded by
30 days. No automatic quarantine from a static finding, a model response or one red build.

The Runtime evidence screen can create, renew or revoke an entry when the current token has
`quarantine:write`. Reads require `events:read`. Renewal/revocation uses the expected version;
concurrent updates produce 409 rather than silently replacing another decision. The audit API
records the actor and version. Renewal preserves original creation time and total debt age.
The single approver is an authorized actor; a two-human approval workflow is not implemented.

For offline operation:

```bash
uv run --frozen flakydetector-evidence --db /tmp/flaky-events.db \
  --workspace local --repo owner/project quarantine \
  --nodeid 'tests/test_checkout.py::test_payment[usd]' \
  --source-hash ACTUAL_RECORDED_64_CHARACTER_SHA256 \
  --owner ArtemAlimpiev --issue https://github.com/owner/project/issues/123 \
  --reason 'Investigating controlled transient failures' \
  --approved-by reviewer --ttl-days 7
```

Placeholders are intentionally not executable valid identities. Choose an actual record in the
UI/report. Selectors are exact, not regex/glob patterns; unusually shaped nodeids can require
explicit support. Changes to source invalidate an old exact-source exception.

`flakydetector-evidence ... run --env-id ... --image ... --seed-id ... -- tests/` executes
**all** specified trusted tests. It retains all attempts and computes a gate after execution.
Active quarantine can change that gate, never raw outcomes. Retry success alone does not suppress
an earlier failure. Expired entries, incomplete recording or session errors cannot be hidden.
A separate quarantine CI lane is an operator workflow, not an automatically installed scheduler.

Static baseline, static waiver and runtime quarantine are distinct. Baseline is implemented;
a standalone expiring static-waiver approval service is not included. Quarantine and lifecycle
audit retention is separate from execution-event pruning and needs an operator policy.
