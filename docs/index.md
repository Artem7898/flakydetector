# FlakyDetector documentation

Application version: **{{ release }}**.

FlakyDetector provides source-level test-risk analysis and records comparable
pytest execution evidence. A static finding is a reason to investigate, not proof
that a test is flaky. Model scores are not calibrated failure probabilities.

The application uses API and feature semantic schemas **3.0.0**, legacy trail schema **3** and new event schema **1**/provenance **4**. Read the migration notes before reusing an existing database or model.

## Use and understand the application

```{toctree}
:maxdepth: 2
:caption: Application

api_reference
CAPABILITY_MATRIX
MIGRATION_0.2.2
MONITORS
SARIF_ACTION
QUARANTINE
RULES
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
