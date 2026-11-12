"""Runs slow work off the request thread, so a webhook can acknowledge at once."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from functools import partial

logger = logging.getLogger(__name__)

Task = Callable[[], object]


class BackgroundRunner:
    """A small thread pool where tasks that share a key run one at a time, in order.

    Different keys run in parallel. Tasks are in memory only: one that is waiting
    or running when the process stops is lost, which is why callers persist their
    input before submitting.
    """

    def __init__(self, workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="citabot-worker")
        self._pending: set[Future[None]] = set()
        self._queues: dict[Hashable, deque[Task]] = {}
        self._guard = threading.Lock()

    def submit(self, task: Task, key: Hashable) -> None:
        with self._guard:
            queue = self._queues.get(key)
            if queue is not None:  # a worker is already draining this key
                queue.append(task)
                return
            self._queues[key] = deque([task])
            future = self._pool.submit(partial(self._drain, key))
            self._pending.add(future)
        future.add_done_callback(self._finished)

    def _drain(self, key: Hashable) -> None:
        while True:
            with self._guard:
                queue = self._queues[key]
                if not queue:
                    del self._queues[key]
                    return
                task = queue.popleft()
            try:
                task()
            except Exception:  # one failed task must not drop the ones queued behind it
                logger.exception("Falló una tarea en segundo plano")

    def _finished(self, future: Future[None]) -> None:
        with self._guard:
            self._pending.discard(future)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until every submitted task has finished. Returns False on timeout."""
        with self._guard:
            pending = list(self._pending)
        return not wait(pending, timeout).not_done

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
