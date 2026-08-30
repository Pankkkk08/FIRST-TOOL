import os

from sweep.core.duplicates import find_duplicates


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_find_duplicates_groups_identical_content(tmp_path):
    _write(tmp_path / "a.txt", b"hello world")
    _write(tmp_path / "sub" / "b.txt", b"hello world")
    _write(tmp_path / "c.txt", b"different")

    groups = find_duplicates(str(tmp_path))

    assert len(groups) == 1
    group = groups[0]
    assert group.size == len(b"hello world")
    assert set(os.path.basename(p) for p in group.paths) == {"a.txt", "b.txt"}
    assert group.wasted_bytes == len(b"hello world")


def test_find_duplicates_ignores_same_size_different_content(tmp_path):
    _write(tmp_path / "a.txt", b"AAAAAAAAAA")
    _write(tmp_path / "b.txt", b"BBBBBBBBBB")

    groups = find_duplicates(str(tmp_path))
    assert groups == []


def test_find_duplicates_handles_three_way_group_and_savings(tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        _write(tmp_path / name, b"triplet-content")
    _write(tmp_path / "unique.txt", b"solo")

    groups = find_duplicates(str(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].paths) == 3
    assert groups[0].wasted_bytes == len(b"triplet-content") * 2


def test_find_duplicates_min_size_filters_small_files(tmp_path):
    _write(tmp_path / "a.txt", b"x")
    _write(tmp_path / "b.txt", b"x")

    groups = find_duplicates(str(tmp_path), min_size=2)
    assert groups == []

    groups = find_duplicates(str(tmp_path), min_size=1)
    assert len(groups) == 1


def test_find_duplicates_empty_directory(tmp_path):
    assert find_duplicates(str(tmp_path)) == []
