"""Install the built wheel in an independent environment and exercise its real entrypoints."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    wheels = sorted((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one built wheel in dist/")
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required for independent wheel verification")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    with tempfile.TemporaryDirectory(prefix="flaky-installed-wheel-") as folder:
        temporary = Path(folder)
        environment = temporary / ".venv"
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirements = temporary / "requirements.txt"
        commands = [
            [uv, "venv", str(environment), "--python", sys.executable],
            [uv, "export", "--frozen", "--extra", "api", "--extra", "pytest", "--no-emit-project", "--output-file", str(requirements)],
            [uv, "pip", "sync", "--python", str(python), str(requirements)],
            [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])],
        ]
        for command in commands:
            subprocess.run(command, cwd=root, env=env, check=True, timeout=600)
        smoke = temporary / "wheel_smoke.py"
        shutil.copyfile(root / "scripts/wheel_smoke.py", smoke)
        subprocess.run([str(python), str(smoke)], cwd=temporary, env=env, check=True, timeout=120)


if __name__ == "__main__":
    main()
