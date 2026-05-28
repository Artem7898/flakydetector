from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "FlakyDetector"
copyright = "https://orcid.org/0009-0007-6740-7242"
author = "Artem Alimpiev"
release = "v0.2.0-alpha: Fixture State Analysis (42D Feature Space)"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

myst_enable_extensions = [
    "colon_fence",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"

autodoc_member_order = "bysource"
autoclass_content = "both"
autodoc_typehints = "description"

autodoc_mock_imports = [
    "catboost",
    "numpy",
    "pandas",
    "polars",
    "sklearn",
]

