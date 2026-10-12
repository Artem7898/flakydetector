"""One killable OS process per analysis; bounded admission, CPU/RAM/wall/output.

This is a resource/process boundary, NOT a hostile multi-tenant filesystem sandbox.
Run each trust domain in a separately restricted container/user and network namespace.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import JsonValue, TypeAdapter

from flakydetector.utils.config import Settings


class WorkerFailure(RuntimeError):
    pass


class WorkerTimeout(WorkerFailure):
    pass


class WorkerBusy(WorkerFailure):
    pass


class ProcessSupervisor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.active = 0
        self.pids: set[int] = set()
        self.closed = False

    async def execute(self, command: list[str], data: bytes) -> bytes:
        if self.closed or self.active >= 2:
            raise WorkerBusy("Analysis capacity exhausted")
        if sys.platform != "linux":
            raise WorkerFailure(
                "Resource-isolated API workers require Linux; use the CLI for trusted local inputs",
            )
        self.active += 1
        process: asyncio.subprocess.Process | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="fd-worker-") as temp:
                # No service token, inherited PYTHONPATH, provider keys or arbitrary environment.
                env = {
                    "PATH": os.defpath,
                    "HOME": temp,
                    "TMPDIR": temp,
                    "LANG": "C.UTF-8",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                }
                output_path = Path(temp) / "response.json"
                with output_path.open("wb") as output:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=temp,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=output,
                        stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    self.pids.add(process.pid)
                    try:
                        await asyncio.wait_for(
                            process.communicate(data),
                            timeout=self.settings.timeout_seconds,
                        )
                    except TimeoutError as exc:
                        raise WorkerTimeout(
                            "Analysis exceeded its deadline; worker terminated"
                        ) from exc
                    if process.returncode != 0:
                        raise WorkerFailure("Analysis worker exited without a valid result")
                if output_path.stat().st_size > self.settings.worker_output_bytes:
                    raise WorkerFailure("Analysis response limit exceeded")
                return output_path.read_bytes()
        finally:
            if process is not None:
                # Always kill the entire session, including descendants of a dead leader.
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                self.pids.discard(process.pid)
            self.active -= 1

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        root = str(Path(__file__).resolve().parents[2])
        bootstrap = "import sys;sys.path.insert(0,sys.argv[1]);from flakydetector.workers.child import main;main()"
        limits = {
            "cpu": self.settings.worker_cpu_seconds,
            "memory": self.settings.worker_memory_mb * 1024 * 1024,
            "output": self.settings.worker_output_bytes,
        }
        payload = {
            **payload,
            "limits": limits,
            "model_path": str(self.settings.model_path) if self.settings.model_path else None,
            "max_file_bytes": self.settings.max_file_bytes,
            "max_ast_nodes": self.settings.max_ast_nodes,
            "max_archive_bytes": self.settings.max_archive_bytes,
            "max_files": self.settings.max_files,
            "max_unpacked_bytes": self.settings.max_unpacked_bytes,
            "max_entries": self.settings.max_entries,
            "max_compression_ratio": self.settings.max_compression_ratio,
            "max_path_depth": self.settings.max_path_depth,
            "max_path_length": self.settings.max_path_length,
        }
        data = json.dumps(payload, separators=(",", ":")).encode()
        if (
            len(data)
            > self.settings.max_unpacked_bytes * 2 + self.settings.max_archive_bytes * 2 + 1000000
        ):
            raise WorkerFailure("Worker input budget exceeded")
        raw = await self.execute([sys.executable, "-I", "-c", bootstrap, root], data)
        try:
            result = TypeAdapter(dict[str, JsonValue]).validate_json(raw, strict=True)
            if result.get("_worker_error"):
                raise WorkerFailure("Worker rejected input")
            return result
        except (ValueError, UnicodeError) as exc:
            raise WorkerFailure("Invalid worker result") from exc

    async def close(self) -> None:
        self.closed = True
        for pid in tuple(self.pids):
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
