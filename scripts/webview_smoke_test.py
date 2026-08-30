#!/usr/bin/env python3
"""Headless end-to-end smoke test for Squeeze: launches the real
pywebview window (real WebKit/WebView2 renderer, real JS<->Python
`js_api` bridge — not mocked, unlike tests/test_webui_frontend.py) and
drives a real video compression through it via `window.evaluate_js`,
since native file-picker dialogs can't be scripted — everything else
(the API bridge, the DOM, ffmpeg) is exercised for real.

Run manually via:
    WEBKIT_DISABLE_COMPOSITING_MODE=1 LIBGL_ALWAYS_SOFTWARE=1 \\
        xvfb-run -a python3 scripts/webview_smoke_test.py

(The two env vars work around a WebKitGTK-under-Xvfb rendering quirk —
see packaging/README.md. Not needed on a real desktop.)
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webview  # noqa: E402

from squeeze.core.ffmpeg_util import find_ffmpeg  # noqa: E402
from squeeze.webui.api import Api  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "squeeze", "webui", "static")


def make_test_clip(path: str, duration: float = 1.5) -> None:
    cmd = [
        find_ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=15",
        "-f", "lavfi", "-i", f"sine=duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac",
        path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)


def call_js(window, expr: str, timeout: float = 15.0):
    """`window.evaluate_js(expr)` does NOT await a Promise unless given a
    callback — without one it just JSON-stringifies the raw Promise
    object (which serializes to `{}`), so every `pywebview.api.*(...)`
    call here (always Promise-returning, even for a sync Python method)
    needs the callback form. Converts that callback into an ordinary
    blocking call via a threading.Event.
    """
    done = threading.Event()
    box: dict = {}

    def callback(result):
        box["value"] = result
        done.set()

    window.evaluate_js(expr, callback)
    if not done.wait(timeout):
        raise AssertionError(f"evaluate_js callback timed out for: {expr}")
    return box["value"]


def wait_until(window, js_predicate: str, timeout: float, what: str) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if call_js(window, js_predicate):
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for: {what}")


def run(window: "webview.Window") -> None:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video_src = os.path.join(tmp, "clip.mp4")
            make_test_clip(video_src)

            # -- real API bridge sanity check --------------------------------
            caps = call_js(window, "window.pywebview.api.get_capabilities()")
            assert "quality_presets" in caps, caps
            assert caps["quality_presets"]["Fast (H.264)"]["crf"] == 22
            print("[bridge]  get_capabilities() OK via real js_api bridge")

            # -- drive the real DOM: pick a preset through the actual <select> --
            window.evaluate_js(
                "document.getElementById('video-preset').value = 'Fast (H.264)';"
                "document.getElementById('video-preset').dispatchEvent(new Event('change'));"
            )
            crf = window.evaluate_js("document.getElementById('video-crf').value")
            assert crf == "22", f"preset should have set CRF via real DOM event, got {crf!r}"
            print("[dom]     Quality Preset picker updated CRF field via real <select> change event")

            # -- start a real compression job (bypass the native file dialog,
            # call the exposed API directly like app.js's click handler would) --
            start_result = call_js(
                window,
                f"window.pywebview.api.start_video_job({json.dumps([video_src])}, "
                f"{{codec: 'libx264', crf: 30, preset: 'ultrafast'}})"
            )
            assert start_result["ok"], start_result
            print(f"[video]   started real compression job for {video_src}")

            wait_until(
                window,
                "window.pywebview.api.get_video_status().then(s => !s.running)",
                timeout=20, what="video job to finish",
            )
            status = call_js(window, "window.pywebview.api.get_video_status()")
            row = status["rows"][0]
            print(f"[video]   status={row['status']!r} saved={row.get('saved')!r}")
            assert row["status"] == "Done", status

            expected_out = os.path.join(tmp, "clip_compressed.mp4")
            assert os.path.isfile(expected_out), "compressed output file missing"
            print(f"[video]   output file confirmed on disk: {expected_out}")

            # -- archive tab: real zip through the real bridge -----------------
            doc = os.path.join(tmp, "doc.txt")
            with open(doc, "w") as f:
                f.write("hello world " * 2000)
            arc_result = call_js(
                window,
                f"window.pywebview.api.start_archive_bundle_job({json.dumps([doc])}, "
                f"{{format_label: 'ZIP (.zip)', level: 6, output_dir: {json.dumps(tmp)}}})"
            )
            assert arc_result["ok"], arc_result
            wait_until(
                window,
                "window.pywebview.api.get_archive_bundle_status().then(s => !s.running)",
                timeout=10, what="archive job to finish",
            )
            arc_status = call_js(window, "window.pywebview.api.get_archive_bundle_status()")
            print(f"[archive] {arc_status['overall']}")
            assert "Created" in arc_status["overall"], arc_status

        print("\nSMOKE TEST PASSED")
        os._exit(0)
    except Exception:
        import traceback

        traceback.print_exc()
        os._exit(1)


def main() -> None:
    api = Api()
    window = webview.create_window(
        "Squeeze", url=os.path.join(STATIC_DIR, "index.html"), js_api=api,
        width=1080, height=780,
    )
    api.window = window
    threading.Thread(target=run, args=(window,), daemon=True).start()
    webview.start(debug=False)


if __name__ == "__main__":
    main()
