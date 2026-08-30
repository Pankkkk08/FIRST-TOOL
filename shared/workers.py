"""Thread + polling helper so long scans never freeze the Tkinter UI.

Tkinter widgets must only be touched from the main thread. The pattern
here: run the scan in a background thread, drop the result (or exception)
into a queue, and poll that queue from `root.after()` on the main thread.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class CancellableTask:
    """One background job with a cooperative cancel flag."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def cancel(self) -> None:
        self._stop_event.set()

    def run(self, widget, target: Callable[[], Any], on_done: Callable[[Any, Exception | None], None], poll_ms: int = 100) -> None:
        """Start `target()` in a background thread; call `on_done(result, error)`
        on the main thread (via `widget.after`) once it finishes or raises.
        """
        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = target()
                result_queue.put((result, None))
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
                result_queue.put((None, exc))

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

        def poll() -> None:
            try:
                result, error = result_queue.get_nowait()
            except queue.Empty:
                widget.after(poll_ms, poll)
                return
            on_done(result, error)

        widget.after(poll_ms, poll)
