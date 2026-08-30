"""Shared helpers used across the core scanning modules."""

from __future__ import annotations

import os

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(num_bytes: float) -> str:
    """Format a byte count as a short human-readable string, e.g. '3.4 MB'."""
    if num_bytes < 0:
        return f"-{human_size(-num_bytes)}"
    size = float(num_bytes)
    for unit in _UNITS:
        if size < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"  # pragma: no cover - unreachable, defensive only


def iter_dir_entries(path):
    """Yield os.DirEntry objects for a directory, skipping unreadable ones.

    Never raises for permission errors or races (a file disappearing between
    listing and stat) — those are simply skipped, since this tool is a
    best-effort local scanner, not a source of truth about the filesystem.
    """
    try:
        with os.scandir(path) as it:
            yield from it
    except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
        return
