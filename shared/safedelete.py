"""Reversible "delete" via a local quarantine folder.

Every destructive action in the app (removing a duplicate, clearing a
large/old file) goes through here instead of `os.remove`, so a mistake is
recoverable: files are moved into a timestamped quarantine directory under
the user's home folder rather than being permanently removed. The
quarantine is plain files on disk — nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass


def default_quarantine_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".sweep_trash")


@dataclass
class QuarantineResult:
    moved: list[tuple[str, str]]  # (original_path, quarantined_path)
    failed: list[tuple[str, str]]  # (original_path, error_message)
    batch_dir: str


def quarantine_paths(paths: list[str], quarantine_root: str | None = None) -> QuarantineResult:
    """Move each path in `paths` into a fresh timestamped batch folder.

    A manifest.json is written alongside so `restore_batch` can put files
    back at their original locations later.
    """
    root = quarantine_root or default_quarantine_root()
    batch_dir = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
    os.makedirs(batch_dir, exist_ok=True)

    moved: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    manifest = []

    for i, src in enumerate(paths):
        try:
            base = os.path.basename(src.rstrip(os.sep)) or f"item-{i}"
            dest = os.path.join(batch_dir, f"{i:05d}_{base}")
            shutil.move(src, dest)
            moved.append((src, dest))
            manifest.append({"original": src, "quarantined": dest})
        except (OSError, shutil.Error) as exc:
            failed.append((src, str(exc)))

    if manifest:
        with open(os.path.join(batch_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    return QuarantineResult(moved=moved, failed=failed, batch_dir=batch_dir)


def restore_batch(batch_dir: str) -> list[tuple[str, str]]:
    """Move every file in a quarantine batch back to its original location.

    Returns the list of (quarantined_path, restored_path) pairs that
    succeeded; entries whose original location is occupied again or whose
    parent directory no longer exists are left in quarantine.
    """
    manifest_path = os.path.join(batch_dir, "manifest.json")
    restored: list[tuple[str, str]] = []
    if not os.path.isfile(manifest_path):
        return restored

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    remaining = []
    for entry in manifest:
        original, quarantined = entry["original"], entry["quarantined"]
        try:
            if os.path.exists(original) or not os.path.isdir(os.path.dirname(original)):
                remaining.append(entry)
                continue
            shutil.move(quarantined, original)
            restored.append((quarantined, original))
        except (OSError, shutil.Error):
            remaining.append(entry)

    if remaining:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2)
    else:
        try:
            os.remove(manifest_path)
            os.rmdir(batch_dir)
        except OSError:
            pass

    return restored


def empty_quarantine(quarantine_root: str | None = None) -> int:
    """Permanently delete everything in the quarantine. Returns bytes freed...

    Actually returns the number of batch folders removed (byte accounting
    isn't needed by the UI; keep this simple and honest about what it does).
    """
    root = quarantine_root or default_quarantine_root()
    if not os.path.isdir(root):
        return 0
    count = 0
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
            count += 1
    return count
