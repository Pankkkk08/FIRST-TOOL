#!/usr/bin/env python3
"""Headless smoke test for Squeeze: build the real Tk app, drive a video
compression, a photo compression, and both archive modes through the
actual widgets/threads. Run manually via:

    xvfb-run -a python3 scripts/compressor_smoke_test.py
"""

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from compressor.app import build_app  # noqa: E402
from compressor.core.ffmpeg_util import find_ffmpeg  # noqa: E402


def pump(root, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)


def wait_until(root, predicate, timeout: float, what: str) -> None:
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {what}")


def make_test_clip(path: str, duration: float = 2.0) -> None:
    cmd = [
        find_ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=15",
        "-f", "lavfi", "-i", f"sine=duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac",
        path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)


def make_test_image(path: str) -> None:
    img = Image.new("RGB", (1000, 800), (10, 20, 30))
    for x in range(0, 1000, 6):
        for y in range(0, 800, 9):
            img.putpixel((x, y), ((x * 13) % 256, (y * 7) % 256, (x + y) % 256))
    img.save(path)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        video_src = os.path.join(tmp, "clip.mp4")
        make_test_clip(video_src)
        photo_src = os.path.join(tmp, "photo.png")
        make_test_image(photo_src)
        archive_srcs = []
        for i in range(3):
            p = os.path.join(tmp, f"doc{i}.txt")
            with open(p, "w") as f:
                f.write("hello world " * 2000)
            archive_srcs.append(p)

        root = build_app()
        notebook = root.nametowidget(root.winfo_children()[0])
        video_tab, photo_tab, archive_tab = notebook.winfo_children()

        # --- Video tab ---
        video_tab._add_paths([video_src])
        video_tab.crf_var.set(35)
        video_tab.preset_var.set("ultrafast")
        video_tab._start()
        wait_until(root, lambda: video_tab.tree.set(video_src, "status") in ("Done", "Failed"),
                   timeout=20, what="video compression to finish")
        status = video_tab.tree.set(video_src, "status")
        print(f"[video]  status={status!r} saved={video_tab.tree.set(video_src, 'saved')!r}")
        assert status == "Done", f"video compression failed: {video_tab.tree.set(video_src, 'progress')}"

        # --- Photo tab ---
        photo_tab._add_paths([photo_src])
        photo_tab.quality_var.set(50)
        photo_tab._start()
        wait_until(root, lambda: photo_tab.tree.set(photo_src, "status") in ("Done", "Failed"),
                   timeout=10, what="photo compression to finish")
        status = photo_tab.tree.set(photo_src, "status")
        print(f"[photo]  status={status!r} saved={photo_tab.tree.set(photo_src, 'saved')!r}")
        assert status == "Done"

        # --- Archive tab: bundle mode ---
        archive_tab._add_paths(list(archive_srcs))
        archive_tab.mode_var.set("bundle")
        archive_tab._start()
        wait_until(root, lambda: "Created" in archive_tab.status_var.get() or "Failed" in archive_tab.status_var.get(),
                   timeout=10, what="archive bundle to finish")
        print(f"[archive-bundle] {archive_tab.status_var.get()}")
        assert "Created" in archive_tab.status_var.get()

        # --- Archive tab: gzip mode ---
        archive_tab.mode_var.set("gzip")
        archive_tab._start()
        wait_until(root, lambda: "Compressed" in archive_tab.status_var.get(),
                   timeout=10, what="archive gzip batch to finish")
        print(f"[archive-gzip]   {archive_tab.status_var.get()}")
        assert all(os.path.isfile(p + ".gz") for p in archive_srcs)

        root.destroy()

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
