"""Generic background batch-job runner shared by the video/photo/archive
job wiring in api.py.

Runs a list of items through `job_fn` sequentially on a worker thread,
writing progress into a plain dict that the UI polls (`snapshot()`).
Simple dict/list mutation from one writer thread, read by the polling
caller, is safe under the GIL without extra locking — the same pattern
the old Tkinter build used for its background threading.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Optional

from squeeze.core.format import human_size


class Runner:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state: dict[str, Any] = {"running": False, "rows": [], "overall": ""}

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def cancel(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return bool(self._state.get("running"))

    def start(
        self,
        items: list,
        key_fn: Callable[[Any], str],
        job_fn: Callable[[Any, Callable[[], bool], Callable[[float, str], None]], Any],
    ) -> None:
        """`job_fn(item, should_stop, report) -> CompressResult`. `report`
        follows the same convention the old GUI used: fraction in [0, 1]
        updates the progress %, fraction -1 updates just the speed/status
        suffix, fraction -2 replaces the status text (e.g. "Probing…").
        """
        self._stop_event = threading.Event()
        rows = [
            {"key": key_fn(it), "name": os.path.basename(key_fn(it)), "status": "Queued", "progress": "", "saved": ""}
            for it in items
        ]
        row_by_key = {r["key"]: r for r in rows}
        self._state = {"running": True, "rows": rows, "overall": f"Processing {len(items)} file(s)…"}

        def worker() -> None:
            total_in = 0
            total_out = 0
            for item in items:
                if self.should_stop():
                    break
                key = key_fn(item)
                row = row_by_key[key]
                row["status"] = "Compressing…"

                def report(fraction: float, speed: str = "", _row=row) -> None:
                    if fraction == -2:
                        _row["status"] = speed
                    elif fraction >= 0:
                        _row["progress"] = f"{fraction * 100:.0f}%" + (f" ({speed})" if speed else "")
                    elif speed:
                        base = _row["progress"].split(" (")[0]
                        _row["progress"] = f"{base} ({speed})" if base else speed

                try:
                    result = job_fn(item, self.should_stop, report)
                except Exception as exc:  # noqa: BLE001 - surfaced per-row, not swallowed
                    row["status"] = "Failed"
                    row["progress"] = str(exc)[:160]
                    continue

                if not result.success:
                    row["status"] = "Cancelled" if result.message == "Cancelled" else "Failed"
                    row["progress"] = "" if result.message == "Cancelled" else result.message[:160]
                else:
                    # A success message starting with "Done" is a richer
                    # status the job wants shown (e.g. "Done (software
                    # fallback)" when the hw encoder didn't work out).
                    message = getattr(result, "message", "")
                    row["status"] = message if message.startswith("Done") else "Done"
                    row["progress"] = "100%"
                    row["saved"] = f"{human_size(result.saved_bytes)} ({result.saved_percent:.0f}%)"
                    total_in += result.input_size
                    total_out += result.output_size

            self._state["running"] = False
            if self.should_stop():
                self._state["overall"] = "Cancelled."
            elif total_in > 0:
                # Batch total, the way Caesium/HandBrake surface it —
                # only successful files count toward it.
                saved_pct = 100 * (total_in - total_out) / total_in
                self._state["overall"] = (
                    f"Done — {human_size(total_in)} → {human_size(total_out)} "
                    f"(saved {saved_pct:.0f}%)"
                )
            else:
                self._state["overall"] = "Done."

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def snapshot(self) -> dict:
        return {
            "running": self._state.get("running", False),
            "rows": list(self._state.get("rows", [])),
            "overall": self._state.get("overall", ""),
        }
