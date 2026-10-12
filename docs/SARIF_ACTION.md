# SARIF, trusted baselines and consumer GitHub Action

The CLI supports `--format sarif`; text and JSON remain. SARIF is always source-free and represents
the full scan, even when policy blocks only new/worsened findings. The report uses versioned
rules, safe repository-relative URIs, Unicode columns and stable FlakyDetector fingerprints.
It does not invent `security-severity` for reliability smells or forge GitHub's
`primaryLocationLineHash`. GitHub's upload action may add that line hash from the target checkout.
Schema validation is a required release check; actual Code Scanning ingestion is a separate gate.

Finding identity combines supported source structure, lexical owner and occurrence, not line
number, request hash or ML clone hash. Line-only shifts and common alias changes are tested;
arbitrary refactors/renames and semantic clone equivalence are not guaranteed identity-preserving.
One shared-fixture location can have several test associations. Inline statements keep columns.

## Baseline policy

Baseline schema binds base revision, scan scope, rule version and fingerprint version.
Use a reviewed base: the head PR cannot approve itself. New and worsened findings can fail CI;
existing debt stays visible. A disappearance is resolved only after complete comparable analysis.
Missing/corrupt/mismatched baseline or scanner failure is operational/inconclusive exit 2.
The consumer Action calculates the baseline from bounded trusted-base Git objects, not a
head-provided JSON file. No target dependency installation, pytest collection, hooks or filters
are invoked by the analyzer step.

## Consumer workflow example

Replace the all-caps placeholder with the full reviewed **published** FlakyDetector commit SHA.
This candidate is not yet a release tag or GitHub Marketplace publication.

```yaml
name: Static test reliability
on: [pull_request]
permissions:
  contents: read
  security-events: write
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: Artem7898/flakydetector@REPLACE_WITH_REVIEWED_40_CHARACTER_COMMIT_SHA
        with:
          path: .
          baseline-ref: ${{ github.event.pull_request.base.sha }}
          fail-on: high
          upload-sarif: 'true'
```

For source-free downloadable reports without Code Scanning capability, use `upload-sarif: 'false'`
and remove that write permission. Fork/organization policies may prevent upload. Do not work around
this by running untrusted head code using `pull_request_target` and privileged credentials.
The consumer Action rejects that event. Pin action dependencies to reviewed immutable SHAs in
high-assurance deployments. The included workflow uses upstream release tags and is not a claim
of a fully pinned software supply chain.

The adapter emits a job summary, bounded command annotations and a SARIF artifact before the final
policy gate. Exit 1 still preserves the report; exit 2 remains a failure. Code Scanning should be
uploaded once per analyzer/category, not twice from the Python verification matrix. Actual PR
annotations depend on changed-line locations and GitHub support/capability.

The old Markdown PR-comment adapter remains an explicitly invoked helper; this candidate does
not auto-post duplicate comments or provide an idempotent comment-maintenance service. Live GitHub
upload, fork restrictions and private-repository capability are deployment acceptance checks.

Official contracts: [SARIF support](https://docs.github.com/en/code-security/reference/code-scanning/sarif-files/sarif-support),
[upload workflow](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/integrate-with-existing-tools/upload-sarif-file),
[OASIS schema](https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json).
