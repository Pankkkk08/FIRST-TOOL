"""Shared result type for every compression backend in this app."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompressResult:
    success: bool
    message: str
    input_size: int = 0
    output_size: int = 0

    @property
    def saved_bytes(self) -> int:
        return max(0, self.input_size - self.output_size)

    @property
    def saved_percent(self) -> float:
        if self.input_size <= 0:
            return 0.0
        return 100.0 * self.saved_bytes / self.input_size
