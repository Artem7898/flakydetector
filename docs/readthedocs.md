# Build and publish documentation

The documentation is Sphinx with MyST Markdown and the Furo theme. Version labels
come from `pyproject.toml`, without importing application modules or loading an ML
model. Build warnings and unresolved internal references fail the build.

## Build locally

From the repository root, with Python 3.12 or 3.13 and uv installed:

```bash
uv sync --locked --no-dev --extra docs
uv run --frozen python -m sphinx -n -W --keep-going -b html docs docs/_build/html
```

For the same requirements-file installation used on Read the Docs, use a separate
environment. This does not install the application:

```bash
RTD_VENV="$(mktemp -d)/venv"
python3.12 -m venv "$RTD_VENV"
"$RTD_VENV/bin/python" -m pip install -r docs/requirements.txt
"$RTD_VENV/bin/python" -m sphinx -n -W --keep-going -b html docs docs/_build/rtd
```

A successful local build does not prove that the hosted project's repository
integration, default branch or version settings are correct. Verify its build log
and source commit as well.

## Dependencies and reproducibility

`docs/requirements.txt` is a hashed export of the `docs` extra and core requirements
from `uv.lock`, excluding the local application package. It includes Sphinx, MyST
and Furo and their locked transitive dependencies. It does not request the ML, RAG,
LLM, API or frontend dependency groups. Read the Docs installs this export through
`python.install`; it need not run a server, download a model or execute test inputs.

After deliberately updating the project lock, regenerate the package entries:

```bash
uv export --locked --no-dev --extra docs --no-emit-project --no-annotate \
  --no-header --format requirements-txt > /tmp/flakydetector-docs-requirements.txt
```

Replace the generated package entries in `docs/requirements.txt` with that output,
preserving its comment header and `--require-hashes`. Run the documentation checks
again and commit the lock and export together. Do not hand-edit individual pins.

## Read the Docs project settings

Use the existing project for `Artem7898/flakydetector`, or add that repository once
through the Read the Docs Community dashboard. Keep these settings aligned:

| Setting | Value |
|---|---|
| Repository | `https://github.com/Artem7898/flakydetector` |
| Default branch | `main` |
| Default documentation version | `latest` |
| Configuration file | `.readthedocs.yaml` at the repository root |
| Python / OS | Python 3.12 / Ubuntu 24.04, specified in YAML |
| Sphinx configuration | `docs/conf.py` |
| Pull request builds | Enabled after configuring the GitHub integration |

Use the official GitHub integration for automatic builds. A GitHub Actions job
named `CI gate` is not a Read the Docs build: its success alone does not publish
the documentation site.

The old `master` branch and its PR #5 predate the merged 0.2.1rc1 work. Prepare
replacement documentation changes from `main`, rather than selecting the old side
of every conflict. Close that obsolete PR with a link to its replacement after the
replacement has been reviewed; do not delete branches or rewrite history to fix a
documentation build.

## Avoid the unrelated stable tag

Deleting a GitHub Release does not remove its Git tag. The previously unrelated
`v1.0.0` tag may still exist, and Read the Docs can select the highest stable tag
for its `stable` version. Check the actual identifier of `stable`; do not present
that version as this candidate's documentation. Use `latest` pointing to `main`.
Keep `latest` as the default until an intended stable version is available.
Do not delete Git tags or hosted versions as part of these documentation changes.

## Verification and diagnosis

`verify_release.py` installs the locked docs extra and builds the documentation
from the extracted final ZIP on each Python CI matrix entry. A documentation
failure therefore fails the existing `CI gate`; no branch protection is removed.

All source pages are in the root `toctree`. Historical raw build logs and the
requirements file are explicitly excluded from page parsing, not suppressed as
warnings. The logs remain unmodified in the source tree.

On a hosted failure, inspect the failing command, commit, version identifier and
YAML path in the Read the Docs build log. A pending GitHub check is not itself a
Sphinx error; merge conflicts and an inactive integration require different fixes.

## Official references

- [Read the Docs configuration reference](https://docs.readthedocs.com/platform/stable/config-file/v2.html)
- [Add a project](https://docs.readthedocs.com/platform/stable/intro/add-project.html)
- [Pull request builds](https://docs.readthedocs.com/platform/stable/guides/pull-requests.html)
- [Version selection](https://docs.readthedocs.com/platform/stable/versions.html)
- [Sphinx table of contents](https://www.sphinx-doc.org/en/master/usage/restructuredtext/directives.html#table-of-contents)
