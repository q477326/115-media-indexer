from concurrent.futures import ThreadPoolExecutor

from app.core.database import SessionLocal
from app.services.organizer import run_organizer_job


class OrganizerManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="organizer-dry-run")

    def start(self, job_id: int) -> None:
        self._executor.submit(self._run, job_id)

    @staticmethod
    def _run(job_id: int) -> None:
        with SessionLocal() as db:
            run_organizer_job(db, job_id)


organizer_manager = OrganizerManager()
