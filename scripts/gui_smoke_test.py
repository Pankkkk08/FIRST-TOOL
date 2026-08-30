#!/usr/bin/env python3
"""Headless smoke test: build the real Tk app, drive a disk scan through the
actual button handlers, and exercise every tab. Not a pytest test (needs a
display / Xvfb) — run manually via:

    xvfb-run -a python3 scripts/gui_smoke_test.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_utility.app import build_app  # noqa: E402


def make_sample_tree(base: str) -> None:
    for rel, size in [
        ("a.txt", 1000),
        ("dup1.txt", 500),
        ("sub/dup2.txt", 500),  # same size as dup1, different content on purpose below
        ("sub/big.bin", 20000),
        ("sub/deep/tiny.txt", 10),
    ]:
        full = os.path.join(base, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"Q" * size)
    # Make an actual duplicate pair (identical content) for the duplicates tab.
    with open(os.path.join(base, "dupA.txt"), "wb") as f:
        f.write(b"same-content-xyz" * 50)
    with open(os.path.join(base, "sub", "dupB.txt"), "wb") as f:
        f.write(b"same-content-xyz" * 50)


def pump(root, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        make_sample_tree(tmp)

        root = build_app()
        notebook = root.nametowidget(root.winfo_children()[0])
        disk_tab, dup_tab, large_tab, sysmon_tab = notebook.winfo_children()

        # --- Disk usage tab ---
        disk_tab.path_var.set(tmp)
        disk_tab._start_scan()
        pump(root, 2.0)
        assert disk_tab._root_node is not None, "disk scan never completed"
        assert disk_tab._root_node.size > 0, "disk scan found zero bytes"
        print(f"[disk]  scanned {tmp}: total size = {disk_tab._root_node.size} bytes, "
              f"{len(disk_tab._root_node.children)} top-level entries")
        # Force a treemap render at a concrete size (winfo geometry is 1x1 before pack/mainloop settles).
        disk_tab.canvas.config(width=400, height=300)
        pump(root, 0.3)
        disk_tab._render_treemap()
        print(f"[disk]  treemap drew {len(disk_tab._rect_by_id)} canvas items")

        # --- Duplicates tab ---
        dup_tab.path_var.set(tmp)
        dup_tab._start_scan()
        pump(root, 2.0)
        print(f"[dup]   found {len(dup_tab._groups)} duplicate group(s)")
        assert len(dup_tab._groups) >= 1, "expected the seeded duplicate pair to be found"

        # --- Large files tab ---
        large_tab.path_var.set(tmp)
        large_tab.min_size_var.set(0)
        large_tab._start_scan()
        pump(root, 2.0)
        print(f"[large] found {len(large_tab._results)} file(s)")
        assert len(large_tab._results) > 0

        # --- System monitor tab ---
        pump(root, 1.0)
        print(f"[sysmon] cpu label = {sysmon_tab.cpu_label.cget('text')!r}, "
              f"mem label = {sysmon_tab.mem_label.cget('text')!r}, "
              f"warning = {sysmon_tab.warning_var.get()!r}")

        root.destroy()

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
