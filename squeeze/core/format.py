"""Formatting helpers shared across every local tool in this repo."""

from __future__ import annotations

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
