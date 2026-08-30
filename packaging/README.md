# Packaging Squeeze as a standalone executable

`squeeze.spec` builds a single-file, no-Python-required executable with
[PyInstaller](https://pyinstaller.org/). It's been built and
smoke-tested (the resulting executable actually launches, not just
"PyInstaller didn't error").

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

From the repo root, with a virtualenv activated:

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
this packaging only bundles the Python/Tk/Pillow side. Reasons: ffmpeg
is a large (~80MB+), platform-specific, license-bearing binary
(LGPL/GPL depending on build config), and correctly redistributing it
means shipping the right build per OS/arch and honoring its license —
worth doing deliberately later, not as a packaging afterthought. Until
then, tell people installing the standalone executable to also install
ffmpeg (`sudo apt install ffmpeg`, `brew install ffmpeg`, or grab a
build from ffmpeg.org) if they want the Video tab. Photos and
Files/Archives work with zero extra installs either way.

## Building for all platforms via GitHub Actions

Push a tag starting with `v` (e.g. `v0.1.0`):

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/build.yml` then builds Squeeze on `windows-latest`,
`macos-latest`, and `ubuntu-latest`, and attaches all three executables
to a GitHub Release created for that tag — so anyone can grab the right
one from the repo's Releases page without installing Python or building
anything themselves.

You can also trigger the same workflow manually (without pushing a tag)
from the Actions tab — it uploads the three executables as workflow
artifacts in that case instead of creating a release, useful for
checking a build works before deciding to cut a release.

## Verifying a build actually works (not just "PyInstaller didn't error")

A PyInstaller build can succeed and still produce an executable that
crashes on launch (a missing hidden import, a hook that didn't fire).
`scripts/_pyinstaller_exe_smoke.py` catches that class of failure by
actually launching the built executable and checking it's still running
a few seconds later, instead of exiting immediately with an import
error:

```bash
pyinstaller packaging/squeeze.spec
xvfb-run -a python3 scripts/_pyinstaller_exe_smoke.py dist/Squeeze   # Linux/CI, headless
# or, with a real display:
python3 scripts/_pyinstaller_exe_smoke.py dist/Squeeze
```

This is what `.github/workflows/build.yml` runs after every build,
before uploading anything — a build that produces a crashing executable
fails CI instead of silently shipping a broken download.
