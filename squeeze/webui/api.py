"""The Python object exposed to the frontend as `pywebview.api`.

Every method here is callable from JavaScript and returns something
JSON-serializable (pywebview handles the marshalling). Long-running work
(compression) runs on a background thread via `jobs.Runner`; the
frontend polls `get_*_status()` every ~300ms rather than this pushing
updates, which keeps the JS side simple (one polling loop) and avoids
needing a second communication channel back into the page.

Nothing in here does any actual compression — it's a thin adapter over
squeeze/core/*, which is unchanged from the Tkinter build and already
has no UI-framework dependency.
"""

from __future__ import annotations

import json
import os
import threading

import webview

from squeeze.core.archive import (
    ARCHIVE_FORMATS,
    create_archive,
    default_archive_extension,
    gzip_files_individually,
)
from squeeze.core.common import CompressResult
from squeeze.core.ffmpeg_util import (
    VIDEO_EXTENSIONS,
    find_ffmpeg,
    find_ffprobe,
    is_video_file,
    probe,
)
from squeeze.core.format import human_size
from squeeze.core.photo import (
    IMAGE_EXTENSIONS,
    PhotoOptions,
    compress_photo,
    default_output_extension,
    is_image_file,
)
from squeeze.core.video import (
    QUALITY_PRESETS,
    VIDEO_CODECS,
    VideoOptions,
    compress_video,
)
from squeeze.webui.jobs import Runner

MAX_DIMENSION_CHOICES = {
    "Keep original size": None,
    "Max 3840px (4K)": 3840,
    "Max 1920px (Full HD)": 1920,
    "Max 1280px (HD)": 1280,
    "Max 800px": 800,
}


def _unique_path(out_dir: str, name: str, ext: str) -> str:
    candidate = os.path.join(out_dir, f"{name}{ext}")
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(out_dir, f"{name}_{n}{ext}")
        n += 1
    return candidate


def _unique_output_path(out_dir: str, stem: str, ext: str) -> str:
    """Same as `_unique_path`, but for a *derived* output next to an
    original file — always suffixed so it can never collide with (or be
    mistaken for) the source it was compressed from.
    """
    return _unique_path(out_dir, f"{stem}_compressed", ext)


