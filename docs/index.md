# 🔬 FlakyDetector Documentation

Welcome to the official documentation for **FlakyDetector** — a scientific-grade research tool designed to uncover non-deterministic (flaky) tests in Python ecosystems using Abstract Syntax Tree (AST) analysis and CatBoost Machine Learning classification.

```{toctree}
:hidden:
:maxdepth: 2
:caption: Contents

research_paper
research_paper.EN
api_reference
```

## 🧠 Key Capabilities

Unlike traditional re-run-based tools, FlakyDetector statically evaluates code architecture to find latent bugs *before* they manifest in your CI/CD pipelines.

| Capability | Description |
|------------|-------------|
| **🧬 AST Pattern Matching** | Detection of 11+ anti-patterns (`time.sleep`, `datetime.now()`, global variable mutations, unmocked network calls). |
| **🧠 Explainable ML** | 42-dimensional feature space fed into a CatBoost model with built-in feature importance and SHAP-compatible interpretability. |
| **📊 Test Smells Analysis** | Identification of structural risks such as high cyclomatic complexity (>10) and fixture state leakage. |
| **🖥️ Interactive Dashboard** | Modern React + Recharts frontend for visual triage, severity distribution, and syntax highlighting. |
| **📂 CLI Scanner** | Powerful directory scanning with beautiful tabular terminal output (powered by `rich`). |
| **⚙️ CI/CD Integration** | Ready-to-use GitHub Actions workflow that blocks Pull Requests when critical patterns are detected. |
| **🐳 Production Infrastructure** | Docker support, `uv` for lightning-fast builds, and pre-commit hooks (ruff, pyright). |

## 🏗️ Core Architecture Overview

FlakyDetector is built using the principles of **Clean (Hexagonal) Architecture**, ensuring domain logic remains pure and framework-agnostic.

### Core Domain

Pure Python stateless execution engine containing AST visitors, log parsers, and Pydantic v2 validation models. This layer has zero external I/O dependencies.

### Ports & Adapters

Interfaces abstracting the concrete infrastructure:

- **FastAPI REST** — asynchronous API endpoints
- **CLI Scanner** — `rich`-powered terminal interface
- **GitHub Actions Collector** — CI event ingestion
- **React + Vite Dashboard** — frontend visualization layer

### Infrastructure

Production-grade persistence and compute layers:

- **CatBoost** — serialized model weights (`.cbm` format)
- **SQLite / PostgreSQL** — relational storage for reports
- **Local FS / Parquet** — feature vector serialization

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Adapters      │     │     Ports        │     │   Core Domain   │
│  (In/Out)       │────▶│  (Interfaces)    │────▶│  (Pure Python)  │
│                 │     │                  │     │                 │
│ • GitHub API    │     │ • Abstract       │     │ • Analysis      │
│ • CI Systems    │     │   Feature        │     │   Engine        │
│ • CLI Scanner   │     │   Extractor      │     │ • Domain        │
│ • FastAPI REST  │     │ • Abstract       │     │   Models        │
│ • React UI      │     │   Classifier     │     │ • Feature       │
│                 │     │                  │     │   Extractor     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │  Infrastructure │
                                               │  (OutPorts)     │
                                               │                 │
                                               │ • CatBoost      │
                                               │ • SQLite/PSQL   │
                                               │ • Local FS      │
                                               └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ (for UI)
- Docker (optional)

### Option 1: Local Setup (via `uv`)

```bash
# 1. Clone the repository
git clone https://github.com/Artem7898/flakydetector
cd flakydetector

# 2. Install uv and dependencies
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. Generate synthetic dataset and train the ML model
python scripts/train_model.py

# 4. Start the API server
uvicorn flakydetector.dashboard.main:app --reload --port 8001
```

### Option 2: Docker (recommended for isolation)

```bash
docker-compose up --build
```

### Start Frontend

```bash
cd dashboard_frontend
npm install
npm run dev
```

