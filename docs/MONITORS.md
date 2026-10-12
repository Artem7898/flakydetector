# Events and monitors

`ExecutionEvent -> ComparisonPolicy -> MonitorEngine -> MonitorObservation` is separate from
`StaticFinding` and `TriageProposal`. Monitors are replayable pure functions. Results carry
versions, event references, facts, limitations and `detected`, `not_detected` or
`insufficient_evidence`. Confidence describes a bounded observation, not a calibrated probability.

## Recorded identity

Events include workspace/repo, session/run/invocation/attempt/phase, full parameterized nodeid,
worker, timestamp, sequence, outcome, failure kind, source-file hash and structured provenance.
Three terminal phases are folded into a complete attempt; incomplete/expected outcomes remain
distinct. Idempotent replay does not increase counts. Reuse of an ID with different bytes is a
conflict. Collection errors and worker crashes must not be fabricated as ordinary assertion results.
Collection order is not worker execution order. A `gw0` name is not a durable machine identity.

Comparable provenance requires a known clean revision and components for Python, installed
packages, configuration, collection, external-state identity, seed identity and image. Missing
components result in `unknown`; differing components in `incompatible`. These are recorder/operator
attestations, not proof all hidden state is controlled. Retries are not independent sessions.

## Monitor decisions

| Monitor | Required evidence and behavior |
|---|---|
| pass_on_retry | Complete failed attempt followed by pass in one invocation under comparable context |
| intermittent_same_commit | Pass/fail in separate runs for the same nodeid/revision/comparable context |
| failure_rate_window | First-terminal-attempt failure rate and minimum exposure; all-fail is elevated failure rate, not an intermittent label |
| order_permutation | Explicit controlled order experiment, repeated outcomes per treatment; the order projection is not a global relaxation |
| worker_specific | Controlled image experiment, same-test exposure and descriptive Wilson separation; exploratory environment association |
| timeout_variance | Sufficient durations and timeout evidence; low-confidence timing pressure, not cause |
| infra_blast_radius | At least five tests and correlated failures; without trusted external corroboration only a suspected incident |
| static_risk_only | Static findings without comparable history; risk_detected, not observed flaky behavior |

Extended thresholds are deterministic implementation policies, not validated universal SLOs.
Their acceptance tests use constructed examples. Ordinary HTTP recorder keys cannot submit
external corroboration; confirmed infrastructure incidents need a separately trusted adapter.
A monitor extension is trusted Python code registered server-side, never an uploaded executable.

## Recorder execution

The actual pytest plugin writes events when `--flaky-trail` is set. Configuration IDs
`--flaky-trail-env`, `--flaky-trail-image`, `--flaky-trail-seed-id` must describe your setup.
They do not change external services or randomness. Use `--flaky-trail-experiment`,
`--flaky-trail-treatment-axis` and `--flaky-trail-treatment` only for deliberately controlled
experiments; see `pytest --help` for the exact currently installed flags.

The required CI matrix covers Python 3.12/3.13 and pytest 8.4.2/9.0.2 with xdist, rerunfailures
and pytest-asyncio. Version records are uploaded. Missing required plugins cause failure,
not an implicit green skip. Until this matrix actually runs, its YAML is not compatibility evidence.

## History, SLO and change signals

Metrics state their population: first attempt, final attempt, invocation or run. Quarantined
outcomes remain visible. Unknown denominators return null. Precision is independently reviewed
TP/(TP+FP), not the number of fixes. Lifecycle events provide triage/fix medians with unresolved age.
Daily counts use UTC. Fixed-window before/after changes are exploratory, not causal change points;
a scalable streaming detector or calibrated fleet-level alerting service is not included.

HTTP replay is bounded at 10,000 events. Larger data needs paged exports/bounded offline windows.
Operator-configured reliability policies can gate expired quarantine, first-attempt failure
rate, static policy/coverage and independently reviewed precision. Missing inputs result in exit 2.
