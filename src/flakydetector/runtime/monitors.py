"""Replayable monitors. Correlation, observed intermittency and causation remain distinct."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import sqrt
from statistics import median
from typing import Literal, Protocol, cast

from flakydetector.pytest_flaky_trail.storage import TrailStorage
from flakydetector.reporting.findings import digest
from flakydetector.runtime.models import (
    Attempt,
    ExecutionEvent,
    MonitorObservation,
    Outcome,
    Provenance,
)

REQUIRED_COMPONENTS = {
    "python",
    "dependencies",
    "config",
    "collection",
    "external_state",
    "seed",
    "image",
}
MONITORS = (
    "pass_on_retry",
    "intermittent_same_commit",
    "failure_rate_window",
    "order_permutation",
    "worker_specific",
    "timeout_variance",
    "infra_blast_radius",
    "static_risk_only",
)


def compatible(a: Provenance, b: Provenance, *, axis: str = "none") -> str:
    if (
        not a.recorded_context_complete
        or not b.recorded_context_complete
        or a.dirty is not False
        or (b.dirty is not False)
        or (not a.revision)
        or (not b.revision)
        or any(not a.components.get(k) or not b.components.get(k) for k in REQUIRED_COMPONENTS)
    ):
        return "unknown"
    if a.source_hash != b.source_hash or a.revision != b.revision:
        return "incompatible"
    if (axis != "none") and (
        a.experiment_id != b.experiment_id
        or not a.experiment_id
        or a.treatment_axis != axis
        or (b.treatment_axis != axis)
    ):
        return "unknown"
    excluded: set[str] = (
        {"collection"} if axis == "order" else {"image"} if axis == "image" else set()
    )
    if any(
        (
            a.components.get(k) != b.components.get(k)
            for k in (set(a.components) | set(b.components)) - excluded
        ),
    ):
        return "incompatible"
    if axis == "none" and (
        a.environment_hash != b.environment_hash
        or a.treatment_axis != b.treatment_axis
        or a.treatment_value != b.treatment_value
    ):
        return "incompatible"
    return "compatible"


def comparison_details(
    a: Provenance, b: Provenance, *, axis: str = "none"
) -> tuple[str, tuple[str, ...]]:
    status = compatible(a, b, axis=axis)
    reasons: list[str] = []
    if status == "compatible":
        reasons.append(
            "Same source/revision and all required recorded components under comparison policy v1; external truth is not independently attested.",
        )
    else:
        if a.dirty is not False or b.dirty is not False:
            reasons.append("Clean source revision is not established.")
        if not a.revision or not b.revision:
            reasons.append("Revision is missing.")
        missing = sorted(
            k for k in REQUIRED_COMPONENTS if not a.components.get(k) or not b.components.get(k)
        )
        if missing:
            reasons.append("Missing controlled context: " + ", ".join(missing))
        if not a.recorded_context_complete or not b.recorded_context_complete:
            reasons.append("Recorder could not fully encode the selected context.")
        if status == "incompatible":
            reasons.append("Recorded source, revision, environment or selected treatment differs.")
        if axis != "none":
            reasons.append(
                "Controlled treatment comparison requires the same explicit experiment ID."
            )
    return (status, tuple(reasons))


def attempts_from_events(events: Sequence[ExecutionEvent]) -> tuple[Attempt, ...]:
    groups: dict[tuple[str, str, str, int], list[ExecutionEvent]] = defaultdict(list)
    seen: dict[tuple[str, str], ExecutionEvent] = {}
    for e in events:
        identity = (e.workspace, e.event_id)
        if identity in seen:
            if seen[identity] != e:
                raise ValueError("Conflicting duplicate event")
            continue
        seen[identity] = e
        if e.phase != "session":
            groups[e.workspace, e.repo, e.invocation_id, e.attempt].append(e)
    attempts: list[Attempt] = []
    for group in groups.values():
        group.sort(key=lambda e: (e.sequence, e.event_id))
        first = group[0]
        phases = {e.phase: e for e in group}
        # Duplicate phases or changed context inside an attempt are not silently merged.
        uniform = all(
            (
                e.provenance == first.provenance
                and e.nodeid == first.nodeid
                and (e.run_id == first.run_id)
                and (e.worker == first.worker)
                and (e.source_file_hash == first.source_file_hash)
                for e in group
            ),
        )
        reports = {p: (e.outcome, e.expected) for p, e in phases.items()}
        outcome = (
            TrailStorage.terminal_outcome(reports)
            if uniform and len(phases) == len(group)
            else "incomplete"
        )
        attempts.append(
            Attempt(
                repo=first.repo,
                workspace=first.workspace,
                run_id=first.run_id,
                invocation_id=first.invocation_id,
                nodeid=first.nodeid,
                worker=first.worker,
                attempt=first.attempt,
                started_at=min(e.started_at for e in group),
                ended_at=max(e.ended_at for e in group),
                duration=sum(e.duration for e in group),
                outcome=cast(Outcome, outcome),
                failure_kind=next(
                    (e.failure_kind for e in group if e.failure_kind != "unknown"), "unknown"
                ),
                provenance=first.provenance,
                event_ids=tuple(e.event_id for e in group),
                complete=outcome not in {"incomplete", "unknown"},
                source_file_hash=first.source_file_hash,
                comparison_status=comparison_details(first.provenance, first.provenance)[0],
                comparability_reasons=comparison_details(first.provenance, first.provenance)[1],
            ),
        )
    return tuple(
        sorted(attempts, key=lambda a: (a.started_at, a.run_id, a.invocation_id, a.attempt))
    )


def comparable_groups(attempts: Sequence[Attempt], *, axis: str = "none") -> list[list[Attempt]]:
    groups: list[list[Attempt]] = []
    for a in attempts:
        if (
            not a.complete
            or a.outcome not in {"passed", "failed", "error"}
            or compatible(a.provenance, a.provenance, axis=axis) != "compatible"
        ):
            continue
        for group in groups:
            if compatible(group[0].provenance, a.provenance, axis=axis) == "compatible":
                group.append(a)
                break
        else:
            groups.append([a])
    return groups


def wilson(failures: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = 1.96
    p = failures / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


class Monitor(Protocol):
    name: str

    def evaluate(self, events: Sequence[ExecutionEvent]) -> Sequence[MonitorObservation]: ...


class ComparisonPolicy:
    version = "1"

    def compare(
        self, left: Provenance, right: Provenance, *, axis: str = "none"
    ) -> tuple[str, tuple[str, ...]]:
        if axis not in {"none", "order", "image"}:
            raise ValueError("Unsupported comparison treatment")
        return comparison_details(left, right, axis=axis)


class _Emitter:
    def __init__(self, nodeid: str, observations: list[MonitorObservation]) -> None:
        self.nodeid = nodeid
        self.observations = observations

    def __call__(
        self,
        monitor: str,
        detected: bool | None,
        verdict: str,
        selected: Sequence[Attempt] = (),
        *,
        confidence: Literal["high", "medium", "low", "none"] = "medium",
        facts: tuple[str, ...] = (),
        metrics: dict[str, float | int | None] | None = None,
    ) -> None:
        evidence = tuple(sorted({id_ for a in selected for id_ in a.event_ids}))
        status = (
            "insufficient_evidence"
            if detected is None
            else "detected"
            if detected
            else "not_detected"
        )
        self.observations.append(
            MonitorObservation(
                observation_id=digest(
                    [monitor, "1", self.nodeid, status, evidence, facts, metrics]
                ),
                monitor=monitor,
                nodeid=self.nodeid,
                status=status,
                verdict=verdict
                if detected
                else "insufficient_evidence"
                if detected is None
                else "not_observed",
                confidence=confidence if detected else "none",
                evidence_ids=evidence,
                facts=facts,
                metrics=metrics or {},
            ),
        )


class MonitorEngine:
    def __init__(
        self,
        *,
        window_size: int = 20,
        minimum: int = 10,
        fail_ratio: float = 0.2,
        extensions: Sequence[Monitor] = (),
    ) -> None:
        if not 2 <= minimum <= window_size or not 0 <= fail_ratio <= 1:
            raise ValueError("Invalid monitor policy")
        self.extensions = tuple(extensions)
        if len({m.name for m in self.extensions}) != len(self.extensions) or any(
            m.name in MONITORS for m in self.extensions
        ):
            raise ValueError("Duplicate or reserved monitor name")
        self.window_size = window_size
        self.minimum = minimum
        self.fail_ratio = fail_ratio

    def evaluate(
        self, events: Sequence[ExecutionEvent], *, static_nodeids: Sequence[str] = ()
    ) -> tuple[MonitorObservation, ...]:
        attempts = attempts_from_events(events)
        by_node: dict[str, list[Attempt]] = defaultdict(list)
        scopes = {(e.workspace, e.repo) for e in events}
        if len(scopes) > 1:
            raise ValueError("One workspace/repository per evaluation")
        for a in attempts:
            by_node[a.nodeid].append(a)
        observations: list[MonitorObservation] = []
        for nodeid in sorted(set(by_node) | set(static_nodeids)):
            rows = by_node[nodeid]
            groups = comparable_groups(rows)
            emit = _Emitter(nodeid, observations)
            retry: list[Attempt] = []
            for group in groups:
                for a in group:
                    if a.outcome not in {"failed", "error"}:
                        continue
                    next_ = [
                        b
                        for b in group
                        if b.invocation_id == a.invocation_id
                        and b.attempt > a.attempt
                        and (b.outcome == "passed")
                        and (b.started_at >= a.started_at)
                    ]
                    if next_:
                        retry.extend([a, min(next_, key=lambda b: b.attempt)])
            emit(
                "pass_on_retry",
                True if retry else False if groups else None,
                "observed_flaky_behavior",
                retry,
                confidence="high",
                facts=(
                    "Retries are dependent attempts, not independent runs.",
                    "Compatibility is under explicitly recorded context only.",
                ),
            )
            intermittent: list[Attempt] = []
            for group in groups:
                passing = [a for a in group if a.outcome == "passed"]
                failing = [a for a in group if a.outcome in {"failed", "error"}]
                for a in passing:
                    for b in failing:
                        if a.run_id != b.run_id:
                            intermittent.extend([a, b])
                            break
                    if intermittent:
                        break
                if intermittent:
                    break
            emit(
                "intermittent_same_commit",
                True if intermittent else False if groups else None,
                "observed_flaky_behavior",
                intermittent,
                confidence="high",
            )
            # Windows count first attempts of invocations, not all retries.
            window_groups: list[list[Attempt]] = []
            for group in groups:
                first: dict[str, Attempt] = {}
                for a in group:
                    if a.invocation_id not in first or a.attempt < first[a.invocation_id].attempt:
                        first[a.invocation_id] = a
                ordered = sorted(first.values(), key=lambda a: a.started_at)[-self.window_size :]
                if len(ordered) >= self.minimum:
                    window_groups.append(ordered)
            window = max(window_groups, key=lambda g: g[-1].started_at) if window_groups else []
            failures = sum(a.outcome in {"failed", "error"} for a in window)
            emit(
                "failure_rate_window",
                failures / len(window) > self.fail_ratio if window else None,
                "elevated_failure_rate",
                window,
                facts=(
                    "Denominator: first terminal attempts per invocation; includes consistently failing tests.",
                ),
                metrics={
                    "failures": failures if window else None,
                    "invocations": len(window),
                    "ratio": failures / len(window) if window else None,
                },
            )
            # Explicit controlled experiments, not weakening the ordinary comparator.
            order_match: list[Attempt] = []
            for group in comparable_groups(rows, axis="order"):
                treatments: dict[str, list[Attempt]] = defaultdict(list)
                for a in group:
                    if a.attempt == 1:
                        treatments[a.provenance.treatment_value].append(a)
                for left, ls in treatments.items():
                    for right, rs in treatments.items():
                        if (
                            left != right
                            and left
                            and right
                            and (len({a.run_id for a in ls}) >= 3)
                            and (len({a.run_id for a in rs}) >= 3)
                            and all(a.outcome == "passed" for a in ls)
                            and all(a.outcome in {"failed", "error"} for a in rs)
                        ):
                            order_match = [*ls, *rs]
            emit(
                "order_permutation",
                True if order_match else None,
                "order_dependent",
                order_match,
                confidence="high",
                facts=(
                    "Controlled order treatments repeated across at least three runs per treatment.",
                ),
            )
            image_match: list[Attempt] = []
            for group in comparable_groups(rows, axis="image"):
                images: dict[str, list[Attempt]] = defaultdict(list)
                for a in group:
                    if a.attempt == 1:
                        images[a.provenance.components["image"]].append(a)
                for left, ls in images.items():
                    for right, rs in images.items():
                        if (
                            left == right
                            or min(len({a.run_id for a in ls}), len({a.run_id for a in rs})) < 10
                        ):
                            continue
                        lf = sum(a.outcome != "passed" for a in ls)
                        rf = sum(a.outcome != "passed" for a in rs)
                        if wilson(lf, len(ls))[0] > wilson(rf, len(rs))[1] + 0.05:
                            image_match = [*ls, *rs]
            emit(
                "worker_specific",
                True if image_match else None,
                "environment_specific_association",
                image_match,
                facts=(
                    "Same test and controlled image experiment; worker ID alone is not machine identity.",
                    "Exploratory interval comparison, not a causal diagnosis or multiple-testing-corrected study.",
                ),
            )
            timing: list[Attempt] = []
            for group in groups:
                timing_attempts = sorted(
                    [a for a in group if a.attempt == 1], key=lambda a: a.started_at
                )
                if len(timing_attempts) < 20:
                    continue
                earlier, later = (timing_attempts[-20:-10], timing_attempts[-10:])
                if sum(a.failure_kind == "timeout" for a in later) >= 3 and median(
                    a.duration for a in later
                ) > 2 * max(0.001, median(a.duration for a in earlier)):
                    timing = [*earlier, *later]
            emit(
                "timeout_variance",
                True if timing else None,
                "timing_pressure",
                timing,
                confidence="low",
                facts=(
                    "Timeout durations are censored observations, not completed execution times.",
                ),
            )
            if nodeid in static_nodeids:
                emit(
                    "static_risk_only",
                    not groups,
                    "risk_detected",
                    facts=("Static evidence is not proof of an observed flaky test.",),
                    confidence="low",
                )
        # Blast radius is a shared-run association unless independently corroborated.
        runs: dict[str, list[Attempt]] = defaultdict(list)
        for a in attempts:
            if a.complete and a.attempt == 1:
                runs[a.run_id].append(a)
        for run_id, rows in runs.items():
            failed = [a for a in rows if a.outcome in {"failed", "error"}]
            if len({a.nodeid for a in failed}) >= 5 and len(failed) / len(rows) >= 0.8:
                evidence = tuple(sorted({id_ for a in failed for id_ in a.event_ids}))
                signals = [
                    e
                    for e in events
                    if e.run_id == run_id
                    and e.phase == "session"
                    and (e.failure_kind == "infrastructure")
                    and e.corroboration_id
                    and (e.collector != "pytest")
                ]
                observations.append(
                    MonitorObservation(
                        observation_id=digest(["infra", run_id, evidence]),
                        monitor="infra_blast_radius",
                        nodeid="<session>",
                        status="detected",
                        verdict="infrastructure_incident"
                        if signals
                        else "suspected_infrastructure_incident",
                        confidence="high" if signals else "low",
                        evidence_ids=evidence + tuple(e.event_id for e in signals),
                        facts=(
                            "Many failures share a run; a shared fixture regression remains an alternative explanation.",
                        ),
                    ),
                )
        for extension in self.extensions:
            extra = tuple(extension.evaluate(events))
            if any(item.monitor != extension.name for item in extra):
                raise ValueError("Extension returned a different monitor identity")
            known_ids = {event.event_id for event in events}
            if any(not set(item.evidence_ids) <= known_ids for item in extra):
                raise ValueError("Extension references unavailable evidence")
            observations.extend(extra)
        return tuple(observations)