Open http://localhost:3000 — the interactive dashboard is ready.

## 📂 CLI Scanning & CI/CD Integration

### Directory Scanning

Point the analyzer at any test directory:

```bash
uv run python scripts/scan_folder.py ./my_project/tests/
```

**Sample output:**

```text
🔍 Scanning: ./my_project/tests/ ...

                               Flaky Patterns Detected
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ File               ┃ Line  ┃ Pattern             ┃ Severity   ┃ Confidence┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ test_api.py        │     3 │ time_sleep          │   MEDIUM   │       90% │
└────────────────────┴───────┴─────────────────────┴────────────┴───────────┘
```

### GitHub Actions

The included workflow (`.github/workflows/flaky_detection.yml`) automatically blocks Pull Requests when critical anti-patterns are introduced:

```yaml
- name: Run FlakyDetector
  run: uv run python scripts/scan_folder.py ./tests --fail-on-critical
```

If a pattern with `severity: CRITICAL` is found, the step exits with code 1 and the merge is blocked.

## 🔬 Scientific Methodology

FlakyDetector converts source code into a mathematical representation through a 42-dimensional feature vector:

| Feature Group | Count | Description |
|---------------|-------|-------------|
| **AST Features** | 16 | Counters for specific anti-patterns (e.g., `ast_time_sleep: 1.0`). |
| **Category Features** | 9 | Aggregate scores for root causes (Timing, State, Network, Concurrency, I/O). |
| **Test Smells** | 1 | Cyclomatic complexity of the test function. |
| **Fixture Analysis** | 5 | Fixture scope analysis (`session`, no `yield`, mutable literal returns). |
| **Derived Features** | 3 | Mathematical ratios: `ast_to_log_ratio`, `pattern_diversity`. |
| **Confidence Scores** | 8 | Maximum and average detector certainties. |

The resulting vector is fed into a CatBoost classifier, which provides both classification accuracy and **Feature Importance** for scientific interpretability of results.

For the complete scientific proof and experimental design, see the dedicated research papers:

- {doc}`research_paper` (Russian)
- {doc}`research_paper.EN` (English)

## 🛠 Development Standards

The project adheres to strict quality standards:

| Tool | Purpose |
|------|---------|
| **ruff** | Formatting and linting (replaces black, isort, flake8). |
| **pyright** | Strict typing in strict mode (Pydantic v2, Type Hints). |
| **pytest + pytest-asyncio** | Unit and integration tests. |
| **pre-commit** | Automated checks on every commit. |

```bash
# Run linting
pre-commit run --all-files

# Run tests
uv run pytest tests/unit/ -v
```

## 📚 Citation & Academic Context

If you use FlakyDetector in your academic research or industry whitepapers, please cite:

```bibtex
@software{flakydetector2026,
  author = {Alimpiev, Artem and Research Team},
  title = {FlakyDetector: Scientific-grade AST & ML Flaky Test Detection},
  year = {2026},
  url = {https://github.com/Artem7898/flakydetector},
  doi = {10.5281/zenodo.20043002}
}
```

## 👨‍💻 Author

**Artem Alimpiev** — Python Developer

- 🐙 GitHub: [Artem7898](https://github.com/Artem7898)
- 💼 LinkedIn: [artem-alimpiev](https://www.linkedin.com/in/artem-alimpiev/)
- 📧 Email: [alimpievne@gmail.com](mailto:alimpievne@gmail.com)
- 🆔 ORCID: [0009-0007-6740-7242](https://orcid.org/0009-0007-6740-7242)
- 📦 Zenodo: [Record 20042797](https://zenodo.org/records/20042797)
- 🔗 DOI: [10.5281/zenodo.20043002](https://doi.org/10.5281/zenodo.20043002)

## 📄 License

Distributed under the MIT License. See `LICENSE` file for details.

---

*Built for researchers and engineers. AST + ML. Precise. Reproducible.*