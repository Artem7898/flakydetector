"""Example of async flaky test patterns."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_concurrent_requests_race_condition():
    """FLAKY: Race condition due to unsynchronized concurrent access."""
    shared_counter = {"value": 0}

    async def increment():
        temp = shared_counter["value"]
        await asyncio.sleep(0.001)  # Race condition window
        shared_counter["value"] = temp + 1

    # Run 100 concurrent increments
    tasks = [increment() for _ in range(100)]
    await asyncio.gather(*tasks)

    # This assertion may fail due to race condition
    assert shared_counter["value"] == 100


@pytest.mark.asyncio
async def test_timeout_dependency():
    """FLAKY: Depends on async operation completing within time."""

    async def slow_operation():
        await asyncio.sleep(0.1)  # Timing dependent
        return "result"

    result = await asyncio.wait_for(slow_operation(), timeout=0.15)
    assert result == "result"


@pytest.mark.asyncio
async def test_task_order_non_deterministic():
    """FLAKY: Results depend on task execution order."""
    results = []

    async def append_value(value: int):
        await asyncio.sleep(0.001 * (3 - value))  # Different delays
        results.append(value)

    await asyncio.gather(
        append_value(1),
        append_value(2),
        append_value(3),
    )

    # Order is non-deterministic
    assert results == [3, 2, 1]  # May fail
