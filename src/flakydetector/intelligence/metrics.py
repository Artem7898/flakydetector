"""Explicit populations, nullable unavailable metrics and exploratory change signals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from statistics import median
from typing import Any

from flakydetector.governance.lifecycle import LifecycleEvent
from flakydetector.governance.quarantine import QuarantineEntry
from flakydetector.runtime.models import Attempt, ExecutionEvent
from flakydetector.runtime.monitors import (
    MonitorEngine,
    attempts_from_events,
    comparable_groups,
    wilson,
)


def reliability_metrics(
    events: Sequence[ExecutionEvent],
    *,
    quarantine: Sequence[QuarantineEntry] = (),
    lifecycle: Sequence[LifecycleEvent] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    attempts = attempts_from_events(events)
    first: dict[str, Attempt] = {}
    last: dict[str, Attempt] = {}
    for a in attempts:
        if a.invocation_id not in first or a.attempt < first[a.invocation_id].attempt:
            first[a.invocation_id] = a
        if a.invocation_id not in last or a.attempt > last[a.invocation_id].attempt:
            last[a.invocation_id] = a
    terminal = [
        a for a in first.values() if a.complete and a.outcome in {"passed", "failed", "error"}
    ]
    final = [a for a in last.values() if a.complete and a.outcome in {"passed", "failed", "error"}]
    observations = MonitorEngine().evaluate(events)
    intermittent = {
        o.nodeid
        for o in observations
        if o.status == "detected" and o.monitor == "intermittent_same_commit"
    }
    by_node: dict[str, list[Attempt]] = defaultdict(list)
    for attempt in attempts:
        by_node[attempt.nodeid].append(attempt)
    comparable_nodes = {
        node
        for node, rows in by_node.items()
        if any(len({a.run_id for a in group}) >= 2 for group in comparable_groups(rows))
    }
    retry_invocations = 0
    for id_, a in first.items():
        b = last[id_]
        if a.outcome in {"failed", "error"} and b.outcome == "passed" and (a.attempt < b.attempt):
            from flakydetector.runtime.monitors import compatible

            retry_invocations += compatible(a.provenance, b.provenance) == "compatible"
    histories: dict[str, list[LifecycleEvent]] = defaultdict(list)
    for e in lifecycle:
        histories[e.finding_id].append(e)
    triage_times: list[float] = []
    fix_times: list[float] = []
    open_ages: list[float] = []
    reviews: list[LifecycleEvent] = []
    for group in histories.values():
        group.sort(key=lambda e: (e.at, e.event_id))
        opened = None
        triaged = False
        for event in group:
            if event.at > now:
                continue
            if event.kind in {"opened", "reopened"}:
                if opened is None:
                    opened = event.at
                    triaged = False
            elif event.kind == "triaged" and opened is not None and (not triaged):
                triage_times.append((event.at - opened).total_seconds())
                triaged = True
            elif event.kind == "fixed" and opened is not None:
                fix_times.append((event.at - opened).total_seconds())
                opened = None
        if opened is not None:
            open_ages.append(max(0.0, (now - opened).total_seconds()))
        review = next(
            (
                e
                for e in reversed(group)
                if e.kind.startswith("review_") and e.independent_review and (e.at <= now)
            ),
            None,
        )
        if review:
            reviews.append(review)
    tp = sum(e.kind == "review_true_positive" for e in reviews)
    fp = sum(e.kind == "review_false_positive" for e in reviews)
    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"invocations": 0, "failures": 0})
    for a in terminal:
        day = a.started_at.astimezone(UTC).date().isoformat()
        daily[day]["invocations"] += 1
        daily[day]["failures"] += a.outcome in {"failed", "error"}
    return {
        "schema_version": "1",
        "population": "First terminal attempts per invocation; retries and expected outcomes are reported separately.",
        "attempts": len(attempts),
        "runs": len({a.run_id for a in attempts}),
        "invocations": len(first),
        "terminal_invocations": len(terminal),
        "ignored_or_incomplete": len(first) - len(terminal),
        "first_attempt_failure_rate": sum(a.outcome in {"failed", "error"} for a in terminal)
        / len(terminal)
        if terminal
        else None,
        "final_failure_rate": sum(a.outcome in {"failed", "error"} for a in final) / len(final)
        if final
        else None,
        "pass_on_retry_count": retry_invocations if events else None,
        "intermittent_outcome_rate": len(intermittent) / len(comparable_nodes)
        if comparable_nodes
        else None,
        "comparable_test_count": len(comparable_nodes),
        "intermittent_test_count": len(intermittent),
        "quarantine_count": sum(e.active(now) for e in quarantine),
        "expired_quarantine_count": sum(
            e.revoked_at is None and now >= e.expires_at for e in quarantine
        ),
        "quarantine_oldest_age_seconds": max(
            (
                (now - (e.original_created_at or e.created_at)).total_seconds()
                for e in quarantine
                if e.active(now)
            ),
            default=None,
        ),
        "median_time_to_triage_seconds": median(triage_times) if triage_times else None,
        "median_time_to_fix_seconds": median(fix_times) if fix_times else None,
        "unresolved_count": len(open_ages),
        "oldest_unresolved_age_seconds": max(open_ages, default=None),
        "static_finding_precision": tp / (tp + fp) if tp + fp else None,
        "independently_reviewed_findings": tp + fp,
        "unknown_reviews": sum(e.kind == "review_unknown" for e in reviews),
        "daily": [
            {"date": day, **counts, "failure_rate": counts["failures"] / counts["invocations"]}
            for day, counts in sorted(daily.items())
        ],
        "limitations": [
            "No production SLO is inferred from synthetic tests.",
            "Repeated invocations within one run may be correlated.",
            "Missing timestamps/reviews produce null, not zero latency or perfect precision.",
        ],
    }


def change_points(events: Sequence[ExecutionEvent], *, minimum: int = 20) -> list[dict[str, Any]]:
    if minimum < 10:
        raise ValueError("At least 10 distinct recorded runs per side are required")
    by_node: dict[str, list[Attempt]] = defaultdict(list)
    for a in attempts_from_events(events):
        if a.attempt == 1:
            by_node[a.nodeid].append(a)
    signals: list[dict[str, Any]] = []
    for node, rows in by_node.items():
        for group in comparable_groups(rows):
            # Select at most one invocation per run; minimum means distinct run IDs.
            unique = {a.run_id: a for a in sorted(group, key=lambda a: a.started_at)}
            ordered = sorted(unique.values(), key=lambda a: a.started_at)
            if len(ordered) < 2 * minimum:
                continue
            before, after = (ordered[-2 * minimum : -minimum], ordered[-minimum:])
            b = sum(a.outcome != "passed" for a in before)
            a = sum(x.outcome != "passed" for x in after)
            if a / minimum - b / minimum >= 0.2 and wilson(a, minimum)[0] > wilson(b, minimum)[1]:
                signals.append(
                    {
                        "nodeid": node,
                        "status": "exploratory_change",
                        "before_rate": b / minimum,
                        "after_rate": a / minimum,
                        "window_end": after[-1].ended_at.isoformat(),
                        "runs_per_window": minimum,
                        "evidence_ids": [id_ for row in [*before, *after] for id_ in row.event_ids],
                        "limitation": "Fixed-window association, not causal attribution or a fully calibrated online detector.",
                    },
                )
    return signals
