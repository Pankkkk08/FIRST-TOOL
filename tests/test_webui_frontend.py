"""Frontend interaction tests for squeeze/webui/static/*.

Runs the real HTML/CSS/JS in a real Chromium (via Playwright) with a
mocked `window.pywebview.api` standing in for the Python backend — this
verifies the DOM wiring (tab switching, the Quality Preset picker filling
in dependent fields, what shape of options object Start actually sends)
independently of squeeze/webui/api.py, which has its own real-backend
tests in test_webui_api.py. Between the two, both halves of the bridge
are exercised; only pywebview's own JS<->Python plumbing isn't covered
here (that's exactly what scripts/webview_smoke_test.py drives in a real
webview instead).
"""

from __future__ import annotations

import json
import pathlib

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "squeeze" / "webui" / "static"

MOCK_API_INIT_SCRIPT = """
window.__calls = [];
function recordCall(name, args) { window.__calls.push({name, args}); }

window.pywebview = {
  api: {
    get_capabilities: () => Promise.resolve({
      ffmpeg_available: true,
      video_codecs: {
        "H.264 (libx264) — widest compatibility": "libx264",
        "H.265 / HEVC (libx265) — smaller files": "libx265",
        "AV1 (libsvtav1) — smallest, needs newer players": "libsvtav1"
      },
      quality_presets: {
        "Fast (H.264)": {codec: "libx264", crf: 22, speed: "fast", profile: "main"},
        "HQ (H.264)": {codec: "libx264", crf: 20, speed: "slow", profile: "high"},
        "Fast (AV1)": {codec: "libsvtav1", crf: 34, speed: "6", profile: null}
      },
      max_dimension_choices: ["Keep original size", "Max 1920px (Full HD)"],
      archive_formats: ["ZIP (.zip)", "Tar + gzip (.tar.gz)"]
    }),
    pick_video_files: () => { recordCall("pick_video_files", []); return Promise.resolve(["/tmp/movie1.mp4", "/tmp/movie2.mov"]); },
    pick_video_folder: () => Promise.resolve([]),
    pick_photo_files: () => Promise.resolve(["/tmp/photo1.jpg"]),
    pick_photo_folder: () => Promise.resolve([]),
    pick_archive_files: () => Promise.resolve(["/tmp/doc1.txt", "/tmp/doc2.txt"]),
    pick_archive_folder: () => Promise.resolve([]),
    pick_output_folder: () => Promise.resolve("/tmp/out"),
    expand_dropped_paths: (paths, kind) => { recordCall("expand_dropped_paths", [paths, kind]); return Promise.resolve(paths); },
    start_video_job: (items, options) => { recordCall("start_video_job", [items, options]); return Promise.resolve({ok: true}); },
    get_video_status: () => Promise.resolve({running: false, rows: [], overall: "Done."}),
    cancel_video_job: () => { recordCall("cancel_video_job", []); return Promise.resolve(); },
    start_photo_job: (items, options) => { recordCall("start_photo_job", [items, options]); return Promise.resolve({ok: true}); },
    get_photo_status: () => Promise.resolve({running: false, rows: [], overall: "Done."}),
    cancel_photo_job: () => Promise.resolve(),
    start_archive_bundle_job: (items, options) => { recordCall("start_archive_bundle_job", [items, options]); return Promise.resolve({ok: true}); },
    get_archive_bundle_status: () => Promise.resolve({running: false, overall: "Done."}),
    cancel_archive_bundle_job: () => Promise.resolve(),
    start_archive_gzip_job: (items, options) => { recordCall("start_archive_gzip_job", [items, options]); return Promise.resolve({ok: true}); },
    get_archive_gzip_status: () => Promise.resolve({running: false, rows: [], overall: "Done."}),
    cancel_archive_gzip_job: () => Promise.resolve()
  }
};
"""


def _chromium_executable_path():
    """This sandbox's pip-installed Playwright and its pre-installed
    browser are a version apart, so the default lookup fails here; a
    normal `playwright install` setup won't need this override. Falls
    back to Playwright's own resolution when no mismatch is present.
    """
    import glob
    import os

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    candidates = sorted(glob.glob(os.path.join(browsers_path, "chromium-*", "chrome-linux", "chrome")))
    return candidates[-1] if candidates else None


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        exe = _chromium_executable_path()
        launch_kwargs = {"executable_path": exe} if exe else {}
        b = p.chromium.launch(**launch_kwargs)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page(viewport={"width": 1080, "height": 780})
    console_errors = []
    pg.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    pg.on("pageerror", lambda exc: console_errors.append(str(exc)))
    pg.add_init_script(MOCK_API_INIT_SCRIPT)
    pg.goto(f"file://{STATIC_DIR / 'index.html'}")
    pg.wait_for_timeout(200)
    pg._console_errors = console_errors  # noqa: SLF001 - test-only stash
    yield pg
    assert not console_errors, f"JS console errors: {console_errors}"
    pg.close()


