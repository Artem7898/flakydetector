# 🔬 FlakyDetector Documentation

Welcome to the official documentation for **FlakyDetector** — a scientific-grade researcher tool designed to uncover non-deterministic (flaky) tests in Python ecosystems using Abstract Syntax Tree (AST) analysis and CatBoost Machine Learning classification.

---

```{toctree}
:maxdepth: 2
:caption: 🚀 Getting Started

index
```

```{toctree}
:maxdepth: 2
:caption: 🧠 Scientific Methodology

architecture
```

```{toctree}
:maxdepth: 2
:caption: 💻 API Reference

api_reference
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

## 👨‍💻 Citation & Academic Context

If you use FlakyDetector in your academic research or industry whitepapers, please use the following citation format:

```bibtex
@software{flakydetector2026,
  author = {Research Team},
  title = {FlakyDetector: Scientific-grade AST & ML Flaky Test Detection},
  year = {2026},
  url = {https://github.com}
}
```
