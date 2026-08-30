import os
import time

from desktop_utility.core.largefiles import find_largest_files, find_oldest_files


def _write(path, size, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_find_largest_files_orders_descending(tmp_path):
    _write(tmp_path / "small.bin", 10)
    _write(tmp_path / "medium.bin", 100)
    _write(tmp_path / "big.bin", 1000)

    result = find_largest_files(str(tmp_path), top_n=10)

    sizes = [r.size for r in result]
    assert sizes == sorted(sizes, reverse=True)
    assert [os.path.basename(r.path) for r in result] == ["big.bin", "medium.bin", "small.bin"]


def test_find_largest_files_respects_top_n_bound(tmp_path):
    for i in range(20):
        _write(tmp_path / f"f{i}.bin", i + 1)

    result = find_largest_files(str(tmp_path), top_n=5)

    assert len(result) == 5
    assert [r.size for r in result] == [20, 19, 18, 17, 16]


def test_find_largest_files_min_size_filter(tmp_path):
    _write(tmp_path / "a.bin", 5)
    _write(tmp_path / "b.bin", 50)

    result = find_largest_files(str(tmp_path), top_n=10, min_size=10)
    assert len(result) == 1
    assert os.path.basename(result[0].path) == "b.bin"


def test_find_oldest_files_orders_ascending_by_mtime(tmp_path):
    now = time.time()
    _write(tmp_path / "newest.bin", 1, mtime=now - 10)
    _write(tmp_path / "middle.bin", 1, mtime=now - 1000)
    _write(tmp_path / "oldest.bin", 1, mtime=now - 100000)

    result = find_oldest_files(str(tmp_path), top_n=10)

    assert [os.path.basename(r.path) for r in result] == ["oldest.bin", "middle.bin", "newest.bin"]


def test_find_oldest_files_respects_top_n_bound(tmp_path):
    now = time.time()
    for i in range(20):
        _write(tmp_path / f"f{i}.bin", 1, mtime=now - i * 1000)

    result = find_oldest_files(str(tmp_path), top_n=5)

    assert len(result) == 5
    # The 5 oldest are the ones with the largest i (i=15..19), oldest first.
    assert [os.path.basename(r.path) for r in result] == [
        "f19.bin",
        "f18.bin",
        "f17.bin",
        "f16.bin",
        "f15.bin",
    ]


def test_find_oldest_files_min_age_days_filter(tmp_path):
    now = time.time()
    _write(tmp_path / "recent.bin", 1, mtime=now - 10)
    _write(tmp_path / "old.bin", 1, mtime=now - 400 * 86400)

    result = find_oldest_files(str(tmp_path), top_n=10, min_age_days=100)

    assert len(result) == 1
    assert os.path.basename(result[0].path) == "old.bin"
