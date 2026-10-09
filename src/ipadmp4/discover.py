"""Decide which files to convert from the command-line arguments."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

# Picked up when scanning a directory. .mp4/.m4v are deliberately absent:
# they already are MP4, and a re-run must not pick up its own output.
VIDEO_EXTENSIONS = frozenset(
    {
        ".3gp", ".asf", ".avi", ".divx", ".flv", ".m2ts", ".mkv", ".mov",
        ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".vob", ".webm", ".wmv",
    }
)  # fmt: skip


def normalize_extension(ext: str) -> str:
    ext = ext.strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


def collect(
    paths: Iterable[Path], *, recursive: bool, extensions: frozenset[str] | None
) -> tuple[list[Path], list[str]]:
    """Return the files to convert plus an error message per bad argument.

    - A file named explicitly is taken whatever its extension, unless
      `extensions` (from -e) is given -- then it must match too.
    - A directory requires `recursive`; it is scanned for `extensions`, or
      for all known video extensions by default. Hidden files and folders
      (including macOS "._" resource-fork files) are skipped.
    """
    files: list[Path] = []
    errors: list[str] = []
    seen: set[Path] = set()

    def add(src: Path) -> None:
        key = src.resolve()
        if key not in seen:
            seen.add(key)
            files.append(src)

    for path in paths:
        if path.is_dir():
            if not recursive:
                errors.append(f"{path}: is a directory (use -r to convert the videos in it)")
                continue
            wanted = extensions if extensions is not None else VIDEO_EXTENSIONS
            for src in _scan(path, wanted):
                add(src)
        elif path.is_file():
            if extensions is not None and path.suffix.lower() not in extensions:
                continue
            add(path)
        else:
            errors.append(f"{path}: no such file or directory")
    return files, errors


def _scan(root: Path, extensions: frozenset[str]) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if Path(name).suffix.lower() in extensions:
                found.append(Path(dirpath) / name)
    return found
