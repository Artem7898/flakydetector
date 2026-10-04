"""Example of timing-dependent flaky test patterns."""

import time
from datetime import datetime


def test_time_sleep_dependency():
    """FLAKY: Uses time.sleep without proper synchronization."""
    start_time = time.time()

    # Simulate async operation
    time.sleep(0.1)

    elapsed = time.time() - start_time

    # This may fail on slow systems
    assert elapsed < 0.15


def test_datetime_now_dependency():
    """FLAKY: Uses datetime.now() which is non-deterministic."""
    before = datetime.utcnow()

    # Some operation
    result = str(datetime.utcnow())

    _after = datetime.utcnow()

    # This assertion is timing-dependent
    assert before.strftime("%Y-%m-%d") in result


def test_performance_threshold():
    """FLAKY: Performance test without proper thresholds."""
    start = time.time()

    # Some operation
    sum(range(1000000))

    elapsed = time.time() - start

    # May fail on slow CI or under load
    assert elapsed < 0.05
