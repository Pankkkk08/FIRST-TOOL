# Local Desktop Tools

Small, local-only desktop utilities in plain Python — no accounts, no
network calls, no telemetry. Two tools live here so far:

| Tool | What it does | Run it |
|---|---|---|
| **[Dissect](#dissect)** | See what's using your disk & system resources | `python run.py` |
| **[Squeeze](#squeeze)** | Compress video, photos, and files/folders | `python run_compressor.py` |

Both are separate windows/apps (run whichever you need), and both share a
small `shared/` package (background-thread runner, safe quarantine-delete,
byte-size formatting) so they behave consistently.

## Requirements

- Python 3.9+
- Tkinter (bundled with the standard python.org installers for
  Windows/macOS; on Linux, install your distro's Tk package if it's
  missing, e.g. `sudo apt install python3-tk` on Debian/Ubuntu)
- `pip install -r requirements.txt` for the optional bits: `psutil`
  (Dissect's System Monitor tab) and `Pillow` (Squeeze's Photos tab)
- **ffmpeg** on PATH, for Squeeze's Video tab only (see below) — install
  via `sudo apt install ffmpeg`, `brew install ffmpeg`, or ffmpeg.org.
  Every other tab/feature in both apps works without it.

```bash
pip install -r requirements.txt
python run.py              # Dissect
python run_compressor.py   # Squeeze
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

All scan/compression logic lives in each tool's `core/` package with
**no Tkinter import**, so it's fully unit-tested without a display —
duplicate/large-file detection, the treemap algorithm, ffmpeg command
building + a real encode/cancel round-trip, Pillow resize/quality/format
conversion, and zip/tar archive creation all have direct tests.

To smoke-test the actual GUIs end-to-end (drives the real Tk widgets and
background threads, requires a display or Xvfb):

```bash
xvfb-run -a python3 scripts/gui_smoke_test.py          # Dissect
xvfb-run -a python3 scripts/compressor_smoke_test.py   # Squeeze
```

---

## Dissect

Inspired by [DissectMac](https://dissectmac.com/), built cross-platform
(Windows / macOS / Linux).

**Philosophy:** the one destructive action the app offers (removing
files) never permanently deletes anything — it moves files to a local
quarantine folder (`~/.dissect_trash`) that you can restore from.

### Features

- **Disk usage analyzer** — scan any folder and see a squarified treemap
  of what's taking up space, plus a sortable list. Double-click a folder
  (in the treemap or the list) to drill into it; "Up" to go back.
- **Duplicate file finder** — groups byte-identical files (cheap size
  check first, then a hash check only within same-size groups) and shows
  how much space you'd reclaim by keeping one copy per group.
- **Large & old file finder** — surfaces the biggest files, or the
  least-recently-modified ones, under a folder.
- **System monitor** — live CPU, memory, and per-disk usage.

### Project layout

```
desktop_utility/
  core/            # diskscan (treemap), duplicates, largefiles, sysmon
  gui/             # Tkinter widgets, one file per tab
  app.py           # builds the main window and wires the tabs together
run.py             # entry point
```

### Roadmap ideas (not implemented yet)

- App uninstaller with leftover-file detection (DissectMac's flagship Pro
  feature) — cross-platform version would need per-OS heuristics for
  where apps leave data behind (`~/Library` on macOS, `%APPDATA%` on
  Windows, `~/.config`/`~/.cache` on Linux), which is why it's left out
  of this first pass rather than shipped half-right.
- Packaging as a standalone binary (PyInstaller) per platform.

---

## Squeeze

A local video/photo/file compressor — the "make this smaller" HandBrake-
style workflow (batch queue, presets, progress, cancel), but also
covering photos and generic files, and built the same local-only way as
Dissect. Every tab processes a batch on a background thread so the
window never freezes, and every job can be cancelled mid-run.

### Features

- **Video** (needs ffmpeg) — batch queue of video files/folders; choose
  codec (H.264/libx264, H.265/libx265, or AV1/libsvtav1), quality (CRF),
  target resolution, audio handling (copy/re-encode/strip), and output
  container. Live per-file progress and encode speed, read straight from
  ffmpeg's own `-progress` output. Never upscales — if you ask for 1080p
  on a 720p source, it just keeps 720p.
- **Photos** (needs Pillow) — batch queue of images; quality slider,
  max-dimension resize (never upscales), format conversion
  (JPEG/PNG/WEBP), EXIF/metadata stripping. Applies EXIF orientation
  before saving so re-encoded photos don't come out sideways.
- **Files / Archives** (stdlib only) — either bundle files/folders into
  one archive (.zip / .tar.gz / .tar.xz, adjustable compression level,
  folder structure preserved) or gzip each file individually in place
  (`file.log` → `file.log.gz`), whichever shape of "smaller" you need.

None of the three tabs overwrite your originals or an existing output
file — outputs get a `_compressed` suffix (or `_2`, `_3`, ... if that's
already taken).

### Project layout

```
compressor/
  core/            # No Tkinter import — unit-tested directly
    ffmpeg_util.py    # find ffmpeg/ffprobe, probe duration/resolution
    video.py           # build the ffmpeg command, run it, parse progress
    photo.py            # Pillow resize/quality/format/metadata
    archive.py           # zip/tar.gz/tar.xz bundling + per-file gzip
    common.py            # shared CompressResult dataclass
  gui/             # Tkinter widgets, one file per tab
    batch.py          # sequential background batch-job runner (shared
                       # by the Video and Photo tabs)
  app.py           # builds the main window and wires the tabs together
run_compressor.py  # entry point
```

### Roadmap ideas (not implemented yet)

- Hardware-accelerated encoding (VideoToolbox/NVENC/QSV) for much faster
  video compression on supported hardware — left out because it needs
  per-platform detection and graceful fallback to get right.
- A "target file size" mode for video (two-pass encoding to hit an exact
  MB target) instead of only quality-based CRF.
- HEIC input support for photos (needs a codec Pillow doesn't ship with
  by default).

---

## Shared code

```
shared/
  workers.py    # CancellableTask: background-thread + queue polling
                 # helper so a scan/compress never freezes the UI
  safedelete.py  # quarantine/restore instead of permanent delete (used
                  # by Dissect; available to Squeeze if it ever needs it)
  format.py       # human_size() etc.
  theme.py         # shared color/font constants
```

## License

No license file has been added yet — add one if you plan to distribute
this.
