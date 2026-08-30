# Dissect

A small, local-only desktop utility for seeing what's using your disk and
system resources — inspired by [DissectMac](https://dissectmac.com/), but
built cross-platform (Windows / macOS / Linux) in plain Python.

**Philosophy:** everything runs on your machine. No account, no network
calls, no telemetry. The one destructive action the app offers (removing
files) never permanently deletes anything — it moves files to a local
quarantine folder (`~/.dissect_trash`) that you can restore from.

## Features

- **Disk usage analyzer** — scan any folder and see a squarified treemap
  of what's taking up space, plus a sortable list. Double-click a folder
  (in the treemap or the list) to drill into it; "Up" to go back.
- **Duplicate file finder** — groups byte-identical files (cheap size
  check first, then a hash check only within same-size groups) and shows
  how much space you'd reclaim by keeping one copy per group.
- **Large & old file finder** — surfaces the biggest files, or the
  least-recently-modified ones, under a folder.
- **System monitor** — live CPU, memory, and per-disk usage.
- **Safe delete** — every "remove" action quarantines files instead of
  calling `os.remove`, so a misclick is recoverable.

## Requirements

- Python 3.9+
- Tkinter (bundled with the standard python.org installers for
  Windows/macOS; on Linux, install your distro's Tk package if it's
  missing, e.g. `sudo apt install python3-tk` on Debian/Ubuntu)
- `psutil` (only used by the System Monitor tab — everything else works
  without it)

## Running it

```bash
pip install -r requirements.txt
python run.py
```

The System Monitor tab works without `psutil` installed too — it just
shows a message telling you it's unavailable instead of crashing the app.

## Project layout

```
desktop_utility/
  core/            # Pure logic, no GUI dependency — fully unit-tested
    diskscan.py       # recursive size scan + squarified treemap layout
    duplicates.py      # size-then-hash duplicate detection
    largefiles.py      # bounded-heap largest/oldest file scans
    sysmon.py          # CPU/memory/disk snapshot via psutil
    safedelete.py       # quarantine / restore instead of permanent delete
    common.py          # human_size() etc.
  gui/             # Tkinter widgets, one file per tab
  workers.py       # background-thread + queue helper so scans don't
                   # freeze the UI
  app.py           # builds the main window and wires the tabs together
run.py             # entry point
tests/             # pytest suite for everything in core/
scripts/gui_smoke_test.py  # headless end-to-end smoke test (drives the
                            # real Tk widgets under Xvfb)
```

Every scan/analysis algorithm lives in `desktop_utility/core/` with **no
Tkinter import**, specifically so it can be unit tested without a
display. The GUI layer is a thin wrapper that calls into `core/` from a
background thread (via `workers.CancellableTask`) and renders the result.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

This covers directory scanning (including symlink handling, permission
errors, and edge cases), the treemap layout algorithm, duplicate
detection, the largest/oldest file heaps, and the quarantine/restore
round-trip — all without needing a display.

To smoke-test the actual GUI end-to-end (requires a display or Xvfb):

```bash
xvfb-run -a python3 scripts/gui_smoke_test.py   # Linux, headless
# or, with a real display:
python3 scripts/gui_smoke_test.py
```

## Roadmap ideas (not implemented yet)

- App uninstaller with leftover-file detection (DissectMac's flagship Pro
  feature) — cross-platform version would need per-OS heuristics for
  where apps leave data behind (`~/Library` on macOS, `%APPDATA%` on
  Windows, `~/.config`/`~/.cache` on Linux), which is why it's left out
  of this first pass rather than shipped half-right.
- Packaging as a standalone binary (PyInstaller) per platform.
- Scheduled/background scan mode.

## License

No license file has been added yet — add one if you plan to distribute
this.
