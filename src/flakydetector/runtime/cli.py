"""Local evidence operations and explicit trusted pytest execution. API never calls run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from flakydetector.governance.quarantine import QuarantineEntry, QuarantineStore, applies
from flakydetector.intelligence.metrics import change_points, reliability_metrics
from flakydetector.runtime.models import ExecutionEvent
from flakydetector.runtime.monitors import MonitorEngine, attempts_from_events
from flakydetector.runtime.store import EvidenceStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--workspace", default="local")
    parser.add_argument("--repo", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("file", type=Path)
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path)
    report.add_argument("--policy", type=Path)
    export = sub.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    prune = sub.add_parser("prune")
    prune.add_argument("--retention-days", type=int, default=30)
    quarantine = sub.add_parser("quarantine")
    quarantine.add_argument("--nodeid", required=True)
    quarantine.add_argument("--source-hash", required=True)
    for key in ("owner", "issue", "reason", "approved-by"):
        quarantine.add_argument("--" + key, required=True)
    quarantine.add_argument("--ttl-days", type=int, default=7)
    run = sub.add_parser("run")
    run.add_argument("--env-id", required=True)
    run.add_argument("--image", required=True)
    run.add_argument("--seed-id", required=True)
    run.add_argument("pytest_args", nargs=argparse.REMAINDER)
    upload = sub.add_parser("upload")
    upload.add_argument("--url", required=True)
    upload.add_argument("--token-env", default="FLAKY_API_TOKEN")
    upload.add_argument("--allow-remote", action="store_true")
    upload.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        db = EvidenceStore(args.db.resolve())
        if args.command == "upload":
            from flakydetector.runtime.upload import upload_events

            result = upload_events(
                db,
                workspace=args.workspace,
                repo=args.repo,
                url=args.url,
                token=os.getenv(args.token_env, ""),
                allow_remote=args.allow_remote,
                batch_size=args.batch_size,
            )
            print(json.dumps(result))
            return 0
        if args.command == "ingest":
            if args.file.stat().st_size > 20000000:
                raise ValueError("Upload too large")
            events = [
                ExecutionEvent.model_validate_json(line)
                for line in args.file.read_text().splitlines()
                if line.strip()
            ]
            added, duplicates = db.ingest(events, workspace=args.workspace)
            print(json.dumps({"added": added, "duplicates": duplicates}))
            return 0
        if args.command == "prune":
            if args.retention_days < 1:
                raise ValueError("Retention must be positive")
            print(
                json.dumps(
                    {
                        "deleted": db.prune(
                            workspace=args.workspace,
                            older_than=datetime.now(UTC) - timedelta(days=args.retention_days),
                        ),
                    },
                ),
            )
            return 0
        qs = QuarantineStore(db)
        if args.command == "quarantine":
            now = datetime.now(UTC)
            entry = QuarantineEntry(
                workspace=args.workspace,
                repo=args.repo,
                nodeid=args.nodeid,
                source_hash=args.source_hash,
                owner=args.owner,
                issue=args.issue,
                reason=args.reason,
                approved_by=args.approved_by,
                created_at=now,
                expires_at=now + timedelta(days=args.ttl_days),
            )
            qs.save(entry, actor=args.approved_by)
            print(entry.model_dump_json(indent=2))
            return 0
        session = None
        pytest_code = None
        if args.command == "run":
            session = str(uuid4())
            env = {**os.environ, "FLAKY_RUN_ID": session}
            # This explicit command runs TRUSTED local tests. It is not offered by HTTP.
            command = [
                sys.executable,
                "-m",
                "pytest",
                "--flaky-trail",
                "--flaky-trail-db",
                str(args.db.resolve()),
                "--flaky-trail-repo",
                args.repo,
                "--flaky-trail-workspace",
                args.workspace,
                "--flaky-trail-env",
                args.env_id,
                "--flaky-trail-image",
                args.image,
                "--flaky-trail-seed-id",
                args.seed_id,
            ]
            extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
            pytest_code = subprocess.run([*command, *extra], env=env, check=False).returncode
        if args.command == "export":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as stream:
                next_page = 0
                while True:
                    page, next_page = db.page(
                        workspace=args.workspace, repo=args.repo, cursor=next_page, limit=1000
                    )
                    for event in page:
                        stream.write(
                            event.model_copy(update={"traceback": None}).model_dump_json() + "\n",
                        )
                    if next_page is None:
                        break
            return 0
        events, cursor = db.page(workspace=args.workspace, repo=args.repo, limit=10000)
        if cursor is not None:
            raise ValueError("Offline replay limit exceeded; use paged export")
        if session:
            events = [e for e in events if e.run_id == session]
        observations = MonitorEngine().evaluate(events)
        entries = qs.list(args.workspace, args.repo)
        result: dict[str, Any] = {
            "schema_version": "1",
            "observations": [o.model_dump(mode="json") for o in observations],
            "attempts": [a.model_dump(mode="json") for a in attempts_from_events(events)],
            "metrics": reliability_metrics(events, quarantine=entries),
            "change_points": change_points(events),
        }
        exit_code = 0
        if args.command == "report" and args.policy:
            from flakydetector.governance.policy import ReliabilityPolicy, evaluate_gates

            if args.policy.stat().st_size > 100000:
                raise ValueError("Policy too large")
            gate = evaluate_gates(
                ReliabilityPolicy.model_validate_json(args.policy.read_text()),
                result["metrics"],
            )
            result["quality_gate"] = gate
            exit_code = cast(int, gate["exit_code"])
        output = json.dumps(result, indent=2)
        if args.command == "report" and args.output:
            args.output.write_text(output + "\n")
        else:
            print(output)
        if args.command == "run":
            if (
                pytest_code not in {0, 1}
                or not events
                or any(e.phase == "session" and e.outcome == "error" for e in events)
            ):
                return 2
            now = datetime.now(UTC)
            if any(e.revoked_at is None and e.expires_at <= now for e in entries):
                return 1
            attempts = attempts_from_events(events)
            if any(not a.complete for a in attempts):
                return 2
            failures = [a for a in attempts if a.outcome in {"failed", "error"}]
            unquarantined = [
                a
                for a in failures
                if not applies(
                    entries,
                    workspace=args.workspace,
                    repo=args.repo,
                    nodeid=a.nodeid,
                    source_hash=a.provenance.source_hash,
                    now=now,
                )
            ]
            # All tests ran. Retry success does not automatically suppress earlier failures.
            return 1 if unquarantined or (pytest_code == 1 and (not failures)) else 0
        return exit_code
    except (ValueError, OSError) as exc:
        print(f"Evidence operation rejected ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
