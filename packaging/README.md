# Packaging Squeeze as a standalone executable

`squeeze.spec` builds a single-file, no-Python-required executable with
[PyInstaller](https://pyinstaller.org/). It's been built and
smoke-tested (the resulting executable actually launches and drives a
real compression, not just "PyInstaller didn't error") — see
`scripts/webview_smoke_test.py` and `scripts/_pyinstaller_exe_smoke.py`.

## The UI is a webview, not Tkinter

Squeeze renders its UI with the OS's own webview — WebView2 on Windows
(bundled with Windows 10/11), WebKit on macOS (`pyobjc`, bundled with
the OS), WebKitGTK on Linux (a system package). This is real
GPU-accelerated rendering with genuine live CSS blur for the glass
panels, and it's what fixed an earlier, choppier Tkinter build where
the panels were hand-drawn, blurred *images* redrawn in Python. Nothing
here is a browser bundled into the app — pywebview talks to whatever
webview the OS already has.

**Linux end users need `webkit2gtk` installed** (Windows/macOS ship a
webview by default, nothing extra needed there):

```bash
sudo apt install gir1.2-webkit2-4.1   # Debian/Ubuntu
```

## Important: PyInstaller does not cross-compile

Build on the same OS you want the executable for:

- Build on Windows → get a Windows `.exe`
- Build on macOS → get a macOS `.app`
- Build on Linux → get a Linux ELF binary

There's no way around this locally. If you need executables for all
three platforms without owning all three machines, use the GitHub
Actions workflow described below — it builds on real Windows/macOS/Linux
runners and hands you all three.

## Building locally

From the repo root, with a virtualenv activated (on Linux, see the main
README's Installing section for why the venv needs
`--system-site-packages`, or the pinned-`pygobject` pip alternative, to
build at all):

```bash
pip install -r requirements.txt -r requirements-dev.txt
pyinstaller packaging/squeeze.spec
```

Output: `dist/Squeeze` (`dist/Squeeze.exe` on Windows, `dist/Squeeze.app`
on macOS) — a single file (or `.app` bundle), copy it anywhere and run
it. `build/` and `dist/` are scratch output, already in `.gitignore`;
delete them freely and rebuild any time.

### ffmpeg is not bundled

The Video tab still needs `ffmpeg`/`ffprobe` on the end user's PATH —
this packaging only bundles the Python/pywebview/Pillow side plus the
HTML/CSS/JS UI assets. Reasons: ffmpeg is a large (~80MB+),
platform-specific, license-bearing binary (LGPL/GPL depending on build
config), and correctly redistributing it means shipping the right build
per OS/arch and honoring its license — worth doing deliberately later,
not as a packaging afterthought. Until then, tell people installing the
standalone executable to also install ffmpeg (`sudo apt install ffmpeg`,
`brew install ffmpeg`, or grab a build from ffmpeg.org) if they want the
Video tab. Photos and Files/Archives work with zero extra installs
either way.

## Building for all platforms via GitHub Actions

Push a tag starting with `v` (e.g. `v0.1.0`):

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/build.yml` runs the full test suite first (including
a real end-to-end webview + ffmpeg smoke test), then builds Squeeze on
`windows-latest`, `macos-latest`, and `ubuntu-latest`, and attaches all
three executables to a GitHub Release created for that tag — so anyone
can grab the right one from the repo's Releases page without installing
Python or building anything themselves.

You can also trigger the same workflow manually (without pushing a tag)
from the Actions tab — it uploads the three executables as workflow
artifacts in that case instead of creating a release, useful for
checking a build works before deciding to cut a release.

## Verifying a build actually works (not just "PyInstaller didn't error")

A PyInstaller build can succeed and still produce an executable that
crashes on launch (a missing hidden import, a hook that didn't fire, a
data file that didn't get bundled). `scripts/_pyinstaller_exe_smoke.py`
catches that class of failure by actually launching the built executable
and checking it's still running a few seconds later, instead of exiting
immediately with an import error:

```bash
pyinstaller packaging/squeeze.spec
xvfb-run -a python3 scripts/_pyinstaller_exe_smoke.py dist/Squeeze   # Linux/CI, headless
# or, with a real display:
python3 scripts/_pyinstaller_exe_smoke.py dist/Squeeze
```

This is what `.github/workflows/build.yml` runs after every build,
before uploading anything — a build that produces a crashing executable
fails CI instead of silently shipping a broken download.

### A note on testing WebKitGTK under Xvfb specifically

Running the *unpackaged* app or its smoke tests under Xvfb (headless
Linux, e.g. this repo's own CI) needs two environment variables WebKitGTK
otherwise needs a real compositor for:

```bash
WEBKIT_DISABLE_COMPOSITING_MODE=1 LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python3 ...
```

Without them the window loads (the DOM, JS, and the Python bridge all
work correctly — confirmed via `window.evaluate_js`) but nothing paints
to the screen, which reads as a silent blank window if you're
screenshotting it for a sanity check. This is purely an Xvfb/software-
rendering artifact; a real desktop with a working compositor and/or GPU
doesn't need either variable.
