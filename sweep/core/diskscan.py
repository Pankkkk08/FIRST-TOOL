"""Recursive directory size scanning and squarified-treemap layout.

Pure logic, no GUI dependency, so it's directly unit-testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


@dataclass
class Node:
    """One file or directory in a scanned tree."""

    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    children: list["Node"] = field(default_factory=list)

    def sorted_children(self) -> list["Node"]:
        return sorted(self.children, key=lambda n: n.size, reverse=True)


def scan_directory(
    root_path: str,
    max_depth: Optional[int] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Node:
    """Build a size tree rooted at `root_path`.

    - Symlinks are not followed (avoids double-counting and cycles).
    - Unreadable files/directories are skipped rather than raising.
    - `max_depth=None` scans fully; `0` returns just the root with its
      total size but no children materialized.
    - `should_stop` is polled periodically so a caller (e.g. a GUI thread)
      can cancel a long scan cooperatively.
    """
    root_path = os.path.abspath(root_path)
    name = os.path.basename(root_path.rstrip(os.sep)) or root_path
    root = Node(name=name, path=root_path, is_dir=True)
    _scan_into(root, depth=0, max_depth=max_depth, should_stop=should_stop)
    return root


def _scan_into(node: Node, depth: int, max_depth: Optional[int], should_stop) -> None:
    if should_stop is not None and should_stop():
        return
    try:
        entries = list(os.scandir(node.path))
    except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
        return

    total = 0
    keep_children = max_depth is None or depth < max_depth
    for entry in entries:
        if should_stop is not None and should_stop():
            return
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                child = Node(name=entry.name, path=entry.path, is_dir=True)
                _scan_into(child, depth + 1, max_depth, should_stop)
                total += child.size
                if keep_children:
                    node.children.append(child)
            else:
                st = entry.stat(follow_symlinks=False)
                total += st.st_size
                if keep_children:
                    node.children.append(
                        Node(name=entry.name, path=entry.path, size=st.st_size, is_dir=False)
                    )
        except (PermissionError, FileNotFoundError, OSError):
            continue
    node.size = total


# ---------------------------------------------------------------------------
# Squarified treemap layout (Bruls, Huizing, van Wijk, 2000)
# ---------------------------------------------------------------------------


@dataclass
class Rect:
    node: Node
    x: float
    y: float
    w: float
    h: float


def squarified_treemap(nodes: Iterable[Node], x: float, y: float, w: float, h: float) -> list[Rect]:
    """Lay out `nodes` (already sorted, ideally descending by size) into
    rectangles filling the (x, y, w, h) box, minimizing aspect ratio.
    """
    items = [n for n in nodes if n.size > 0]
    if not items or w <= 0 or h <= 0:
        return []

    total = sum(n.size for n in items)
    if total <= 0:
        return []

    # Scale sizes to the available area so the algorithm works in area units.
    scale = (w * h) / total
    areas = [n.size * scale for n in items]

    result: list[Rect] = []
    remaining = list(zip(items, areas))
    rx, ry, rw, rh = x, y, w, h

    while remaining:
        side = min(rw, rh)
        row: list[tuple[Node, float]] = []
        row_worst = float("inf")
        i = 0
        while i < len(remaining):
            candidate_row = row + [remaining[i]]
            worst = _worst_aspect(candidate_row, side)
            if worst <= row_worst:
                row = candidate_row
                row_worst = worst
                i += 1
            else:
                break

        row_area = sum(a for _, a in row)
        row_len = row_area / side if side > 0 else 0

        placed = 0.0
        if rw >= rh:
            # Lay the row out vertically along the left edge.
            for n, a in row:
                seg = a / row_len if row_len > 0 else 0
                result.append(Rect(n, rx, ry + placed, row_len, seg))
                placed += seg
            rx += row_len
            rw -= row_len
        else:
            # Lay the row out horizontally along the top edge.
            for n, a in row:
                seg = a / row_len if row_len > 0 else 0
                result.append(Rect(n, rx + placed, ry, seg, row_len))
                placed += seg
            ry += row_len
            rh -= row_len

        remaining = remaining[len(row):]

    return result


def _worst_aspect(row: list[tuple[Node, float]], side: float) -> float:
    if not row or side <= 0:
        return float("inf")
    areas = [a for _, a in row]
    total = sum(areas)
    if total <= 0:
        return float("inf")
    row_len = total / side
    if row_len <= 0:
        return float("inf")
    worst = 0.0
    for a in areas:
        seg = a / row_len
        if seg <= 0:
            continue
        ratio = max(row_len / seg, seg / row_len)
        worst = max(worst, ratio)
    return worst
