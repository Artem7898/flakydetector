"""Cheap documentation contract checks; the real Sphinx build is a separate CI gate."""

from __future__ import annotations

import ast
import fnmatch
import re
import runpy
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def config() -> dict[str, object]:
    return runpy.run_path(str(DOCS / "conf.py"))


def docnames() -> set[str]:
    excluded = config()["exclude_patterns"]
    return {
        str(path.relative_to(DOCS).with_suffix(""))
        for path in DOCS.rglob("*")
        if path.is_file()
        and path.suffix in {".md", ".txt"}
        and not any(fnmatch.fnmatch(path.relative_to(DOCS).as_posix(), p) for p in excluded)
        and "_build" not in path.relative_to(DOCS).parts
    }


def toc_entries() -> list[str]:
    blocks = re.findall(r"```\{toctree\}\n(.*?)```", (DOCS / "index.md").read_text(), re.S)
    return [
        line.strip()
        for block in blocks
        for line in block.splitlines()
        if line.strip() and not line.startswith(":")
    ]


class DocumentationConfigTests(unittest.TestCase):
    def test_version_comes_from_project_metadata(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(config()["release"], project["version"])
        self.assertEqual(config()["version"], project["version"])

    def test_conf_does_not_import_application_or_ml(self) -> None:
        tree = ast.parse((DOCS / "conf.py").read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertEqual(imports, {"os", "pathlib", "tomllib"})

    def test_every_document_has_navigation(self) -> None:
        self.assertEqual(set(toc_entries()), docnames() - {"index"})

    def test_navigation_has_no_duplicates_or_self_reference(self) -> None:
        entries = toc_entries()
        self.assertEqual(len(entries), len(set(entries)))
        self.assertNotIn("index", entries)

    def test_log_files_and_requirements_are_not_pages(self) -> None:
        self.assertFalse(any("verification/" in name for name in docnames()))
        self.assertNotIn("requirements", docnames())
        self.assertIn("history/0.2.0/README", docnames())
        self.assertIn("architecture", docnames())
        self.assertIn("architecture_summary", docnames())

    def test_substitution_matches_metadata(self) -> None:
        settings = config()
        self.assertIn("substitution", settings["myst_enable_extensions"])
        self.assertEqual(settings["myst_substitutions"], {"release": settings["release"]})
        self.assertIn("{{ release }}", (DOCS / "index.md").read_text())

    def test_warning_policy_is_strict(self) -> None:
        settings = config()
        self.assertTrue(settings["nitpicky"])
        self.assertNotIn("suppress_warnings", settings)
        self.assertIn("fail_on_warning: true", (ROOT / ".readthedocs.yaml").read_text())

    def test_requirements_match_lock_and_have_hashes(self) -> None:
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        packages = {p["name"]: p for p in lock["package"]}
        text = (DOCS / "requirements.txt").read_text()
        self.assertIn("--require-hashes", text.splitlines())
        names = set()
        for statement in text.replace("\\\n", " ").splitlines():
            if not statement or statement.startswith(("#", "--")):
                continue
            match = re.match(r"([a-z0-9-]+)==([^ ;]+)", statement)
            self.assertIsNotNone(match, statement)
            if match is None:
                continue
            name, version = match.groups()
            names.add(name)
            self.assertIn(name, packages)
            self.assertEqual(version, packages[name]["version"])
            hashes = set(re.findall(r"--hash=(sha256:[a-f0-9]{64})", statement))
            self.assertTrue(hashes, name)
            allowed = {wheel["hash"] for wheel in packages[name].get("wheels", [])}
            sdist = packages[name].get("sdist")
            if sdist:
                allowed.add(sdist["hash"])
            self.assertTrue(hashes <= allowed, name)
        self.assertTrue({"sphinx", "myst-parser", "furo"} <= names)
        self.assertFalse({"catboost", "chromadb", "openai", "fastapi", "flakydetector"} & names)

    def test_verifier_requires_sphinx_after_docs_install(self) -> None:
        text = (ROOT / "scripts/verify_release.py").read_text()
        self.assertIn('"documentation"', text)
        self.assertIn('"sphinx"', text)
        self.assertIn('"-W"', text)
        self.assertIn('"--keep-going"', text)
        prefix = text.split('("ruff",', 1)[0]
        self.assertRegex(prefix, r'"--extra",\s*"docs"')

    def test_rtd_installs_export_not_application(self) -> None:
        text = (ROOT / ".readthedocs.yaml").read_text()
        self.assertIn("requirements: docs/requirements.txt", text)
        self.assertNotIn("path: .", text)
        self.assertIn('python: "3.12"', text)


if __name__ == "__main__":
    unittest.main()
