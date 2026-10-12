"""Explicit server launcher. No implicit public bind and no inherited proxy trust."""

from __future__ import annotations

import argparse
from pathlib import Path

from flakydetector.security.auth import is_loopback
from flakydetector.utils.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--evidence-db", type=Path)
    parser.add_argument("--source-mode", choices=["disabled", "redacted"], default=None)
    args = parser.parse_args(argv)
    from dataclasses import replace

    settings = Settings.from_env()
    remote = args.host != "localhost" and (not is_loopback(args.host))
    if remote and (not args.allow_remote):
        parser.error("Remote bind requires --allow-remote and authentication")
    try:
        settings = replace(
            settings,
            profile="shared" if remote else settings.profile,
            allow_remote=args.allow_remote or settings.allow_remote,
            credentials_file=args.credentials_file or settings.credentials_file,
            evidence_db=args.evidence_db or settings.evidence_db,
            source_mode=args.source_mode or settings.source_mode,
        )
        from flakydetector.dashboard.main import create_app

        app = create_app(settings)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
