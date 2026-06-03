# 🔬 FlakyDetector Documentation

Welcome to the official documentation for **FlakyDetector** — a scientific-grade researcher tool designed to uncover non-deterministic (flaky) tests in Python ecosystems using Abstract Syntax Tree (AST) analysis and CatBoost Machine Learning classification.

---

## 🏗️ Architecture & API Reference

```{toctree}
:maxdepth: 2
:caption: Содержание:

api_reference.md
architecture.txt
architecture_summary.txt
research_paper.EN.md
research_paper.RU.md
```

---

## ✨ Key Capabilities

:::{note}
Unlike traditional re-run-based tools, FlakyDetector statically evaluates code architecture to find latent bugs *before* they manifest in your CI/CD pipelines.
:::


| Capability | Description |
|-------------|----------|
| **🧬 AST Pattern Matching** | Detection of 11+ anti-patterns (`time.sleep`, global mutation, unmocked networking). |
| **🧠 Explainable ML** | 42-Dimensional feature space fed into a CatBoost model with built-in feature importance. |
| **📊 Test Smells Analysis** | Identification of structural risks such as high cyclomatic complexity (>10). |
| **🖥️ Interactive Dashboard** | Modern React + Recharts frontend for visual triage and syntax highlighting. |

---

## 🏗️ Core Architecture Overview

FlakyDetector is built using the principles of **Clean (Hexagonal) Architecture**:

1. **Core Domain**: Pure Python stateless execution engine containing the AST visitors and Pydantic validation models.
2. **Ports/Adapters**: Interfaces for the FastAPI backend, CLI Scanner (powered by `rich`), and GitHub Actions collectors.
3. **Infrastructure**: Production layers handling CatBoost weights serialization (`.cbm`) and Parquet file generation.

---

## 🚀 1: Quick Start

### Option 1: Local Setup (via uv)

```bash
git clone https://github.com
cd flakydetector
curl -LsSf https://astral.sh | sh
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
python scripts/train_model.py
uvicorn flakydetector.dashboard.main:app --reload --port 8001
```

### Option 2: Docker

```bash
docker-compose up --build
```

---

## 📂 CLI Scanning & CI/CD

### Point the analyzer at any test directory:

```bash
uv run python scripts/scan_folder.py ./my_project/tests/
```

### The included GitHub Actions workflow automatically blocks Pull Requests when critical anti-patterns are introduced.



## 🔬 Scientific Methodology & RAG Pipeline
FlakyDetector converts source code into a mathematical representation through a 42-dimensional feature vector (expanded from 37D via pytest fixture state analysis). The model automatically discovered that the absence of teardown logic (yield) is the strongest predictor of flakiness (feature importance: 66.00%).

Cognitive RAG Layer (Sprints 2-3): Beyond static ML, FlakyDetector implements a Retrieval-Augmented Generation pipeline:

Telemetry: The pytest-flaky-trail plugin captures execution outcomes into SQLite.
Extraction: AST parsers isolate failing function contexts.
LLM Analysis: Local LLMs (e.g., Qwen 2.5 Coder) provide root-cause categorization and fix strategies.
Vector Search: Explanations are embedded via ChromaDB, allowing semantic search for tests with similar flakiness patterns (e.g., "find all tests with state leakage").

## 🛠️ Development Standards

```text
Tool         Purpose
ruff         Formatting and linting
pyright      Strict typing
pytest       Unit and integration tests
pre-commit   Automated checks on every commit
```



## 📚 Citation & Academic Context

If you use FlakyDetector in your academic research or industry whitepapers, please use the following citation format:

```bibtex
@software{flakydetector2026,
  author = {Alimpiev, Artem and Research Team},
  title = {FlakyDetector: Scientific-grade AST & ML Flaky Test Detection},
  year = {2026},
  url = {https://github.com},
  doi = {10.5281/zenodo.20043002}
}
```

---

## 👨‍💻 Author

### Artem Alimpiev — Python Developer

* 🐙 **GitHub**: [Artem7898](https://github.com)
* 💼 **LinkedIn**: [artem-alimpiev](https://linkedin.com)
* 📧 **Email**: alimpievne@gmail.com
* 🆔 **ORCID**: 0009-0007-6740-7242

---

## 📄 License

Distributed under the MIT License. See LICENSE for details.

<div align="center">

Built for researchers and engineers. AST + ML. Precise. Reproducible.

</div>
