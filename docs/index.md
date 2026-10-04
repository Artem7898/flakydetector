# FlakyDetector documentation

Current candidate: **{{ release }}**.

FlakyDetector provides source-level test-risk analysis and records comparable
pytest execution evidence. A static finding is a reason to investigate, not proof
that a test is flaky. Model scores are not calibrated failure probabilities.

The current candidate uses API and feature semantic schemas **2.1.0** and ledger
schema **3**. Read the migration notes before reusing an existing database or model.

## Use and understand the application

```{toctree}
:maxdepth: 2
:caption: Application

api_reference
architecture
architecture_summary
LIMITATIONS
MIGRATION_0.2.1
```

## Evaluate the evidence

```{toctree}
:maxdepth: 1
:caption: Evidence and research

BENCHMARK
research_paper.EN
research_paper.RU
history/0.2.0/README
```

## Maintain the project

```{toctree}
:maxdepth: 1
:caption: Maintainers

readthedocs
IMPLEMENTATION_STATUS.RU
REMEDIATION.RU
```

The archived 0.2.0 reports are retained for comparison, not presented as current
verification. New verification belongs to the exact source archive being checked.