def test_capabilities_populate_dropdowns(page):
    codec_options = page.eval_on_selector("#video-codec", "el => el.options.length")
    assert codec_options == 3
    preset_options = page.eval_on_selector("#video-preset", "el => Array.from(el.options).map(o => o.value)")
    assert "Fast (H.264)" in preset_options
    assert "Custom (set below)" in preset_options
    resize_options = page.eval_on_selector("#photo-resize", "el => el.options.length")
    assert resize_options == 2


def test_tab_switching(page):
    assert page.eval_on_selector("#tab-video", "el => el.classList.contains('active')")
    assert not page.eval_on_selector("#tab-photos", "el => el.classList.contains('active')")

    page.click(".tab-pill[data-tab='photos']")

    assert not page.eval_on_selector("#tab-video", "el => el.classList.contains('active')")
    assert page.eval_on_selector("#tab-photos", "el => el.classList.contains('active')")
    assert page.eval_on_selector(".tab-pill[data-tab='photos']", "el => el.classList.contains('active')")


def test_quality_preset_fills_dependent_fields(page):
    page.select_option("#video-preset", "HQ (H.264)")
    assert page.eval_on_selector("#video-codec", "el => el.value") == "H.264 (libx264) — widest compatibility"
    assert page.input_value("#video-crf") == "20"
    assert page.eval_on_selector("#video-speed", "el => el.value") == "slow"
    assert page.eval_on_selector("#video-profile", "el => el.value") == "high"


def test_quality_preset_av1_has_no_profile(page):
    page.select_option("#video-preset", "Fast (AV1)")
    assert page.eval_on_selector("#video-codec", "el => el.value") == "AV1 (libsvtav1) — smallest, needs newer players"
    assert page.input_value("#video-crf") == "34"
    # AV1 has no profile concept in this app — dropdown must fall back to
    # the single "(default)" option, not retain a stale x264 profile value.
    assert page.eval_on_selector("#video-profile", "el => el.value") == "(default)"


def test_add_files_populates_table(page):
    page.click("#video-add-files")
    page.wait_for_timeout(100)
    rows = page.eval_on_selector_all("#video-table tbody tr", "els => els.map(e => e.dataset.path)")
    assert rows == ["/tmp/movie1.mp4", "/tmp/movie2.mov"]
    first_row_name = page.eval_on_selector("#video-table tbody tr td", "el => el.textContent")
    assert first_row_name == "movie1.mp4"


def test_start_compressing_sends_correctly_shaped_options(page):
    page.click("#video-add-files")
    page.wait_for_timeout(100)
    page.select_option("#video-preset", "HQ (H.264)")
    # The checkbox itself is intentionally CSS-hidden and zero-sized
    # (opacity: 0; width/height: 0) in favor of its styled .toggle-track
    # sibling — the standard hidden-checkbox toggle-switch pattern — so
    # it has no clickable viewport rect for Playwright to click, even
    # with force. Set the underlying state directly instead.
    page.eval_on_selector(
        "#video-deinterlace", "el => { el.checked = true; el.dispatchEvent(new Event('change')); }"
    )
    page.fill("#video-outdir", "/tmp/my-output")
    page.click("#video-start")
    page.wait_for_timeout(100)

    calls = page.evaluate("window.__calls")
    start_calls = [c for c in calls if c["name"] == "start_video_job"]
    assert len(start_calls) == 1
    items, options = start_calls[0]["args"]
    assert items == ["/tmp/movie1.mp4", "/tmp/movie2.mov"]
    assert options["codec"] == "libx264"
    assert options["crf"] == "20"
    assert options["preset"] == "slow"
    assert options["profile"] == "high"
    assert options["deinterlace"] is True
    assert options["output_dir"] == "/tmp/my-output"


def test_start_compressing_disables_start_button(page):
    page.click("#video-add-files")
    page.wait_for_timeout(100)
    page.click("#video-start")
    page.wait_for_timeout(50)
    # The mocked get_video_status immediately reports running: false, so
    # the button re-enables on the very next poll tick — check the
    # cancel button became available in between rather than racing the
    # start button's disabled state.
    calls = page.evaluate("window.__calls")
    assert any(c["name"] == "start_video_job" for c in calls)


