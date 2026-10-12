"""Product contracts: rule identity, privacy, policy, events and non-causal monitors."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from flakydetector.application import AnalyzeService
from flakydetector.governance.lifecycle import LifecycleEvent, LifecycleStore
from flakydetector.governance.quarantine import QuarantineEntry, QuarantineStore, applies
from flakydetector.input import InputError, zip_bundle
from flakydetector.intelligence.metrics import change_points, reliability_metrics
from flakydetector.reporting.baseline import compare, create_baseline, policy_exit
from flakydetector.reporting.sarif import to_sarif
from flakydetector.runtime.models import ExecutionEvent, Provenance
from flakydetector.runtime.monitors import MonitorEngine, attempts_from_events, compatible
from flakydetector.runtime.store import EventConflict, EvidenceStore
from flakydetector.security.auth import Principal, authenticate, load_credentials
from flakydetector.security.privacy import redact, safe_path
from flakydetector.security.projection import project_response
from flakydetector.utils.config import Settings

NOW = datetime(2026, 10, 11, tzinfo=UTC)
HASH = "a" * 64


def analyze(code, name="tests/test_case.py"):
    return AnalyzeService(Settings()).analyze({name: code})


def context(**updates):
    return Provenance(
        source_hash=HASH,
        environment_hash="b" * 64,
        revision="c" * 40,
        dirty=False,
        recorded_context_complete=True,
        components=dict.fromkeys(
            ("python", "dependencies", "config", "collection", "external_state", "seed", "image"),
            "known",
        ),
    ).model_copy(
        update=updates,
    )


def events(
    outcome="passed",
    *,
    run="r1",
    invocation="i1",
    attempt=1,
    node="test_x.py::test_x",
    when=NOW,
    provenance=None,
    duration=0.1,
    kind="assertion",
):
    return [
        ExecutionEvent(
            event_id=f"{run}:{invocation}:{attempt}:{phase}",
            workspace="local",
            repo="a/b",
            run_id=run,
            invocation_id=invocation,
            nodeid=node,
            attempt=attempt,
            phase=phase,
            sequence=attempt * 3 + i,
            outcome=outcome if phase == "call" else "passed",
            started_at=when + timedelta(seconds=i),
            ended_at=when + timedelta(seconds=i + duration),
            duration=duration,
            provenance=provenance or context(),
            failure_kind=kind if phase == "call" and outcome != "passed" else "unknown",
        )
        for i, phase in enumerate(("setup", "call", "teardown"))
    ]


def observation(rows, name):
    return next(o for o in MonitorEngine().evaluate(rows) if o.monitor == name)


@pytest.mark.parametrize(
    "body,mitigated",
    [
        (
            'if False:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            False,
        ),
        (
            'if flag:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            False,
        ),
        (
            'if flag:\n        monkeypatch.setattr("requests.get", lambda: None)\n    else:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            True,
        ),
        (
            'if True:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            True,
        ),
        (
            'if flag:\n        return\n    else:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            True,
        ),
        (
            'with patch("requests.get"):\n        pass\n    requests.get("https://example.invalid")',
            False,
        ),
        (
            'try:\n        monkeypatch.setattr("requests.get", lambda: None)\n    except Exception:\n        pass\n    requests.get("https://example.invalid")',
            False,
        ),
        (
            'monkeypatch.setattr("requests.get", lambda: None)\n    monkeypatch.undo()\n    requests.get("https://example.invalid")',
            False,
        ),
        (
            'for x in []:\n        monkeypatch.setattr("requests.get", lambda: None)\n    requests.get("https://example.invalid")',
            False,
        ),
    ],
)
def test_mock_control_flow(body, mitigated):
    code = (
        "import requests\nfrom unittest.mock import patch\ndef test_x(monkeypatch,flag):\n    "
        + body
        + "\n"
    )
    response = analyze(code)
    patterns = [
        p
        for result in response.results
        for p in result.patterns
        if p.pattern_type == "network_call"
    ]
    assert patterns
    assert patterns[-1].metadata["is_mocked"] is mitigated


@pytest.mark.parametrize(
    "left,right",
    [
        (
            'import requests\ndef test_x():\n    requests.get("https://example.invalid")\n',
            'import requests as r\ndef test_x():\n    r.get("https://example.invalid")\n',
        ),
        (
            "import time\ndef test_x():\n    time.sleep(1)\n",
            "import time\n\n# added comment\ndef test_x():\n    time.sleep(1)\n",
        ),
    ],
)
def test_identity_survives_alias_and_line_shift(left, right):
    assert [f.finding_id for f in analyze(left).findings] == [
        f.finding_id for f in analyze(right).findings
    ]


@pytest.mark.parametrize("separator", ["; ", "\n    "])
def test_duplicate_statements_get_distinct_ids(separator):
    response = analyze(
        "import time\ndef test_x():\n    time.sleep(1)" + separator + "time.sleep(1)\n"
    )
    findings = [f for f in response.findings if f.rule_id == "FD-TIME-001"]
    assert len(findings) == 2
    assert len({f.finding_id for f in findings}) == 2


@pytest.mark.parametrize(
    "kind,code,expected",
    [
        (
            "FD-NET-002",
            'import httpx\ndef test_x():\n    c=httpx.Client(timeout=0.2)\n    c.post("https://example.invalid")',
            True,
        ),
        (
            "FD-NET-002",
            'import requests\ndef test_x():\n    c=requests.Session()\n    c.get("https://example.invalid")',
            True,
        ),
        (
            "FD-NET-002",
            'import aiohttp\nasync def test_x():\n    async with aiohttp.ClientSession() as c:\n        await c.get("https://example.invalid")',
            True,
        ),
        (
            "FD-NET-002",
            'import httpx\ndef test_x():\n    c=httpx.Client(transport=httpx.MockTransport(handler))\n    c.get("https://example.invalid")',
            False,
        ),
        (
            "FD-ASYNC-003",
            "import asyncio\nasync def test_x():\n    task=asyncio.create_task(work())",
            True,
        ),
        (
            "FD-ASYNC-003",
            "import asyncio\nasync def test_x():\n    task=asyncio.create_task(work())\n    await task",
            False,
        ),
        (
            "FD-ASYNC-003",
            "import asyncio\nasync def test_x():\n    task=asyncio.create_task(work())\n    await asyncio.gather(task)",
            False,
        ),
        (
            "FD-ASYNC-003",
            "import asyncio\nasync def test_x():\n    task=asyncio.create_task(work())\n    task.cancel()",
            True,
        ),
        (
            "FD-ASYNC-003",
            "import asyncio\nasync def test_x():\n    task=asyncio.create_task(work())\n    task.cancel()\n    await task",
            False,
        ),
        ("FD-ASYNC-001", "import asyncio\nasync def test_x():\n    await asyncio.sleep(0)", False),
        ("FD-ASYNC-001", "import asyncio\nasync def test_x():\n    await asyncio.sleep(1)", True),
        (
            "FD-FS-002",
            'def test_x():\n    with open("shared.txt","w") as f:\n        f.write("x")',
            True,
        ),
        (
            "FD-FS-002",
            'def test_x(tmp_path):\n    with open(tmp_path / "x","w") as f:\n        f.write("x")',
            False,
        ),
        ("FD-ENV-001", 'import os\ndef test_x():\n    os.chdir("/tmp")', True),
        (
            "FD-ENV-001",
            'import os\ndef test_x():\n    old=os.getcwd()\n    try:\n        os.chdir("/tmp")\n    finally:\n        os.chdir(old)',
            False,
        ),
        ("FD-ENV-002", 'import os\ndef test_x():\n    os.environ["TZ"]="UTC"', True),
        ("FD-ENV-002", 'def test_x(monkeypatch):\n    monkeypatch.setenv("TZ","UTC")', False),
        ("FD-TIME-002", "from datetime import date\ndef test_x():\n    assert date.today()", True),
        ("FD-RANDOM-001", "import random\ndef test_x():\n    assert random.random()>0.5", True),
        (
            "FD-RANDOM-001",
            "import random\ndef test_x():\n    random.seed(42)\n    assert random.random()>0.5",
            False,
        ),
        ("FD-RANDOM-001", "import uuid\ndef test_x():\n    key=str(uuid.uuid4())", False),
        (
            "FD-CONCURRENCY-001",
            "import threading\ndef test_x():\n    t=threading.Thread(target=work)\n    t.start()",
            True,
        ),
        (
            "FD-CONCURRENCY-001",
            "import threading\ndef test_x():\n    t=threading.Thread(target=work)\n    t.start()\n    t.join()",
            False,
        ),
    ],
)
def test_selective_semantics(kind, code, expected):
    assert (kind in {f.rule_id for f in analyze(code).findings}) is expected


@pytest.mark.parametrize(
    "bad",
    [
        "../test_x.py",
        "/test_x.py",
        "C:\\test_x.py",
        ".env",
        "keys.pem",
        "a/../../x.py",
        "test_\nx.py",
        "a/" * 30 + "test_x.py",
    ],
)
def test_safe_paths(bad):
    with pytest.raises(ValueError):
        safe_path(bad)


@pytest.mark.parametrize(
    "text",
    [
        'password="CANARY_SECRET"',
        'token = "CANARY_SECRET"',
        "Authorization: Bearer CANARY_SECRET",
        'url="https://user:CANARY_SECRET@example.invalid"',
        'secret="""CANARY_SECRET\nsecond-line"""',
        "-----BEGIN " + "PRIVATE KEY-----\nCANARY_SECRET\n-----END " + "PRIVATE KEY-----",
    ],
)
def test_redaction(text):
    assert "CANARY_SECRET" not in redact(text)
    assert redact(redact(text)) == redact(text)


@pytest.mark.parametrize(
    "permitted,requested,configured",
    [(False, True, True), (True, False, True), (True, True, False), (True, True, True)],
)
def test_privacy_projection(permitted, requested, configured):
    response = analyze('import time\nsecret="CANARY_SECRET"\ndef test_x():\n    time.sleep(1)')
    principal = Principal(
        "reader",
        frozenset({"local"}),
        frozenset({"source:read"} if permitted else {"findings:read"}),
    )
    projected = project_response(
        response,
        Settings(source_mode="redacted" if configured else "disabled"),
        principal,
        "local",
        include_source=requested,
    )
    assert "CANARY_SECRET" not in projected.model_dump_json()
    assert bool(projected.source_snapshots) is (permitted and requested and configured)
    assert projected.source_digests == response.source_digests
    # Its own output must be parseable: no unaccepted computed properties.
    assert type(response).model_validate_json(projected.model_dump_json()) == projected


@pytest.mark.parametrize("remote,token", [(False, None), (True, None), (True, "short")])
def test_shared_requires_explicit_auth(remote, token):
    with pytest.raises(ValueError):
        Settings(profile="shared", allow_remote=remote, api_token=token)


def test_scoped_credentials(tmp_path):
    file = tmp_path / "keys.json"
    file.write_text(
        json.dumps(
            [
                dict(
                    subject="reader",
                    sha256=hashlib.sha256(b"canary-access").hexdigest(),
                    workspaces=["one"],
                    scopes=["findings:read"],
                ),
            ],
        ),
    )
    creds = load_credentials(file)
    user = authenticate("Bearer canary-access", creds)
    assert user.permits("findings:read", "one")
    assert not user.permits("source:read", "one") and (not user.permits("findings:read", "two"))
    assert authenticate("Bearer wrong", creds) is None


@pytest.mark.parametrize(
    "mode", ["depth", "count", "ratio", "case", "unicode", "traversal", "symlink"]
)
def test_zip_rejects_unsafe_archives(mode):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        if mode == "depth":
            z.writestr("a/" * 25 + "test_x.py", "pass")
        if mode == "count":
            for i in range(1001):
                z.writestr(f"d{i}/", "")
        if mode == "ratio":
            z.writestr("test_x.py", "a" * 100000)
        if mode == "case":
            z.writestr("test_x.py", "pass")
            z.writestr("TEST_X.py", "pass")
        if mode == "unicode":
            z.writestr("test_é.py", "pass")
            z.writestr("test_é.py", "pass")
        if mode == "traversal":
            z.writestr("../test_x.py", "pass")
        if mode == "symlink":
            info = zipfile.ZipInfo("test_x.py")
            info.external_attr = (stat.S_IFLNK | 511) << 16
            z.writestr(info, "target")
    with pytest.raises(InputError):
        zip_bundle(output.getvalue(), Settings())


def test_sarif_source_free_and_location():
    response = analyze(
        'import requests\ndef test_x():\n    secret="CANARY_SECRET"; requests.get("https://example.invalid")',
        "tests/test_é.py",
    )
    sarif = to_sarif(response)
    run = sarif["runs"][0]
    assert sarif["version"] == "2.1.0" and run["columnKind"] == "unicodeCodePoints"
    assert "CANARY_SECRET" not in json.dumps(sarif)
    assert (
        run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "tests/test_%C3%A9.py"
    )
    assert run["results"][0]["locations"][0]["physicalLocation"]["region"]["startColumn"] > 1
    assert all(
        "security-severity" not in rule["properties"] for rule in run["tool"]["driver"]["rules"]
    )
    # upload-sarif computes its own line hash.
    assert "partialFingerprints" not in run["results"][0]


@pytest.mark.parametrize("code,success", [("def test_x(): pass", True), ("def test_x(:", False)])
def test_sarif_empty_or_error(code, success):
    sarif = to_sarif(analyze(code))
    assert sarif["runs"][0]["invocations"][0]["executionSuccessful"] is success


def test_baseline_policy_and_drift():
    old = analyze('import requests\ndef test_x():\n    requests.get("https://example.invalid")')
    base = create_baseline(old, revision="abc1234", scope=".", accepted_by="owner")
    current = analyze(
        'import requests\n\ndef test_x():\n    requests.get("https://example.invalid")'
    )
    current, absent = compare(current, base, expected_revision="abc1234", scope=".")
    assert not absent and current.findings[0].baseline_state == "existing"
    assert policy_exit(current, new_only=True) == 0 and policy_exit(current) == 1
    with pytest.raises(ValueError):
        compare(current, base, expected_revision="hijacked", scope=".")
    low = base.model_copy(
        update={"findings": tuple(f.model_copy(update={"severity": "low"}) for f in base.findings)},
    )
    assert (
        compare(current, low, expected_revision="abc1234", scope=".")[0].findings[0].baseline_state
        == "worsened"
    )
    incomplete = analyze("def test_x(:")
    assert (
        compare(incomplete, base, expected_revision="abc1234", scope=".")[1][0].baseline_state
        == "inconclusive"
    )
    assert policy_exit(incomplete, fail_on="none", new_only=True) == 2


@pytest.mark.parametrize(
    "updates,expected",
    [
        ({"dirty": True}, "unknown"),
        ({"dirty": None}, "unknown"),
        ({"revision": ""}, "unknown"),
        ({"recorded_context_complete": False}, "unknown"),
        ({"components": {}}, "unknown"),
        ({"revision": "d" * 40}, "incompatible"),
        ({"source_hash": "d" * 64}, "incompatible"),
        ({"environment_hash": "d" * 64}, "incompatible"),
        ({}, "compatible"),
    ],
)
def test_comparison_policy(updates, expected):
    assert compatible(context(), context(**updates)) == expected


def test_event_store_atomic_idempotency_and_tenant_isolation(tmp_path):
    store = EvidenceStore(tmp_path / "events.db")
    ev = events()
    assert store.ingest(ev, workspace="local") == (3, 0)
    assert store.ingest(ev, workspace="local") == (0, 3)
    with pytest.raises(EventConflict):
        store.ingest(
            [
                *events(run="second", invocation="second"),
                ev[0].model_copy(update={"duration": 2.0}),
            ],
            workspace="local",
        )
    assert len(store.page(workspace="local", repo="a/b")[0]) == 3
    assert not store.page(workspace="other", repo="a/b")[0]
    first, cursor = store.page(workspace="local", repo="a/b", limit=2)
    assert (
        len(first) == 2
        and cursor
        and (len(store.page(workspace="local", repo="a/b", cursor=cursor)[0]) == 1)
    )
    assert (
        store.prune(
            workspace="local", older_than=NOW + timedelta(hours=1), now=NOW + timedelta(days=1)
        )
        == 3
    )


def test_secret_differences_still_conflict(tmp_path):
    store = EvidenceStore(tmp_path / "events.db")
    ev = events()[0].model_copy(update={"traceback": 'password="first_canary"'})
    store.ingest([ev], workspace="local")
    with pytest.raises(EventConflict):
        store.ingest(
            [ev.model_copy(update={"traceback": 'password="second_canary"'})],
            workspace="local",
        )
    assert "first_canary" not in store.page(workspace="local", repo="a/b")[0][0].model_dump_json()


def test_out_of_order_phases_and_incomplete():
    ev = events()
    assert attempts_from_events(list(reversed(ev)))[0].outcome == "passed"
    assert attempts_from_events(ev[:2])[0].outcome == "incomplete"
    assert attempts_from_events([*ev, ev[0]]) == attempts_from_events(ev)
    duplicate = ev[0].model_copy(update={"event_id": "conflicting-phase"})
    assert attempts_from_events([*ev, duplicate])[0].outcome == "incomplete"


@pytest.mark.parametrize(
    "bad", [{"dirty": True}, {"components": {}}, {"environment_hash": "d" * 64}]
)
def test_no_false_flake_from_incompatible_retry(bad):
    ev = events("failed") + events(
        "passed", attempt=2, when=NOW + timedelta(seconds=20), provenance=context(**bad)
    )
    assert observation(ev, "pass_on_retry").status != "detected"


def test_runtime_verdicts_separate_retry_sessions_and_rate():
    ev = events("failed") + events("passed", attempt=2, when=NOW + timedelta(seconds=20))
    assert observation(ev, "pass_on_retry").verdict == "observed_flaky_behavior"
    assert observation(ev, "intermittent_same_commit").status != "detected"
    ev += events("passed", run="r2", invocation="i2", when=NOW + timedelta(days=1))
    assert observation(ev, "intermittent_same_commit").status == "detected"
    allfailed = [
        e
        for i in range(12)
        for e in events("failed", run=f"r{i}", invocation=f"i{i}", when=NOW + timedelta(days=i))
    ]
    assert observation(allfailed, "failure_rate_window").verdict == "elevated_failure_rate"
    assert observation(allfailed, "intermittent_same_commit").status != "detected"


def test_controlled_order_not_an_ordinary_comparison():
    ev = []
    for treatment, outcome in [("A", "passed"), ("B", "failed")]:
        p = context(
            experiment_id="controlled",
            treatment_axis="order",
            treatment_value=treatment,
            components={**context().components, "collection": treatment},
            environment_hash=hashlib.sha256(treatment.encode()).hexdigest(),
        )
        for i in range(3):
            ev += events(outcome, run=f"{treatment}{i}", invocation=f"{treatment}{i}", provenance=p)
    assert observation(ev, "order_permutation").verdict == "order_dependent"
    assert observation(ev, "intermittent_same_commit").status != "detected"


def test_blast_radius_is_suspicion_without_independent_evidence():
    ev = [
        e
        for i in range(6)
        for e in events("failed", node=f"test_x.py::test_{i}", invocation=f"i{i}")
    ]
    o = observation(ev, "infra_blast_radius")
    assert o.verdict == "suspected_infrastructure_incident" and o.confidence == "low"


def test_static_no_history_stays_static():
    o = MonitorEngine().evaluate([], static_nodeids=["test_x.py::test_x"])
    static = next(x for x in o if x.monitor == "static_risk_only")
    assert static.verdict == "risk_detected"
    assert all(x.status == "insufficient_evidence" for x in o if x.monitor != "static_risk_only")


def test_quarantine_renew_revoke_does_not_change_evidence(tmp_path):
    db = EvidenceStore(tmp_path / "ledger.db")
    db.ingest(events("failed"), workspace="local")
    store = QuarantineStore(db)
    entry = QuarantineEntry(
        workspace="local",
        repo="a/b",
        nodeid="test_x.py::test_x",
        source_hash=HASH,
        owner="team",
        issue="issue:1",
        reason="Investigating test cleanup",
        approved_by="owner",
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )
    store.save(entry, actor="owner")
    assert applies(
        store.list("local", "a/b"),
        workspace="local",
        repo="a/b",
        nodeid=entry.nodeid,
        source_hash=HASH,
        now=NOW,
    )
    assert not applies(
        (entry,),
        workspace="local",
        repo="a/b",
        nodeid=entry.nodeid,
        source_hash=HASH,
        now=entry.expires_at,
    )
    renewed = store.renew(
        workspace="local",
        id=entry.id,
        expected_version=1,
        actor="owner",
        expires_at=NOW + timedelta(days=12),
        now=NOW + timedelta(days=6),
        reason="Renewed after another review",
    )
    assert renewed.original_created_at == NOW
    with pytest.raises(ValueError):
        store.renew(
            workspace="local",
            id=entry.id,
            expected_version=1,
            actor="owner",
            expires_at=NOW + timedelta(days=12),
            now=NOW + timedelta(days=6),
            reason="Concurrent stale renewal",
        )
    revoked = store.revoke(
        workspace="local",
        id=entry.id,
        expected_version=2,
        actor="owner",
        reason="Fixed and confirmed by review",
        now=NOW + timedelta(days=7),
    )
    assert not revoked.active(NOW + timedelta(days=7))
    assert attempts_from_events(db.page(workspace="local", repo="a/b")[0])[0].outcome == "failed"


@pytest.mark.parametrize(
    "change",
    [
        {"owner": ""},
        {"nodeid": "test_*"},
        {"expires_at": NOW + timedelta(days=31)},
        {"expires_at": NOW},
        {"created_at": datetime(2026, 10, 11)},
    ],
)
def test_invalid_quarantine_rejected(change):
    data = dict(
        workspace="local",
        repo="a/b",
        nodeid="test_x.py::test_x",
        source_hash=HASH,
        owner="team",
        issue="issue:1",
        reason="Investigating test cleanup",
        approved_by="owner",
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )
    with pytest.raises(ValidationError):
        QuarantineEntry(**{**data, **change})


def test_metrics_null_without_evidence_and_separate_denominators():
    empty = reliability_metrics([])
    assert empty["first_attempt_failure_rate"] is None
    assert empty["static_finding_precision"] is None
    assert empty["median_time_to_fix_seconds"] is None
    ev = events("failed") + events("passed", attempt=2, when=NOW + timedelta(seconds=20))
    m = reliability_metrics(ev)
    assert m["first_attempt_failure_rate"] == 1 and m["final_failure_rate"] == 0
    assert m["pass_on_retry_count"] == 1 and m["runs"] == 1 and (m["attempts"] == 2)


def test_lifecycle_review_is_not_adoption(tmp_path):
    store = LifecycleStore(EvidenceStore(tmp_path / "events.db"))
    for i, kind in enumerate(("opened", "triaged", "fixed", "review_false_positive")):
        ev = LifecycleEvent(
            event_id=str(i),
            workspace="local",
            repo="a/b",
            finding_id=HASH,
            kind=kind,
            at=NOW + timedelta(hours=i),
            actor="reviewer",
            independent_review=True,
        )
        assert store.append(ev, actor="reviewer") and (not store.append(ev, actor="reviewer"))
    m = reliability_metrics([], lifecycle=store.list("local", "a/b"))
    assert m["static_finding_precision"] == 0 and m["median_time_to_fix_seconds"] == 7200


def test_exploratory_change_requires_exposure():
    rows = [
        e
        for i in range(40)
        for e in events(
            "passed" if i < 20 else "failed",
            run=f"r{i}",
            invocation=f"i{i}",
            when=NOW + timedelta(days=i),
        )
    ]
    assert not change_points(rows[:50])
    signals = change_points(rows)
    assert len(signals) == 1 and signals[0]["status"] == "exploratory_change"
