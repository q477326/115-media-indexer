from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from app.core.database import SessionLocal
from app.services.metadata_aggregator import run_enrichment_job


class MetadataTaskManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="metadata-enrichment")
        self._events: dict[int, Event] = {}
        self._lock = Lock()

    def start(self, job_id: int) -> None:
        event = Event()
        with self._lock:
            self._events[job_id] = event
        future = self._executor.submit(self._run, job_id, event)
        future.add_done_callback(lambda _future: self._forget(job_id))

    def stop(self, job_id: int) -> bool:
        with self._lock:
            event = self._events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def _run(self, job_id: int, event: Event) -> None:
        with SessionLocal() as db:
            run_enrichment_job(db, job_id, event)

    def _forget(self, job_id: int) -> None:
        with self._lock:
            self._events.pop(job_id, None)


metadata_task_manager = MetadataTaskManager()
