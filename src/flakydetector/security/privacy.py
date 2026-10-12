"""Source-minimizing projections. Redaction is best-effort, never an access boundary."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import PurePosixPath

# Hooks run before every source-bearing serialization, including error responses.
_PRIVATE_KEY = re.compile(
    "-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S
)
_ASSIGNMENT = re.compile(
    '(?ix)([\\w"\']*(?:password|passwd|secret|token|api[_-]?key|credential|private[_-]?key)[\\w"\']*\\s*[:=]\\s*)(""".*?"""|\\x27\\x27\\x27.*?\\x27\\x27\\x27|"[^"\\n]*"|\\x27[^\\x27\\n]*\\x27|[^\\s,;#}\\]]+)',
    re.S,
)
_BEARER = re.compile("(?i)\\bBearer\\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile("(https?://)[^\\s/@]+:[^\\s/@]+@", re.I)
_KNOWN_TOKEN = re.compile(
    "\\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\\b",
)


def _mask(match: re.Match[str]) -> str:
    # Preserve line numbering for source navigation, but not secret bytes.
    return "[REDACTED]" + "\n" * match.group(0).count("\n")


def _redactor_result_text(value: object) -> str:
    """A third-party redactor must really return text, not just annotate it."""
    if not isinstance(value, str):
        raise TypeError("Invalid redactor output")
    return value


def redact(value: str, hooks: tuple[Callable[[str], str], ...] = ()) -> str:
    value = _PRIVATE_KEY.sub(_mask, value)
    value = _ASSIGNMENT.sub(
        lambda m: m.group(1) + '"[REDACTED]"' + "\n" * m.group(2).count("\n"), value
    )
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _URL_CREDENTIALS.sub("\\1[REDACTED]@", value)
    value = _KNOWN_TOKEN.sub("[REDACTED]", value)
    for hook in hooks:
        try:
            replacement = _redactor_result_text(hook(value))
            value = replacement
        except Exception:
            raise ValueError("Privacy hook failed; output withheld") from None
    return value


def safe_path(value: str, *, max_depth: int = 24, max_length: int = 512) -> str:
    """Require a relative, canonical repository path. No filesystem lookup."""
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(c in value for c in ("\x00", "\r", "\n"))
        or any(part in {"..", "."} for part in value.split("/"))
        or any(":" in part for part in path.parts)
        or (len(path.parts) > max_depth)
        or (len(value) > max_length)
    ):
        raise ValueError("Invalid repository-relative path")
    if any(
        (
            part == ".env" or part.endswith(".pem") or part in {"id_rsa", "id_ed25519"}
            for part in path.parts
        ),
    ):
        raise ValueError("Sensitive files are not accepted as analysis sources")
    return path.as_posix()
