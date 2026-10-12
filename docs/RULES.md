# Selective static semantics

Rule IDs are versioned in `reporting/catalog.py`; they are not reused as probabilities.
A result includes facts the implementation observed, limitations and suggested experiments.
The 42-dimensional ML input still exists, but semantic schema 3.0.0 rejects old models.
New rules do not automatically become extra ML dimensions.

The extended analyzer handles supported imported client objects, explicit controlled transports,
assigned task/worker handles, visible joins/awaits, selected environment/cwd restore patterns,
shared database writes, fixed cache keys and file paths, uncontrolled draws inside assertions
and fixed-sleep polling. It does not prove that all resources are isolated or all mocks execute.
Unknown control flow cannot safely suppress risk. `asyncio.sleep(0)` alone is not a timing-risk
classification; a generic concurrency advisory may remain even for an awaited task.

Supported negative controls include unreachable/conditional patches, proper TaskGroup/await,
controlled mock transports and tmp_path usage. Dynamic SDK clients, arbitrary helper chains,
all NumPy/Faker APIs, aliasing through unknown callables and exception-sensitive resource lifetime
are not comprehensively resolved. Exact float comparison remains a brittle-assertion signal;
it may fail deterministically. A naive timestamp or UUID is not automatically an intermittent bug.

Impact analysis returns reasoned affected edges and falls back to a wider/full scan for unknown
helpers/dynamic dependencies/deletions. It is not an authoritative test-selection oracle.
The included synthetic corpus exercises selected rules; it is not independently labeled research.
