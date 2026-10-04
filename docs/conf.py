project = "FlakyDetector"
author = "Artem Alimpiev"
release = version = "0.2.0"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon", "myst_parser"]
html_theme = "furo"
source_suffix = {".md": "markdown", ".txt": "markdown"}
exclude_patterns = ["_build", "VALIDATION.json"]
autodoc_member_order = "bysource"
