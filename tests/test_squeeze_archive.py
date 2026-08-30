import os
import tarfile
import zipfile

from squeeze.core.archive import (
    create_archive,
    default_archive_extension,
    gzip_files_individually,
)


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_default_archive_extension():
    assert default_archive_extension("zip") == ".zip"
    assert default_archive_extension("targz") == ".tar.gz"
    assert default_archive_extension("tarxz") == ".tar.xz"


def test_create_zip_archive_from_files(tmp_path):
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")
    _write(a, b"hello " * 1000)
    _write(b, b"world " * 1000)
    out = str(tmp_path / "bundle.zip")

    result = create_archive([a, b], out, fmt="zip")

    assert result.success, result.message
    assert os.path.isfile(out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"a.txt", "b.txt"}


def test_create_zip_archive_from_folder_preserves_structure(tmp_path):
    root = tmp_path / "project"
    _write(str(root / "readme.txt"), b"docs")
    _write(str(root / "src" / "main.py"), b"print(1)")
    out = str(tmp_path / "bundle.zip")

    result = create_archive([str(root)], out, fmt="zip")

    assert result.success, result.message
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {
        os.path.join("project", "readme.txt"),
        os.path.join("project", "src", "main.py"),
    }


def test_create_targz_archive(tmp_path):
    a = str(tmp_path / "a.bin")
    _write(a, b"x" * 5000)
    out = str(tmp_path / "bundle.tar.gz")

    result = create_archive([a], out, fmt="targz")

    assert result.success, result.message
    with tarfile.open(out, "r:gz") as tf:
        assert tf.getnames() == ["a.bin"]


def test_create_tarxz_archive(tmp_path):
    a = str(tmp_path / "a.bin")
    _write(a, b"y" * 5000)
    out = str(tmp_path / "bundle.tar.xz")

    result = create_archive([a], out, fmt="tarxz")

    assert result.success, result.message
    with tarfile.open(out, "r:xz") as tf:
        assert tf.getnames() == ["a.bin"]


def test_create_archive_higher_compression_shrinks_more(tmp_path):
    a = str(tmp_path / "a.txt")
    # Highly compressible, repetitive content so compression level matters.
    _write(a, (b"the quick brown fox jumps over the lazy dog " * 5000))

    low = str(tmp_path / "low.zip")
    high = str(tmp_path / "high.zip")
    r_low = create_archive([a], low, fmt="zip", compression_level=1)
    r_high = create_archive([a], high, fmt="zip", compression_level=9)

    assert r_low.success and r_high.success
    assert r_high.output_size <= r_low.output_size


def test_create_archive_empty_input_reports_error(tmp_path):
    result = create_archive([], str(tmp_path / "out.zip"), fmt="zip")
    assert not result.success


def test_create_archive_cancellation_removes_partial_output(tmp_path):
    files = []
    for i in range(20):
        p = str(tmp_path / f"f{i}.bin")
        _write(p, b"z" * 10000)
        files.append(p)
    out = str(tmp_path / "bundle.zip")

    result = create_archive([*files], out, fmt="zip", should_stop=lambda: True)

    assert not result.success
    assert result.message == "Cancelled"
    assert not os.path.isfile(out)


def test_create_archive_progress_callback_fires_per_entry(tmp_path):
    files = []
    for i in range(5):
        p = str(tmp_path / f"f{i}.bin")
        _write(p, b"z" * 100)
        files.append(p)
    out = str(tmp_path / "bundle.zip")
    calls = []

    create_archive(files, out, fmt="zip", on_progress=lambda done, total, name: calls.append((done, total, name)))

    assert len(calls) == 5
    assert calls[-1][0] == 5 and calls[-1][1] == 5


def test_gzip_files_individually(tmp_path):
    a = str(tmp_path / "a.log")
    b = str(tmp_path / "b.log")
    _write(a, b"log line\n" * 500)
    _write(b, b"another log line\n" * 500)

    batch = gzip_files_individually([a, b])

    assert len(batch.results) == 2
    assert all(r.success for _p, r in batch.results)
    assert os.path.isfile(a + ".gz")
    assert os.path.isfile(b + ".gz")
    assert batch.total_output < batch.total_input


def test_gzip_files_individually_custom_output_dir(tmp_path):
    a = str(tmp_path / "sub" / "a.log")
    _write(a, b"content " * 200)
    out_dir = str(tmp_path / "gz_out")

    batch = gzip_files_individually([a], output_dir=out_dir)

    assert batch.results[0][1].success
    assert os.path.isfile(os.path.join(out_dir, "a.log.gz"))
