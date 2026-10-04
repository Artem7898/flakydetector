"""Transport input: bounded reads; ZIP entries are never extracted onto the filesystem."""

from __future__ import annotations

import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from flakydetector.analyzer.ast_analyzer import EXCLUDE
from flakydetector.models.domain import AnalysisDiagnostic
from flakydetector.utils.config import Settings


class InputError(ValueError):
    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.too_large = too_large


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBundle:
    sources: dict[str, str]
    diagnostics: tuple[AnalysisDiagnostic, ...] = ()


def selected(path: PurePosixPath) -> bool:
    return (
        path.suffix == ".py"
        and (
            path.name == "conftest.py"
            or path.name.startswith("test_")
            or path.name.endswith("_test.py")
        )
        and not any(part in EXCLUDE for part in path.parts)
    )


def decode(data: bytes, path: str, limit: int) -> str:
    if len(data) > limit:
        raise InputError(f"{path}: file byte limit exceeded", too_large=True)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"{path}: invalid UTF-8") from exc


def directory_bundle(root: Path, settings: Settings) -> SourceBundle:
    if not root.is_dir():
        raise InputError(f"Not a directory: {root}")
    sources: dict[str, str] = {}
    diagnostics: list[AnalysisDiagnostic] = []
    total = 0
    paths: list[Path] = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if d not in EXCLUDE and not (Path(directory) / d).is_symlink()
        )
        paths.extend(Path(directory) / f for f in sorted(files) if selected(PurePosixPath(f)))
        if len(paths) > settings.max_files:
            raise InputError("File count limit exceeded", too_large=True)
    for path in paths:
        name = path.relative_to(root).as_posix()
        if not selected(PurePosixPath(name)):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            diagnostics.append(
                AnalysisDiagnostic(
                    code="symlink_skipped", message="Symlink source not analyzed", file_path=name
                )
            )
            continue
        if len(sources) >= settings.max_files:
            raise InputError("File count limit exceeded", too_large=True)
        try:
            with path.open("rb") as stream:
                data = stream.read(settings.max_file_bytes + 1)
            total += len(data)
            if total > settings.max_unpacked_bytes:
                raise InputError("Total source byte limit exceeded", too_large=True)
            sources[name] = decode(data, name, settings.max_file_bytes)
        except (OSError, InputError) as exc:
            diagnostics.append(
                AnalysisDiagnostic(code="read_error", message=str(exc), file_path=name)
            )
    return SourceBundle(sources=sources, diagnostics=tuple(diagnostics))


def zip_bundle(data: bytes, settings: Settings) -> SourceBundle:
    if len(data) > settings.max_archive_bytes:
        raise InputError("Archive byte limit exceeded", too_large=True)
    sources: dict[str, str] = {}
    diagnostics: list[AnalysisDiagnostic] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [i for i in archive.infolist() if not i.is_dir()]
            if (
                len(members) > settings.max_files
                or sum(i.file_size for i in members) > settings.max_unpacked_bytes
            ):
                raise InputError("Archive expansion/file count limit exceeded", too_large=True)
            names: set[str] = set()
            for info in members:
                path = PurePosixPath(info.filename.replace("\\", "/"))
                if (
                    not path.parts
                    or path.is_absolute()
                    or ".." in path.parts
                    or ":" in path.parts[0]
                    or stat.S_ISLNK(info.external_attr >> 16)
                ):
                    raise InputError("Unsafe archive member path/type")
                name = str(path)
                if name in names:
                    raise InputError("Duplicate archive member")
                names.add(name)
                if info.flag_bits & 1 or info.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise InputError("Unsupported archive encryption/compression")
                if info.file_size / max(1, info.compress_size) > settings.max_compression_ratio:
                    raise InputError("Compression ratio limit exceeded", too_large=True)
                if not selected(path):
                    continue
                if info.file_size > settings.max_file_bytes:
                    raise InputError("Archive member byte limit exceeded", too_large=True)
                with archive.open(info) as stream:
                    raw = stream.read(settings.max_file_bytes + 1)
                try:
                    sources[name] = decode(raw, name, settings.max_file_bytes)
                except InputError as exc:
                    diagnostics.append(
                        AnalysisDiagnostic(code="encoding_error", message=str(exc), file_path=name)
                    )
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError) as exc:
        raise InputError("Invalid or unsupported ZIP archive") from exc
    return SourceBundle(sources=sources, diagnostics=tuple(diagnostics))
