from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.scanner import scan_source


class ScanManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=settings.scan_workers, thread_name_prefix="media-scan")
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
            scan_source(db, job_id, event)

    def _forget(self, job_id: int) -> None:
        with self._lock:
            self._events.pop(job_id, None)


scan_manager = ScanManager()
