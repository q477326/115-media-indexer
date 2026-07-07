from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.config import settings, validate_safety_flags
from app.core.database import Base, engine
from app.core.migrations import run_startup_migrations
from app.metadata_providers.registry import validate_provider_registry
from app.services.startup_recovery import recover_orphaned_jobs
from app.services.translation_monitor import translation_monitor
from app import models  # noqa: F401


def create_app() -> FastAPI:
    validate_safety_flags(settings)
    validate_provider_registry()
    database_path = settings.database_url.removeprefix("sqlite:///")
    if settings.database_url.startswith("sqlite:///"):
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_startup_migrations(engine)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.on_event("startup")
    def start_translation_monitor() -> None:
        recover_orphaned_jobs()
        translation_monitor.start()

    @app.on_event("shutdown")
    def stop_translation_monitor() -> None:
        translation_monitor.stop()

    return app


app = create_app()
