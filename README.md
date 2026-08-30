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
- **Photos** (needs Pillow) — batch queue of images; quality slider,
  max-dimension resize (never upscales), format conversion
  (JPEG/PNG/WEBP), EXIF/metadata stripping. Applies EXIF orientation
  before saving so re-encoded photos don't come out sideways.
- **Files / Archives** (stdlib only) — either bundle files/folders into
  one archive (.zip / .tar.gz / .tar.xz, adjustable compression level,
  folder structure preserved) or gzip each file individually in place
  (`file.log` → `file.log.gz`), whichever shape of "smaller" you need.

Every tab processes its batch on a background thread so the window
never freezes, and every job can be cancelled mid-run. None of the three
tabs overwrite your originals or an existing output file — outputs get a
`_compressed` suffix (or `_2`, `_3`, ... if that's already taken).

## Installing

There's no installer/package published yet — you run this straight from
a checkout of this repo. Two ways to do that, depending on how
comfortable you are with Python:

### Option A — run from source (works today, needs Python)

```bash
git clone <this-repo-url>
cd FIRST-TOOL
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
python run_squeeze.py
```

Requirements:
- Python 3.9+
- Tkinter — bundled with the standard python.org installers for
  Windows/macOS; on Linux, install your distro's Tk package if it's
  missing, e.g. `sudo apt install python3-tk` on Debian/Ubuntu
- `pip install -r requirements.txt` covers `Pillow` (the Photos tab)
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

All compression logic lives in `squeeze/core/` with **no Tkinter
import**, so it's fully unit-tested without a display — ffmpeg command
building (including a real encode/probe/cancel round-trip and the
built-in quality presets), Pillow resize/quality/format conversion, and
zip/tar archive creation all have direct tests.

To smoke-test the actual GUI end-to-end (drives the real Tk widgets and
background threads, requires a display or Xvfb):

```bash
xvfb-run -a python3 scripts/squeeze_smoke_test.py
```

## Project layout

```
squeeze/
  core/            # No Tkinter import — unit-tested directly
    ffmpeg_util.py    # find ffmpeg/ffprobe, probe duration/resolution
    video.py           # HandBrake-derived quality presets, ffmpeg
                        # command building, encode + progress parsing
    photo.py            # Pillow resize/quality/format/metadata
    archive.py           # zip/tar.gz/tar.xz bundling + per-file gzip
    common.py            # shared CompressResult dataclass
    format.py             # human_size() etc.
  gui/             # Tkinter widgets, one file per tab
    workers.py         # CancellableTask: background-thread + queue
                        # polling helper so a job never freezes the UI
    batch.py             # sequential background batch-job runner
                          # (shared by the Video and Photo tabs)
  app.py           # builds the main window and wires the tabs together
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

- Hardware-accelerated encoding (VideoToolbox/NVENC/QSV) for much faster
  video compression on supported hardware — left out because it needs
  per-platform detection and graceful fallback to get right.
- A "target file size" mode for video (two-pass encoding to hit an exact
  MB target, the way HandBrake's own "Social" presets work) instead of
  only quality-based CRF.
- HEIC input support for photos (needs a codec Pillow doesn't ship with
  by default).

## License

No license file has been added yet — add one if you plan to distribute
this.
