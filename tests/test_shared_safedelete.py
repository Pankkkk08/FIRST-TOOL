import os

from shared.safedelete import quarantine_paths, restore_batch, empty_quarantine


def _write(path, content=b"data"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_quarantine_moves_files_and_removes_originals(tmp_path):
    src = tmp_path / "victim.txt"
    _write(src, b"delete me")
    qroot = tmp_path / "trash"

    result = quarantine_paths([str(src)], quarantine_root=str(qroot))

    assert not src.exists()
    assert len(result.moved) == 1
    assert result.failed == []
    quarantined_path = result.moved[0][1]
    assert os.path.isfile(quarantined_path)
    with open(quarantined_path, "rb") as f:
        assert f.read() == b"delete me"


def test_quarantine_then_restore_roundtrip(tmp_path):
    src = tmp_path / "sub" / "victim.txt"
    _write(src, b"bring me back")
    qroot = tmp_path / "trash"

    result = quarantine_paths([str(src)], quarantine_root=str(qroot))
    assert not src.exists()

    restored = restore_batch(result.batch_dir)

    assert len(restored) == 1
    assert src.exists()
    with open(src, "rb") as f:
        assert f.read() == b"bring me back"


def test_quarantine_missing_file_reports_failure(tmp_path):
    qroot = tmp_path / "trash"
    result = quarantine_paths([str(tmp_path / "does_not_exist.txt")], quarantine_root=str(qroot))
    assert result.moved == []
    assert len(result.failed) == 1


def test_empty_quarantine_removes_batches(tmp_path):
    src = tmp_path / "victim.txt"
    _write(src)
    qroot = tmp_path / "trash"
    quarantine_paths([str(src)], quarantine_root=str(qroot))

    removed = empty_quarantine(quarantine_root=str(qroot))

    assert removed == 1
    assert list(os.walk(qroot)) == [(str(qroot), [], [])] or not os.listdir(qroot)
