"""Compatibility entry point; install the package before invoking this script."""

from flakydetector.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
