# Squeeze

A local video/photo/file compressor — the "make this smaller" HandBrake-
style workflow (batch queue, quality presets, live progress, cancel),
also covering photos and generic files. Everything runs on your machine:
no accounts, no network calls, no telemetry.

## Features

- **Video** (needs ffmpeg) — batch queue of video files/folders. A
  **Quality preset** picker (Fast / HQ / Super HQ, per codec) fills in
  sensible codec/CRF/speed/profile values with one click — the same
  numbers [HandBrake](https://github.com/HandBrake/HandBrake) itself
  ships as its own built-in presets (see **Credits** below) — and every
  field stays editable afterward for full manual control: codec
  (H.264/libx264, H.265/libx265, or AV1/libsvtav1), CRF quality, encoder
  speed, H.264/H.265 profile, target resolution, audio handling
  (copy/re-encode/strip), a deinterlace filter for old/DVD sources, and
  output container. Live per-file progress and encode speed, read
  straight from ffmpeg's own `-progress` output. Never upscales — if you
  ask for 1080p on a 720p source, it just keeps 720p.
  **Hardware acceleration**: when your ffmpeg build offers a GPU encoder
  for the chosen codec (NVIDIA NVENC, Intel QSV, AMD AMF, Apple
  VideoToolbox), a "Use graphics card acceleration" toggle appears —
  typically 5-15× faster, and it keeps the CPU free. If the listed
  encoder turns out not to work on the actual hardware (common: ffmpeg
  builds list encoders the machine can't run), the file is automatically
  re-encoded in software and its row says "Done (software fallback)" —
  nothing fails. Quality mapping is anchored to HandBrake's own hardware
  preset numbers. Encodes also run at below-normal CPU priority (the
  same default HandBrake uses) so the app and the rest of the system
  stay responsive while all cores are busy.
- **Photos** (needs Pillow) — batch queue of images; quality slider,
  max-dimension resize (never upscales), format conversion
  (JPEG/PNG/WEBP), EXIF/metadata stripping. Applies EXIF orientation
  before saving so re-encoded photos don't come out sideways.
- **Files / Archives** (stdlib only) — either bundle files/folders into
  one archive (.zip / .tar.gz / .tar.xz, adjustable compression level,
  folder structure preserved) or gzip each file individually in place
  (`file.log` → `file.log.gz`), whichever shape of "smaller" you need.

Files and folders can also be **dragged and dropped** straight onto the
window from your file manager — they land in whichever tab is open
(folders are searched for videos/photos automatically; the
Files & Archives tab keeps them as folders).

Every tab processes its batch on a background thread so the window
never freezes, and every job can be cancelled mid-run. Queued files show
their size, and a finished batch reports its total ("Done — 2.1 GB →
800 MB (saved 62%)"). None of the three
tabs overwrite your originals or an existing output file — outputs get a
`_compressed` suffix (or `_2`, `_3`, ... if that's already taken).

### Design

The UI is HTML/CSS/JS rendered by the OS's own webview — WebView2 on
Windows, WebKit on macOS/Linux — driven by a small Python backend
(`squeeze/webui/`), not a browser bundled into the app. This replaced an
earlier Tkinter build whose glass panels were hand-drawn blurred
*images*, redrawn in Python on every change: it worked, but felt choppy.
The glass panels here get real, live, GPU-accelerated `backdrop-filter`
blur from the browser engine itself — smoother, and dramatically less
code (`squeeze/webui/static/style.css` vs. a custom Pillow-based
rendering toolkit). See `squeeze/webui/api.py` for the Python↔JS bridge
and `squeeze/webui/static/` for the frontend.

## Installing

There's no installer/package published yet — you run this straight from
a checkout of this repo. Two ways to do that, depending on how
comfortable you are with Python:

### Option A — run from source (works today, needs Python)

```bash
git clone <this-repo-url>
cd FIRST-TOOL

# Windows/macOS:
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# Linux: use --system-site-packages so the venv can see apt's PyGObject
# bindings — see the note below for why a plain venv doesn't work here.
sudo apt install gir1.2-webkit2-4.1
python3 -m venv --system-site-packages .venv && source .venv/bin/activate
pip install -r requirements.txt

python run_squeeze.py
```

Requirements:
- Python 3.9+
- `pip install -r requirements.txt` covers `pywebview` (the UI shell) and
  `Pillow` (the Photos tab)
- A system webview — Windows and macOS already have one (WebView2 /
  WebKit). **On Linux**, `pywebview` needs GTK+WebKit2 Python bindings
  (`gi`), which don't come from pip in the usual way — install the
  system package and give your venv access to it:
  `sudo apt install gir1.2-webkit2-4.1` (Debian/Ubuntu), then create
  your venv with `--system-site-packages` (as above) rather than a
  plain one, or just run with your system Python directly instead of a
  venv. If you do need an isolated venv without system-site-packages,
  install the bindings via pip instead: `sudo apt install
  libgirepository1.0-dev libcairo2-dev pkg-config python3-dev &&
  pip install pygobject==3.48.2` (pin needed — newer PyGObject has a
  callback-signature incompatibility with pywebview's GTK backend).
- **ffmpeg** on PATH, for the Video tab only — install via
  `sudo apt install ffmpeg`, `brew install ffmpeg`, or ffmpeg.org. The
  Photos and Files/Archives tabs work without it.

### Option B — build a standalone executable (no Python needed to run it)

For someone who just wants to double-click an app, build a one-file
executable with [PyInstaller](https://pyinstaller.org/) **on the same OS
you want to run it on** (PyInstaller doesn't cross-compile):

```bash
pip install -r requirements.txt -r requirements-dev.txt
pyinstaller packaging/squeeze.spec
```

This produces `dist/Squeeze` (`.exe` on Windows, a `.app` bundle on
macOS) — copy that file anywhere and run it; nothing else needs to be
installed alongside it (ffmpeg for the Video tab is still a separate
system install — see `packaging/README.md`).

On Windows there's additionally a real installer: after building the
`.exe`, `iscc packaging\windows-installer.iss` (Inno Setup) produces
`dist/Squeeze-Setup.exe`, which installs Squeeze like normal software —
Start Menu entry, optional desktop icon, and an uninstaller in Windows'
"Installed apps". No admin rights needed (it installs per-user). The
GitHub Actions workflow builds this automatically alongside the portable
`.exe`.

If you push a `v*` git tag, `.github/workflows/build.yml` builds this
for Windows/macOS/Linux automatically and attaches the executables to a
GitHub Release, so most people can just download a file from the
Releases page instead of building it themselves. See
`packaging/README.md` for details on both paths.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

All compression logic lives in `squeeze/core/` with **no UI-framework
import**, so it's fully unit-tested without a display — ffmpeg command
building (including a real encode/probe/cancel round-trip and the
built-in quality presets), Pillow resize/quality/format conversion, and
zip/tar archive creation all have direct tests. `squeeze/webui/api.py`
and `jobs.py` (the background-job runner) get the same treatment: real
compression jobs driven directly, no browser needed.

The frontend (`squeeze/webui/static/*`) has its own test layer using
[Playwright](https://playwright.dev/) with a mocked `pywebview.api`,
verifying the DOM wiring — tab switching, the Quality Preset picker
filling in dependent fields, the exact options object Start sends —
independently of the backend:

```bash
pytest tests/test_webui_frontend.py -v
```

And for the real end-to-end path — an actual webview, the actual
JS↔Python bridge, an actual ffmpeg encode, not mocked — see
`scripts/webview_smoke_test.py`:

```bash
xvfb-run -a python3 scripts/webview_smoke_test.py
```

## Project layout

```
squeeze/
  core/            # No UI-framework import — unit-tested directly
    ffmpeg_util.py    # find ffmpeg/ffprobe, probe duration/resolution
    video.py           # HandBrake-derived quality presets, ffmpeg
                        # command building, encode + progress parsing
    photo.py            # Pillow resize/quality/format/metadata
    archive.py           # zip/tar.gz/tar.xz bundling + per-file gzip
    common.py            # shared CompressResult dataclass
    format.py             # human_size() etc.
  webui/           # the pywebview UI
    api.py            # Python object exposed to JS as `pywebview.api` —
                       # a thin adapter over squeeze/core/*
    jobs.py             # generic background batch-job runner (video/
                         # photo/archive-gzip all share it)
    static/              # the actual frontend
      index.html            # page structure, all three tabs
      style.css              # the glass design system — real CSS
                              # backdrop-filter blur, no Python rendering
      app.js                  # DOM wiring + polling loop against
                               # pywebview.api
  webapp.py        # builds the pywebview window, wires up Api
run_squeeze.py     # entry point
```

## Credits

The Video tab's Fast/HQ/Super HQ quality presets (CRF, encoder speed,
and H.264/H.265 profile per codec) are lifted directly from
[HandBrake](https://github.com/HandBrake/HandBrake)'s own built-in
preset definitions
([`preset/preset_builtin.json`](https://github.com/HandBrake/HandBrake/blob/master/preset/preset_builtin.json))
rather than guessed at — HandBrake's maintainers have tuned these over
many releases, and there was no reason to reinvent that. This tool
itself is a from-scratch ffmpeg wrapper, not a fork or repackaging of
HandBrake's code.

## Roadmap ideas (not implemented yet)

- A "target file size" mode for video (two-pass encoding to hit an exact
  MB target, the way HandBrake's own "Social" presets work) instead of
  only quality-based CRF.
- HEIC input support for photos (needs a codec Pillow doesn't ship with
  by default).

## License

No license file has been added yet — add one if you plan to distribute
this.
