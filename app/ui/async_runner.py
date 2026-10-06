from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from app.ui.gtk import GLib

log = logging.getLogger(__name__)

Callback = Callable[[Any], None]


class AsyncRunner:
    def __init__(self, on_busy: Callable[[bool], None] | None = None):
        self._queue: queue.Queue[tuple[Callable[[], Any], Callback | None] | None] = queue.Queue()
        self._on_busy = on_busy
        self._busy = False
        self._thread = threading.Thread(target=self._worker, name="ft-worker", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, fn: Callable[[], Any], callback: Callback | None = None) -> None:
        self._queue.put((fn, callback))

    def stop(self) -> None:
        self._queue.put(None)

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            if self._on_busy:
                GLib.idle_add(self._on_busy, value)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            fn, callback = item
            self._set_busy(True)
            result: Any = None
            try:
                result = fn()
            except Exception as exc:
                log.exception("async task failed")
                result = exc
            if callback is not None:
                GLib.idle_add(self._deliver, callback, result)
            self._set_busy(False)

    @staticmethod
    def _deliver(callback: Callback, result: Any) -> bool:
        try:
            callback(result)
        except Exception:
            log.exception("async callback failed")
        return False
