from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    tool: str
    status: str = "queued"
    progress: str = ""
    result: Any = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    future: Future | None = field(default=None, repr=False)

    @property
    def done(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return round((self.finished or time.time()) - self.started, 1)

    def view(self, with_result: bool = True) -> dict:
        data = {"job_id": self.id, "tool": self.tool, "status": self.status,
                "progress": self.progress, "seconds": self.elapsed()}
        if self.error:
            data["error"] = self.error
        if with_result and self.status == "done":
            data["result"] = self.result
        return data


class JobQueue:
    def __init__(self, workers: int = 1):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mt5-tester")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, tool: str, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], tool=tool)
        with self._lock:
            self._jobs[job.id] = job
        job.future = self._executor.submit(self._run, job, work)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown job {job_id!r}")
            return self._jobs[job_id]

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job.future and job.future.cancel():
            job.status, job.finished = "cancelled", time.time()
            return True
        return False

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    @staticmethod
    def _run(job: Job, work: Callable[[Job], Any]) -> Any:
        job.status, job.started = "running", time.time()
        try:
            job.result = work(job)
            job.status = "done"
            return job.result
        except Exception as exc:
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            job.finished = time.time()
