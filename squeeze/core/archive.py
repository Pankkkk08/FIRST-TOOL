"""Generic file/folder compression: bundle into a zip/tar.gz/tar.xz
archive, or gzip each file individually in place.

Stdlib only (zipfile, tarfile, gzip) — no external archiver dependency.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from squeeze.core.common import CompressResult

ARCHIVE_FORMATS = {
    "ZIP (.zip)": "zip",
    "Tar + gzip (.tar.gz)": "targz",
    "Tar + xz — smaller, slower (.tar.xz)": "tarxz",
}


def default_archive_extension(fmt: str) -> str:
    return {"zip": ".zip", "targz": ".tar.gz", "tarxz": ".tar.xz"}[fmt]


def _iter_files(paths: list[str]) -> list[tuple[str, str]]:
    """Expand a mix of files/folders into (absolute_path, arcname) pairs.

    `arcname` is the path stored inside the archive: for a bare file it's
    just the file's own name; for a folder it's `<folder_name>/<relative
    path>` so extracting the archive recreates the folder structure
    without leaking the full source path from the source machine.
    """
    entries: list[tuple[str, str]] = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            base_name = os.path.basename(p.rstrip(os.sep))
            for dirpath, _dirnames, filenames in os.walk(p, onerror=lambda e: None):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, p)
                    entries.append((full, os.path.join(base_name, rel)))
        elif os.path.isfile(p):
            entries.append((p, os.path.basename(p)))
    return entries


def create_archive(
    paths: list[str],
    output_path: str,
    fmt: str = "zip",
    compression_level: int = 6,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> CompressResult:
    """Bundle `paths` (files and/or folders) into a single archive.

    `on_progress(done_count, total_count, current_name)` is called after
    each entry is written.
    """
    entries = _iter_files(paths)
    if not entries:
        return CompressResult(success=False, message="No files found to archive")

    input_size = sum(os.path.getsize(f) for f, _ in entries if os.path.isfile(f))
    total = len(entries)

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        if fmt == "zip":
            _write_zip(entries, output_path, compression_level, on_progress, should_stop)
        elif fmt == "targz":
            _write_tar(entries, output_path, "gz", compression_level, on_progress, should_stop)
        elif fmt == "tarxz":
            _write_tar(entries, output_path, "xz", compression_level, on_progress, should_stop)
        else:
            return CompressResult(success=False, message=f"Unknown archive format: {fmt}")
    except _Cancelled:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return CompressResult(success=False, message="Cancelled", input_size=input_size)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return CompressResult(success=False, message=str(exc), input_size=input_size)

    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    return CompressResult(
        success=True, message="OK", input_size=input_size, output_size=output_size
    )


class _Cancelled(Exception):
    pass


def _write_zip(entries, output_path, level, on_progress, should_stop) -> None:
    # zipfile's DEFLATE compresslevel is 0-9, matching our 0-9 UI slider directly.
    level = max(0, min(9, level))
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for i, (full, arcname) in enumerate(entries, start=1):
            if should_stop is not None and should_stop():
                raise _Cancelled()
            try:
                zf.write(full, arcname)
            except OSError:
                continue  # file vanished / unreadable mid-scan; skip it, don't abort the batch
            if on_progress is not None:
                on_progress(i, len(entries), arcname)


def _write_tar(entries, output_path, tar_mode, level, on_progress, should_stop) -> None:
    # tarfile's gzip path takes compresslevel 0-9. Its xz (lzma) path takes
    # preset 0-9 too, so the same 0-9 UI slider works for both.
    level = max(0, min(9, level))
    kwargs = {"compresslevel": level} if tar_mode == "gz" else {"preset": level}
    with tarfile.open(output_path, f"w:{tar_mode}", **kwargs) as tf:
        for i, (full, arcname) in enumerate(entries, start=1):
            if should_stop is not None and should_stop():
                raise _Cancelled()
            try:
                tf.add(full, arcname=arcname, recursive=False)
            except OSError:
                continue
            if on_progress is not None:
                on_progress(i, len(entries), arcname)


# ---------------------------------------------------------------------------
# Per-file gzip mode: compress each file individually, preserving names
# (file.log -> file.log.gz) instead of bundling everything into one archive.
# ---------------------------------------------------------------------------


@dataclass
class BatchGzipResult:
    results: list[tuple[str, CompressResult]] = field(default_factory=list)

    @property
    def total_input(self) -> int:
        return sum(r.input_size for _p, r in self.results)

    @property
    def total_output(self) -> int:
        return sum(r.output_size for _p, r in self.results if r.success)


def gzip_files_individually(
    paths: list[str],
    output_dir: Optional[str] = None,
    compression_level: int = 6,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> BatchGzipResult:
    entries = _iter_files(paths)
    batch = BatchGzipResult()
    level = max(1, min(9, compression_level))

    for i, (full, arcname) in enumerate(entries, start=1):
        if should_stop is not None and should_stop():
            break
        dest_dir = output_dir or os.path.dirname(full)
        dest = os.path.join(dest_dir, os.path.basename(full) + ".gz")
        try:
            input_size = os.path.getsize(full)
            os.makedirs(dest_dir, exist_ok=True)
            with open(full, "rb") as src_f, gzip.open(dest, "wb", compresslevel=level) as dst_f:
                shutil.copyfileobj(src_f, dst_f)
            output_size = os.path.getsize(dest)
            batch.results.append(
                (full, CompressResult(success=True, message="OK", input_size=input_size, output_size=output_size))
            )
        except OSError as exc:
            batch.results.append((full, CompressResult(success=False, message=str(exc))))
        if on_progress is not None:
            on_progress(i, len(entries), arcname)

    return batch
