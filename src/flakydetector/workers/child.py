"""Private bounded worker protocol; never imports submitted tests or plugins."""

from __future__ import annotations

import ctypes
import json
import resource
import sys


def main() -> None:
    raw = sys.stdin.buffer.read(65000001)
    if len(raw) > 65000000:
        raise SystemExit(2)
    payload = json.loads(raw)
    limits = payload["limits"]
    resource.setrlimit(resource.RLIMIT_CPU, (int(limits["cpu"]), int(limits["cpu"]) + 1))
    resource.setrlimit(resource.RLIMIT_AS, (int(limits["memory"]), int(limits["memory"])))
    resource.setrlimit(resource.RLIMIT_FSIZE, (int(limits["output"]), int(limits["output"])))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # PR_SET_NO_NEW_PRIVS. Does not claim seccomp/network/filesystem isolation.
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise SystemExit(2)
    from flakydetector.application import AnalyzeService
    from flakydetector.models.domain import AnalysisDiagnostic
    from flakydetector.utils.config import Settings

    settings = Settings(
        **{
            key: payload[key]
            for key in (
                "max_file_bytes",
                "max_ast_nodes",
                "max_archive_bytes",
                "max_files",
                "max_unpacked_bytes",
                "max_entries",
                "max_compression_ratio",
                "max_path_depth",
                "max_path_length",
            )
        },
    )
    service = AnalyzeService(settings)
    if payload.get("use_ml") and payload.get("model_path"):
        from pathlib import Path

        from flakydetector.classifier.catboost_model import FlakyClassifier, ModelUnavailable

        try:
            model = FlakyClassifier()
            model.load_model(Path(payload["model_path"]))
            service.classifier = model
            service.model_version = model.manifest.model_version if model.manifest else None
        except ModelUnavailable:
            service.degraded_reason = "Configured model is unavailable or incompatible"
    if payload.get("operation") != "analyze":
        raise SystemExit(2)
    if "archive_b64" in payload:
        import base64

        from flakydetector.input import zip_bundle

        bundle = zip_bundle(base64.b64decode(payload["archive_b64"], validate=True), settings)
        payload["sources"] = bundle.sources
        payload["diagnostics"] = [d.model_dump(mode="json") for d in bundle.diagnostics]
    result = service.analyze(
        payload["sources"],
        log_content=payload.get("log", ""),
        use_ml=bool(payload.get("use_ml")),
        diagnostics=tuple(
            AnalysisDiagnostic.model_validate(d) for d in payload.get("diagnostics", [])
        ),
    )
    sys.stdout.write(result.model_dump_json())


if __name__ == "__main__":
    main()
