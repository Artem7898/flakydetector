# 💻 API Reference

This section provides comprehensive, low-level technical documentation for the core python modules of the FlakyDetector architecture. It is synchronized with the source code via static analysis.

## 🧬 Layer 1: Analysis Engine (Stateless AST Scanning)

The analysis engine parses source files into Abstract Syntax Trees and inspects nodes for static code anomalies.

### AST Analyzer
```{automodule} flakydetector.analyzer.ast_analyzer
   :members:
   :undoc-members:
   :show-inheritance:
```

### Log Analyzer
```{automodule} flakydetector.analyzer.log_analyzer
   :members:
   :undoc-members:
   :show-inheritance:
```

---

## 🧠 Layer 2: Machine Learning Pipeline

Handles data vectorization and wraps the CatBoost inference engine.

### Feature Extractor (37D to 42D)
```{automodule} flakydetector.classifier.feature_extractor
   :members:
   :show-inheritance:
```

### CatBoost Wrapper
```{automodule} flakydetector.classifier.catboost_model
   :members:
   :show-inheritance:
```

---

## 🖥️ Layer 3: Dashboard & REST API

FastAPI components powering the user-facing reporting panels.

### API Gateway Routes
```{automodule} flakydetector.dashboard.routes
   :members:
   :undoc-members:
```

### Data Validation Schemas
```{automodule} flakydetector.dashboard.models
   :members:
   :show-inheritance:
```

---

## 🛠️ Infrastructure and Utilities

### Typestable Configurations (.env Parser)
```{automodule} flakydetector.utils.config
   :members:
```

### Logger Facility (structlog wrapper)
```{automodule} flakydetector.utils.logger
   :members:
```
