"""Sphinx configuration shared by Read the Docs and artifact verification."""

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "pyproject.toml").open("rb") as project_file:
    metadata = tomllib.load(project_file)

project = "FlakyDetector"
author = "Artem Alimpiev"
copyright = "2026, Artem Alimpiev"
release = version = metadata["project"]["version"]
if not isinstance(release, str):
    raise TypeError("project.version must be a string")

extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon", "myst_parser"]
root_doc = "index"
language = "en"
source_suffix = {".md": "markdown", ".txt": "markdown"}
# Keep the architecture .txt documents. Raw historical build logs are evidence,
# not Markdown pages; do not parse them or rewrite their archived contents.
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "requirements.txt",
    "history/**/verification/**",
    "**/VALIDATION.json",
]
myst_enable_extensions = ["colon_fence", "substitution"]
myst_substitutions = {"release": release}
# Unresolved internal references remain failures in both hosted and local builds.
nitpicky = True
autodoc_member_order = "bysource"
html_theme = "furo"
html_title = f"{project} {release}"
html_baseurl = os.environ.get("READTHEDOCS_CANONICAL_URL", "")
