"""Duplicate file detection.

Cheap-first strategy: group by size (a mismatch already rules out a
duplicate), then only hash files inside a size group that has more than
one member. Hashing is chunked so large files don't get loaded into memory
whole.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

_CHUNK = 1024 * 1024  # 1 MiB


@dataclass
class DuplicateGroup:
    digest: str
    size: int
    paths: list[str]

    @property
    def wasted_bytes(self) -> int:
        """Space reclaimable by keeping just one copy."""
        return self.size * (len(self.paths) - 1)


def _hash_file(path: str) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except (PermissionError, FileNotFoundError, OSError):
        return None
    return h.hexdigest()


def find_duplicates(
    root_path: str,
    min_size: int = 1,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[DuplicateGroup]:
    """Walk `root_path` and return groups of byte-identical files.

    `min_size` filters out tiny files (defaults to skipping only empty
    files) since hashing thousands of zero-byte files wastes time for no
    useful savings.
    """
    by_size: dict[int, list[str]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda e: None):
        if should_stop is not None and should_stop():
            return []
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                if os.path.islink(full):
                    continue
                size = os.path.getsize(full)
            except OSError:
                continue
            if size >= min_size:
                by_size[size].append(full)

    groups: list[DuplicateGroup] = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        if should_stop is not None and should_stop():
            return groups
        by_hash: dict[str, list[str]] = defaultdict(list)
        for p in paths:
            digest = _hash_file(p)
            if digest is not None:
                by_hash[digest].append(p)
        for digest, group_paths in by_hash.items():
            if len(group_paths) >= 2:
                groups.append(DuplicateGroup(digest=digest, size=size, paths=sorted(group_paths)))

    groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return groups