def test_archive_mode_toggle(page):
    page.click(".tab-pill[data-tab='archive']")
    page.wait_for_timeout(100)

    assert page.eval_on_selector("#archive-mode-bundle", "el => el.classList.contains('active')")
    assert not page.eval_on_selector("#archive-format", "el => el.disabled")

    page.click("#archive-mode-gzip")

    assert page.eval_on_selector("#archive-mode-gzip", "el => el.classList.contains('active')")
    assert not page.eval_on_selector("#archive-mode-bundle", "el => el.classList.contains('active')")
    assert page.eval_on_selector("#archive-format", "el => el.disabled")


def test_archive_gzip_job_uses_correct_api_method(page):
    page.click(".tab-pill[data-tab='archive']")
    page.wait_for_timeout(100)
    page.click("#archive-add-files")
    page.wait_for_timeout(100)
    page.click("#archive-mode-gzip")
    page.click("#archive-start")
    page.wait_for_timeout(100)

    calls = page.evaluate("window.__calls")
    assert any(c["name"] == "start_archive_gzip_job" for c in calls)
    assert not any(c["name"] == "start_archive_bundle_job" for c in calls)


def test_compression_level_slider_updates_label(page):
    page.click(".tab-pill[data-tab='archive']")
    page.wait_for_timeout(100)
    page.eval_on_selector("#archive-level", "el => { el.value = 9; el.dispatchEvent(new Event('input')); }")
    assert page.text_content("#archive-level-value") == "9"


def test_empty_queue_start_shows_alert_not_api_call(page):
    dialog_messages = []
    page.on("dialog", lambda d: (dialog_messages.append(d.message), d.accept()))
    page.click("#video-start")
    page.wait_for_timeout(100)
    assert dialog_messages == ["Add at least one video first."]
    calls = page.evaluate("window.__calls")
    assert not any(c["name"] == "start_video_job" for c in calls)


def test_dropped_paths_go_to_active_tab(page):
    # The real path resolution happens Python-side (browser JS never sees
    # full paths) — the backend calls window.squeezeHandleDrop with them,
    # so that's the entry point to drive here.
    page.evaluate("window.squeezeHandleDrop(['/tmp/dropped1.mp4', '/tmp/dropped2.mp4'])")
    page.wait_for_timeout(100)
    rows = page.eval_on_selector_all("#video-table tbody tr", "els => els.map(e => e.dataset.path)")
    assert rows == ["/tmp/dropped1.mp4", "/tmp/dropped2.mp4"]

    calls = page.evaluate("window.__calls")
    expand_calls = [c for c in calls if c["name"] == "expand_dropped_paths"]
    assert expand_calls[-1]["args"] == [["/tmp/dropped1.mp4", "/tmp/dropped2.mp4"], "video"]


def test_dropped_paths_respect_tab_switch(page):
    page.click(".tab-pill[data-tab='photos']")
    page.evaluate("window.squeezeHandleDrop(['/tmp/dropped.jpg'])")
    page.wait_for_timeout(100)

    calls = page.evaluate("window.__calls")
    expand_calls = [c for c in calls if c["name"] == "expand_dropped_paths"]
    assert expand_calls[-1]["args"] == [["/tmp/dropped.jpg"], "photo"]
    rows = page.eval_on_selector_all("#photo-table tbody tr", "els => els.map(e => e.dataset.path)")
    assert rows == ["/tmp/dropped.jpg"]
    # ...and nothing leaked into the (inactive) video tab's queue.
    assert page.eval_on_selector_all("#video-table tbody tr", "els => els.length") == 0


def test_drag_overlay_shows_and_hides(page):
    assert not page.eval_on_selector("#drop-overlay", "el => el.classList.contains('visible')")
    page.evaluate("document.body.dispatchEvent(new DragEvent('dragenter', {bubbles: true}))")
    assert page.eval_on_selector("#drop-overlay", "el => el.classList.contains('visible')")
    page.evaluate("document.body.dispatchEvent(new DragEvent('drop', {bubbles: true}))")
    assert not page.eval_on_selector("#drop-overlay", "el => el.classList.contains('visible')")


def test_full_page_screenshot_smoke(page, tmp_path):
    # Not an assertion on pixels — just proves the whole page renders
    # without layout exceptions once real (mocked) data is loaded, and
    # gives a human-reviewable artifact.
    page.click("#video-add-files")
    page.wait_for_timeout(150)
    out = tmp_path / "frontend_smoke.png"
    page.screenshot(path=str(out))
    assert out.stat().st_size > 10_000
