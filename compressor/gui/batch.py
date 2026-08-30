"""Sequential batch-job runner shared by the Video/Photo/Archive tabs.

Runs a list of items through `job_fn` one at a time on a background
thread (so a slow ffmpeg encode on item 3 doesn't block the UI or item 4
from being queued), while letting each job report fractional progress.
Everything crosses back to the main thread through a Queue drained by
`widget.after()`, since Tkinter widgets are not thread-safe to touch
directly from the worker thread.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional


class BatchRunner:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._msg_queue: "queue.Queue[tuple[str, Any, Any]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def cancel(self) -> None:
        self._stop.set()

    def start(
        self,
        widget,
        items: list,
        job_fn: Callable[[Any, Callable[[], bool], Callable[[float, str], None]], Any],
        on_progress: Callable[[Any, float, str], None],
        on_item_done: Callable[[Any, Any], None],
        on_all_done: Callable[[], None],
        poll_ms: int = 150,
    ) -> None:
        """`job_fn(item, should_stop, report_progress) -> result` runs per item.

        `report_progress(fraction, speed)` may be called any number of times
        from inside `job_fn` (it's running on the worker thread); fraction
        of -1 means "only the speed/status text changed, leave the bar".
        """

        def make_reporter(item):
            return lambda fraction, speed="": self._msg_queue.put(("progress", item, (fraction, speed)))

        def worker() -> None:
            for item in items:
                if self.should_stop():
                    break
                try:
                    result = job_fn(item, self.should_stop, make_reporter(item))
                except Exception as exc:  # noqa: BLE001 - surfaced per-item, not swallowed
                    result = exc
                self._msg_queue.put(("item_done", item, result))
            self._msg_queue.put(("all_done", None, None))

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

        def poll() -> None:
            finished = False
            while True:
                try:
                    kind, item, data = self._msg_queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "progress":
                    fraction, speed = data
                    on_progress(item, fraction, speed)
                elif kind == "item_done":
                    on_item_done(item, data)
                elif kind == "all_done":
                    finished = True
            if finished:
                on_all_done()
            else:
                widget.after(poll_ms, poll)

        widget.after(poll_ms, poll)
