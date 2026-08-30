import os

import pytest

from desktop_utility.core.diskscan import scan_directory, squarified_treemap
from desktop_utility.core.common import human_size


def _write(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)


def test_scan_directory_aggregates_sizes(tmp_path):
    _write(tmp_path / "a.txt", 10)
    _write(tmp_path / "sub" / "b.txt", 20)
    _write(tmp_path / "sub" / "c.txt", 5)
    _write(tmp_path / "sub" / "deeper" / "d.txt", 7)

    root = scan_directory(str(tmp_path))

    assert root.size == 42
    assert root.is_dir
    by_name = {c.name: c for c in root.children}
    assert by_name["a.txt"].size == 10
    assert by_name["sub"].size == 32

    sub = by_name["sub"]
    sub_by_name = {c.name: c for c in sub.children}
    assert sub_by_name["deeper"].size == 7


def test_scan_directory_skips_unreadable(tmp_path):
    _write(tmp_path / "ok.txt", 3)
    locked = tmp_path / "locked"
    locked.mkdir()
    _write(locked / "secret.txt", 100)
    os.chmod(locked, 0o000)
    try:
        root = scan_directory(str(tmp_path))
        # Should not raise; unreadable subtree just contributes 0.
        assert root.size >= 3
    finally:
        os.chmod(locked, 0o755)


def test_scan_directory_does_not_follow_symlinks(tmp_path):
    _write(tmp_path / "real.txt", 50)
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    _write(target_dir / "inside.txt", 999)
    link = tmp_path / "link_to_target"
    try:
        os.symlink(target_dir, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")

    root = scan_directory(str(tmp_path))
    # real.txt (50) + the real target/ dir (999) = 1049. If the symlink were
    # followed, target's contents would be double-counted to 2048 instead.
    assert root.size == 50 + 999


def test_empty_directory_scan(tmp_path):
    root = scan_directory(str(tmp_path))
    assert root.size == 0
    assert root.children == []


def test_human_size_formatting():
    assert human_size(0) == "0 B"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1024 * 1024 * 3) == "3.0 MB"


def test_squarified_treemap_covers_area_and_no_overlap_slack(tmp_path):
    _write(tmp_path / "a.txt", 100)
    _write(tmp_path / "b.txt", 300)
    _write(tmp_path / "c.txt", 600)
    root = scan_directory(str(tmp_path))

    rects = squarified_treemap(root.sorted_children(), 0, 0, 200, 100)

    assert len(rects) == 3
    total_area = sum(r.w * r.h for r in rects)
    assert total_area == pytest.approx(200 * 100, rel=1e-6)
    for r in rects:
        assert r.w > 0 and r.h > 0
        assert r.x >= -1e-6 and r.y >= -1e-6
        assert r.x + r.w <= 200 + 1e-6
        assert r.y + r.h <= 100 + 1e-6


def test_squarified_treemap_handles_empty_and_zero_box():
    assert squarified_treemap([], 0, 0, 100, 100) == []

    from desktop_utility.core.diskscan import Node

    nodes = [Node(name="a", path="/a", size=10)]
    assert squarified_treemap(nodes, 0, 0, 0, 0) == []
