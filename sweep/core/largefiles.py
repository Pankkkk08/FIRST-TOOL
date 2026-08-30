"""Largest-files and oldest-files scans.

Both use a bounded heap so scanning a huge tree doesn't require holding
every file's metadata in memory just to find the top N.
"""

from __future__ import annotations

import heapq
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.mtime) / 86400)


def _walk_files(root_path: str, should_stop: Optional[Callable[[], bool]]):
    for dirpath, _dirnames, filenames in os.walk(root_path, onerror=lambda e: None):
        if should_stop is not None and should_stop():
            return
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                if os.path.islink(full):
                    continue
                st = os.stat(full)
            except OSError:
                continue
            yield FileInfo(path=full, size=st.st_size, mtime=st.st_mtime)


def find_largest_files(
    root_path: str,
    top_n: int = 50,
    min_size: int = 0,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[FileInfo]:
    """Return the `top_n` largest files under `root_path`, biggest first."""
    heap: list[tuple[int, int, FileInfo]] = []  # (size, tiebreak, info) as min-heap
    counter = 0
    for info in _walk_files(root_path, should_stop):
        if info.size < min_size:
            continue
        counter += 1
        entry = (info.size, counter, info)
        if len(heap) < top_n:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    return [info for _size, _c, info in sorted(heap, key=lambda e: e[0], reverse=True)]


def find_oldest_files(
    root_path: str,
    top_n: int = 50,
    min_age_days: float = 0,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[FileInfo]:
    """Return the `top_n` oldest (least recently modified) files, oldest first.

    Bounded max-heap on mtime, keyed by `-mtime` so heapq's native min-heap
    keeps the oldest `top_n` files seen so far: the root always holds the
    *largest* mtime currently kept (the next one to evict), mirroring
    `find_largest_files`'s min-heap-on-size approach but inverted.
    """
    cutoff = time.time() - (min_age_days * 86400)
    heap: list[tuple[float, int, FileInfo]] = []
    counter = 0
    for info in _walk_files(root_path, should_stop):
        if info.mtime > cutoff:
            continue
        counter += 1
        entry = (-info.mtime, counter, info)
        if len(heap) < top_n:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    return [info for _key, _c, info in sorted(heap, key=lambda e: e[2].mtime)]
