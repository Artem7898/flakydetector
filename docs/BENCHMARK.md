> **0.2.1rc1:** execution records must carry provenance version 3. Clone guards now hash the selected target test AST. Old 0.2.0 hashes/labels/model manifests are not silently upgraded. No independent reviewed benchmark was run for this candidate; the protocol below describes required work, not measured accuracy.

# Reproducible evaluation protocol

The previous synthetic 120-example experiment does not establish production accuracy or causation. In particular, feature importance for fixture `yield` does not demonstrate that its absence causes flakiness. New inference models must not repair broken instrumentation by learning its defects.

## Data and independent review

1. Fix a repository revision and source fingerprint. Record dependencies, Python/platform, seed, collection order, worker configuration and external-service snapshot. Repeated executions are comparable only under the declared experimental conditions. If varying seed/order deliberately, retain strata and provenance rather than silently pooling them.
2. Record all setup/call/teardown phases. Keep passed, failed/error, skipped, xfailed/xpassed, unknown and incomplete distinct. Export requires at least five comparable terminal attempts by default. This threshold is an observation policy, not statistical proof of stability.
3. Distinguish all-observed-passed, always-failing and intermittently-failing. Only the latter has observed binary label 1. Exported labels remain unreviewed. Independently inspect causes; populate `reviewed=true`, `review_notes` and `root_causes` for positive labels without consulting the rules being evaluated. Preserve source and ancestor fixture context. Do not derive causes from a rule name, feature importance or LLM hypothesis.
4. Hold out entire repositories for validation and test. Remove template clones across splits. The implemented conservative AST normalization removes names and literal values; it catches normalized templates but is not a general semantic-clone detector. Review false grouping and transformed clones independently. Each split must contain both labels.

## Shared features and comparisons

`FEATURE_NAMES`, semantic schema version and its hash identify the same 42 dimensions in training and serving. Vectors contain source/log counts, confidences, categories, ratios and **used** fixture features. There is no traceback keyword appended as a target-leaking feature. Training currently uses static source evidence only; logging-derived feature dimensions are zero when no log evidence is supplied, just as in the API.

`train_model.py` refuses to run without a reviewed dataset and explicit validation/test repository lists. It rejects incomplete source/fixture analysis, duplicates, monoclass splits and detected template leakage. It compares the default CLI high/critical-severity rule decision, depth-3 decision-tree tabular baseline, constant prevalence baseline and CatBoost. CatBoost keeps early stopping and seed 42. This is evaluation infrastructure; no production dataset/model is bundled.

```bash
uv run --extra ml python scripts/train_model.py --dataset data/reviewed.jsonl \
  --validation-repo owner/validation --test-repo owner/heldout \
  --output data/candidate.cbm --report data/evaluation.json
```

## Required reporting

The report records dataset hash, schema hash, split identities, seed, ROC-AUC, average precision, precision/recall at the frozen default 0.7 CI threshold, false-positive rate, uncalibrated Brier score, descriptive reliability bins, all-observed-passed-suite false positives, recall by reviewed cause, baseline results and accepted/submitted analysis coverage. Current preparation is fail-closed: an unresolvable record aborts the benchmark, rather than improving measured accuracy by silently dropping it.

Real-world release review additionally needs externally validated stable-suite membership, calibration analysis and repository-level confidence intervals and repeated holdouts at realistic prevalence. Sample confidence is not established by a handful of synthetic examples. Calibration must use data separate from training and the final test set; the adapter currently rejects manifests claiming a calibration implementation it cannot execute. It exposes raw scores with `calibrated_probability=null`.

The script writes its evaluation report before checking the minimum precision/recall gate. A failed gate does not save a new inference artifact. The script's candidate success is **not** a substitute for external dataset/protocol review. Deployment only accepts a matching feature schema/checksum and an evaluated manifest; reviewers must additionally approve the report and dataset. No new deployment model was trained during remediation. A tiny temporary model is used solely to regression-test save/load compatibility.

## Sources used to verify adapter contracts

- [pytest phase hooks](https://docs.pytest.org/en/stable/reference/reference.html)
- [CatBoost feature names](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_set_feature_names)
- [uv non-editable Docker installation](https://docs.astral.sh/uv/guides/integration/docker/)
- [Chroma collection configuration](https://docs.trychroma.com/reference/python)