class Api:
    def __init__(self) -> None:
        self.window: webview.Window | None = None
        self._video_runner = Runner()
        self._photo_runner = Runner()
        self._archive_runner = Runner()
        self._archive_bundle_state = {"running": False, "overall": ""}

    # -- static info for the frontend to build its controls from -----------
    def get_capabilities(self) -> dict:
        return {
            "ffmpeg_available": bool(find_ffmpeg() and find_ffprobe()),
            "video_codecs": VIDEO_CODECS,
            "quality_presets": {
                name: {"codec": p.codec, "crf": p.crf, "speed": p.speed, "profile": p.profile}
                for name, p in QUALITY_PRESETS.items()
            },
            "max_dimension_choices": list(MAX_DIMENSION_CHOICES.keys()),
            "archive_formats": list(ARCHIVE_FORMATS.keys()),
        }

    # -- file/folder pickers (native OS dialogs via the webview window) ----
    def _pick_files(self, file_types: tuple[str, ...] = ()) -> list[str]:
        if self.window is None:
            return []
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=file_types
        )
        return list(result) if result else []

    def _pick_folder(self) -> str | None:
        if self.window is None:
            return None
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def pick_video_files(self) -> list[str]:
        return self._pick_files(("Video files (*.mp4;*.mov;*.mkv;*.avi;*.webm)", "All files (*.*)"))

    def pick_video_folder(self) -> list[str]:
        folder = self._pick_folder()
        if not folder:
            return []
        found = []
        for dirpath, _dirnames, filenames in os.walk(folder):
            for name in filenames:
                if is_video_file(name):
                    found.append(os.path.join(dirpath, name))
        return found

    def pick_photo_files(self) -> list[str]:
        return self._pick_files(("Image files (*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tiff)", "All files (*.*)"))

    def pick_photo_folder(self) -> list[str]:
        folder = self._pick_folder()
        if not folder:
            return []
        found = []
        for dirpath, _dirnames, filenames in os.walk(folder):
            for name in filenames:
                if is_image_file(name):
                    found.append(os.path.join(dirpath, name))
        return found

    def pick_archive_files(self) -> list[str]:
        return self._pick_files()

    def pick_archive_folder(self) -> list[str]:
        folder = self._pick_folder()
        return [folder] if folder else []

    def pick_output_folder(self) -> str:
        return self._pick_folder() or ""

    # -- drag & drop -------------------------------------------------------
    def expand_dropped_paths(self, paths: list[str], kind: str) -> list[str]:
        """Turn raw dropped paths into what the given tab's queue accepts:
        folders are walked (video/photo tabs) or kept whole (archive tab,
        which archives folders as folders), and loose files are filtered
        to the media types the tab can actually process.
        """
        matcher = {"video": is_video_file, "photo": is_image_file}.get(kind)
        found: list[str] = []
        for path in paths:
            if os.path.isdir(path):
                if matcher is None:
                    found.append(path)
                    continue
                for dirpath, _dirnames, filenames in os.walk(path):
                    for name in filenames:
                        if matcher(name):
                            found.append(os.path.join(dirpath, name))
            elif os.path.isfile(path):
                if matcher is None or matcher(path):
                    found.append(path)
        return found

    def _on_drop(self, event: dict) -> None:
        """DOM drop handler (registered in webapp.py via window.dom, not
        exposed to JS). pywebview resolves each dropped file's real
        filesystem path into `pywebviewFullPath` — the page's own JS never
        sees full paths (browser security model), so this hands them back
        to the frontend explicitly, which routes them to the active tab.
        """
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths and self.window is not None:
            self.window.evaluate_js(f"window.squeezeHandleDrop({json.dumps(paths)})")

    # -- video ---------------------------------------------------------------
    def start_video_job(self, items: list[str], options: dict) -> dict:
        if self._video_runner.is_running():
            return {"ok": False, "error": "A video job is already running."}
        if not items:
            return {"ok": False, "error": "Add at least one video first."}

        opts = VideoOptions(
            codec=options["codec"],
            crf=int(options["crf"]),
            preset=options["preset"],
            profile=options.get("profile") or None,
            target_height=options.get("target_height") or None,
            audio_mode=options.get("audio_mode", "copy"),
            deinterlace=bool(options.get("deinterlace")),
        )
        container = options.get("container", "mp4")
        out_dir_override = (options.get("output_dir") or "").strip()

        out_paths = {}
        for item in items:
            out_dir = out_dir_override or os.path.dirname(item)
            stem = os.path.splitext(os.path.basename(item))[0]
            out_paths[item] = _unique_output_path(out_dir, stem, "." + container)

        def job_fn(item, should_stop, report):
            out_path = out_paths[item]
            report(-2, "Probing…")
            try:
                info = probe(item)
            except Exception as exc:
                return CompressResult(success=False, message=str(exc))
            report(-2, "Compressing…")
            item_opts = opts
            if opts.target_height and info.height and opts.target_height >= info.height:
                item_opts = VideoOptions(**{**opts.__dict__, "target_height": None})
            return compress_video(
                item, out_path, item_opts, duration_sec=info.duration_sec,
                on_progress=report, should_stop=should_stop,
            )

        self._video_runner.start(items, key_fn=lambda p: p, job_fn=job_fn)
        return {"ok": True}

    def get_video_status(self) -> dict:
        return self._video_runner.snapshot()

    def cancel_video_job(self) -> None:
        self._video_runner.cancel()

    # -- photos ---------------------------------------------------------------
    def start_photo_job(self, items: list[str], options: dict) -> dict:
        if self._photo_runner.is_running():
            return {"ok": False, "error": "A photo job is already running."}
        if not items:
            return {"ok": False, "error": "Add at least one photo first."}

        opts = PhotoOptions(
            quality=int(options.get("quality", 80)),
            max_dimension=MAX_DIMENSION_CHOICES.get(options.get("resize", "Keep original size")),
            output_format=options.get("output_format", "same"),
            strip_metadata=bool(options.get("strip_metadata", True)),
        )
        out_dir_override = (options.get("output_dir") or "").strip()

        out_paths = {}
        for item in items:
            out_dir = out_dir_override or os.path.dirname(item)
            stem = os.path.splitext(os.path.basename(item))[0]
            if opts.output_format == "same":
                ext = os.path.splitext(item)[1].lower()
            else:
                ext = default_output_extension(opts.output_format)
            out_paths[item] = _unique_output_path(out_dir, stem, ext)

        def job_fn(item, should_stop, report):
            report(-2, "Compressing…")
            return compress_photo(item, out_paths[item], opts)

        self._photo_runner.start(items, key_fn=lambda p: p, job_fn=job_fn)
        return {"ok": True}

    def get_photo_status(self) -> dict:
        return self._photo_runner.snapshot()

    def cancel_photo_job(self) -> None:
        self._photo_runner.cancel()

    # -- files / archives -------------------------------------------------
    def start_archive_bundle_job(self, items: list[str], options: dict) -> dict:
        if self._archive_bundle_state["running"]:
            return {"ok": False, "error": "An archive job is already running."}
        if not items:
            return {"ok": False, "error": "Add at least one file or folder first."}

        fmt = ARCHIVE_FORMATS[options["format_label"]]
        level = int(options.get("level", 6))
        out_dir = (options.get("output_dir") or "").strip() or os.path.dirname(os.path.abspath(items[0]))
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Cannot write to output folder: {exc}"}
        target = _unique_path(out_dir, "archive", default_archive_extension(fmt))

        stop_event = threading.Event()
        self._archive_bundle_stop = stop_event
        self._archive_bundle_state = {"running": True, "overall": f"Compressing {len(items)} item(s)…"}

        def progress_cb(done, total, _name):
            self._archive_bundle_state["overall"] = f"Compressing… {done}/{total}"

        def worker():
            result = create_archive(
                items, target, fmt=fmt, compression_level=level,
                on_progress=progress_cb, should_stop=stop_event.is_set,
            )
            self._archive_bundle_state["running"] = False
            if not result.success:
                if result.message == "Cancelled":
                    self._archive_bundle_state["overall"] = "Cancelled."
                else:
                    self._archive_bundle_state["overall"] = f"Failed: {result.message}"
                return
            self._archive_bundle_state["overall"] = (
                f"Created {target} — {human_size(result.output_size)} "
                f"(saved {result.saved_percent:.0f}% vs {human_size(result.input_size)})"
            )

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True}

    def get_archive_bundle_status(self) -> dict:
        return dict(self._archive_bundle_state)

    def cancel_archive_bundle_job(self) -> None:
        stop_event = getattr(self, "_archive_bundle_stop", None)
        if stop_event is not None:
            stop_event.set()

    def start_archive_gzip_job(self, items: list[str], options: dict) -> dict:
        if self._archive_runner.is_running():
            return {"ok": False, "error": "An archive job is already running."}
        if not items:
            return {"ok": False, "error": "Add at least one file or folder first."}

        level = int(options.get("level", 6))
        out_dir_override = (options.get("output_dir") or "").strip() or None

        def job_fn(item, should_stop, report):
            report(-2, "Compressing…")
            batch = gzip_files_individually(
                [item], output_dir=out_dir_override, compression_level=level, should_stop=should_stop
            )
            if not batch.results:
                return CompressResult(success=False, message="No files found (folder was empty?)")
            _path, result = batch.results[0]
            return result

        self._archive_runner.start(items, key_fn=lambda p: p, job_fn=job_fn)
        return {"ok": True}

    def get_archive_gzip_status(self) -> dict:
        return self._archive_runner.snapshot()

    def cancel_archive_gzip_job(self) -> None:
        self._archive_runner.cancel()
