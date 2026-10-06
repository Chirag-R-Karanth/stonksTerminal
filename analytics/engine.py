from __future__ import annotations

import collections
import json
import logging
import os
import select
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_WORKER = Path(__file__).resolve().parent / "r" / "worker.R"


class AnalyticsError(RuntimeError):
    pass


class AnalyticsUnavailable(AnalyticsError):
    pass


class AnalyticsTimeout(AnalyticsError):
    pass


class AnalyticsEngine:
    def __init__(self, rscript: str = "Rscript", timeout: float = 30.0, r_libs: str | None = None):
        self.rscript = rscript
        self.timeout = timeout
        self.r_libs = r_libs
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=50)
        self._stderr_thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        if shutil.which(self.rscript) is None:
            return False
        try:
            result = self.call("ping")
            return isinstance(result, dict) and result.get("status") == "ok"
        except AnalyticsError:
            return False

    def call(self, op: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        with self._lock:
            errors: list[str] = []
            for attempt in range(2):
                try:
                    return self._call_once(op, params, timeout)
                except (AnalyticsUnavailable, AnalyticsTimeout) as exc:
                    errors.append(str(exc))
                    self._stop()
                except AnalyticsError:
                    raise
            raise AnalyticsUnavailable("; ".join(errors) or "R analytics engine unavailable")

    def shutdown(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    payload = json.dumps({"id": -1, "op": "shutdown", "params": {}})
                    self._proc.stdin.write(payload + "\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            self._stop()

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.r_libs:
            env["FT_R_LIBS"] = self.r_libs
        return env

    def _start(self) -> None:
        if shutil.which(self.rscript) is None:
            raise AnalyticsUnavailable(f"Rscript not found ({self.rscript}); R analytics disabled")
        try:
            self._proc = subprocess.Popen(
                [self.rscript, "--vanilla", str(_WORKER)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._env(),
                cwd=str(_WORKER.parent),
            )
        except OSError as exc:
            raise AnalyticsUnavailable(f"failed to start R analytics worker: {exc}") from exc
        self._stderr_tail.clear()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        log.info("R analytics worker started (pid=%s)", self._proc.pid)

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr_tail.append(line.rstrip())

    def _stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)
        except Exception:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    def _stderr_text(self) -> str:
        if not self._stderr_tail:
            return ""
        return " | ".join(list(self._stderr_tail)[-3:])

    def _call_once(self, op: str, params: dict[str, Any] | None, timeout: float | None) -> Any:
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        assert self._proc is not None and self._proc.stdout is not None
        self._next_id += 1
        req_id = self._next_id
        payload = json.dumps({"id": req_id, "op": op, "params": params or {}})
        try:
            self._proc.stdin.write(payload + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AnalyticsUnavailable(f"R analytics worker pipe closed: {self._stderr_text()}") from exc

        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop()
                raise AnalyticsTimeout(
                    f"R analytics op '{op}' timed out: {self._stderr_text() or 'no response'}"
                )
            ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.5))
            if not ready:
                if self._proc.poll() is not None:
                    raise AnalyticsUnavailable(
                        f"R analytics worker exited: {self._stderr_text() or 'unknown error'}"
                    )
                continue
            line = self._proc.stdout.readline()
            if not line:
                raise AnalyticsUnavailable(
                    f"R analytics worker closed stdout: {self._stderr_text() or 'unknown error'}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                log.warning("non-json output from R worker: %.200s", line)
                continue
            if message.get("id") != req_id:
                continue
            if message.get("ok"):
                return message.get("result")
            raise AnalyticsError(str(message.get("error") or "R analytics error"))
