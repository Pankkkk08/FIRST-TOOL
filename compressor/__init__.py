"""Squeeze — a local video/photo/file compressor.

Wraps ffmpeg (video) and Pillow (photos) plus the stdlib zipfile/tarfile
modules (archives). Everything runs as a local subprocess/library call —
no uploads, no network calls, no telemetry.
"""

__version__ = "0.1.0"
