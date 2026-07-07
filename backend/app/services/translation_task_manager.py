from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from app.core.database import SessionLocal
from app.services.nfo_translation import run_translation_file_job, run_translation_job


class TranslationTaskManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-translation")
        self._events: dict[int, Event] = {}
        self._lock = Lock()

    def start(self, job_id: int, file_path: str | None = None) -> None:
        event = Event()
        with self._lock:
            self._events[job_id] = event
        future = self._executor.submit(self._run, job_id, event, file_path)
        future.add_done_callback(lambda _future: self._forget(job_id))

    def stop(self, job_id: int) -> bool:
        with self._lock:
            event = self._events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def _run(self, job_id: int, event: Event, file_path: str | None = None) -> None:
        with SessionLocal() as db:
            if file_path:
                run_translation_file_job(db, job_id, file_path, event)
            else:
                run_translation_job(db, job_id, event)

    def _forget(self, job_id: int) -> None:
        with self._lock:
            self._events.pop(job_id, None)


translation_task_manager = TranslationTaskManager()
