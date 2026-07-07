from sqlalchemy import inspect, text


def run_startup_migrations(engine) -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "organizer_jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("organizer_jobs")}
    migrations = {
        "mode": "ALTER TABLE organizer_jobs ADD COLUMN mode VARCHAR(30) DEFAULT 'template_based'",
        "source_id": "ALTER TABLE organizer_jobs ADD COLUMN source_id INTEGER",
        "reference_source_id": "ALTER TABLE organizer_jobs ADD COLUMN reference_source_id INTEGER",
        "reference_scope_prefix": "ALTER TABLE organizer_jobs ADD COLUMN reference_scope_prefix TEXT",
        "output_root": "ALTER TABLE organizer_jobs ADD COLUMN output_root TEXT",
        "filename_strategy": "ALTER TABLE organizer_jobs ADD COLUMN filename_strategy VARCHAR(80) DEFAULT 'preserve_source_filename'",
    }
    with engine.begin() as conn:
        if "app_settings" not in inspector.get_table_names():
            conn.execute(text(
                """
                CREATE TABLE app_settings (
                    id INTEGER NOT NULL PRIMARY KEY,
                    category VARCHAR(80) NOT NULL,
                    key VARCHAR(120) NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_app_settings_category ON app_settings (category)"))
            conn.execute(text("CREATE INDEX ix_app_settings_key ON app_settings (key)"))
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(text(statement))
        if "metadata" in inspector.get_table_names():
            metadata_columns = {column["name"] for column in inspector.get_columns("metadata")}
            metadata_migrations = {
                "plot": "ALTER TABLE metadata ADD COLUMN plot TEXT",
                "title_locked": "ALTER TABLE metadata ADD COLUMN title_locked BOOLEAN DEFAULT 0",
                "plot_locked": "ALTER TABLE metadata ADD COLUMN plot_locked BOOLEAN DEFAULT 0",
                "actors_locked": "ALTER TABLE metadata ADD COLUMN actors_locked BOOLEAN DEFAULT 0",
                "studio_locked": "ALTER TABLE metadata ADD COLUMN studio_locked BOOLEAN DEFAULT 0",
                "series_locked": "ALTER TABLE metadata ADD COLUMN series_locked BOOLEAN DEFAULT 0",
                "release_date_locked": "ALTER TABLE metadata ADD COLUMN release_date_locked BOOLEAN DEFAULT 0",
            }
            for column, statement in metadata_migrations.items():
                if column not in metadata_columns:
                    conn.execute(text(statement))
        table_names = set(inspector.get_table_names())
        if "organizer_execution_logs" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE organizer_execution_logs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    organizer_job_id INTEGER NOT NULL,
                    organizer_item_id INTEGER NOT NULL,
                    identifier VARCHAR(50),
                    source_path TEXT NOT NULL,
                    display_target_path TEXT NOT NULL,
                    container_target_path TEXT NOT NULL,
                    action VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    error_message TEXT,
                    executed_at DATETIME NOT NULL,
                    FOREIGN KEY(organizer_job_id) REFERENCES organizer_jobs (id) ON DELETE CASCADE,
                    FOREIGN KEY(organizer_item_id) REFERENCES organizer_items (id) ON DELETE CASCADE
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_organizer_execution_logs_job_id ON organizer_execution_logs (organizer_job_id)"))
            conn.execute(text("CREATE INDEX ix_organizer_execution_logs_item_id ON organizer_execution_logs (organizer_item_id)"))
            conn.execute(text("CREATE INDEX ix_organizer_execution_logs_status ON organizer_execution_logs (status)"))
            conn.execute(text("CREATE INDEX ix_organizer_execution_logs_identifier ON organizer_execution_logs (identifier)"))
        else:
            execution_columns = {column["name"] for column in inspector.get_columns("organizer_execution_logs")}
            if "identifier" not in execution_columns:
                conn.execute(text("ALTER TABLE organizer_execution_logs ADD COLUMN identifier VARCHAR(50)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_organizer_execution_logs_identifier ON organizer_execution_logs (identifier)"))
        table_names = set(inspector.get_table_names())
        if "translation_watch_folders" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE translation_watch_folders (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    folder_path TEXT NOT NULL UNIQUE,
                    prompt_template TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    recursive BOOLEAN NOT NULL DEFAULT 1,
                    auto_translate BOOLEAN NOT NULL DEFAULT 0,
                    monitor_initialized BOOLEAN NOT NULL DEFAULT 0,
                    last_scan_at DATETIME,
                    last_error TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_translation_watch_folders_name ON translation_watch_folders (name)"))
            conn.execute(text("CREATE INDEX ix_translation_watch_folders_enabled ON translation_watch_folders (enabled)"))
            conn.execute(text("CREATE INDEX ix_translation_watch_folders_auto_translate ON translation_watch_folders (auto_translate)"))
        else:
            watch_columns = {column["name"] for column in inspector.get_columns("translation_watch_folders")}
            watch_migrations = {
                "recursive": "ALTER TABLE translation_watch_folders ADD COLUMN recursive BOOLEAN NOT NULL DEFAULT 1",
                "auto_translate": "ALTER TABLE translation_watch_folders ADD COLUMN auto_translate BOOLEAN NOT NULL DEFAULT 0",
                "monitor_initialized": "ALTER TABLE translation_watch_folders ADD COLUMN monitor_initialized BOOLEAN NOT NULL DEFAULT 0",
                "last_scan_at": "ALTER TABLE translation_watch_folders ADD COLUMN last_scan_at DATETIME",
                "last_error": "ALTER TABLE translation_watch_folders ADD COLUMN last_error TEXT",
            }
            for column, statement in watch_migrations.items():
                if column not in watch_columns:
                    conn.execute(text(statement))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_translation_watch_folders_auto_translate ON translation_watch_folders (auto_translate)"))
        if "translation_api_settings" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE translation_api_settings (
                    id INTEGER NOT NULL PRIMARY KEY,
                    provider_name VARCHAR(80) NOT NULL DEFAULT 'openai-compatible',
                    enabled BOOLEAN NOT NULL DEFAULT 0,
                    api_key TEXT,
                    base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
                    model_name VARCHAR(120) NOT NULL DEFAULT 'gpt-4.1-mini',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            ))
        if "translation_jobs" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE translation_jobs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    watch_folder_id INTEGER,
                    folder_path TEXT NOT NULL,
                    prompt_template TEXT NOT NULL,
                    mode VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    translated_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(watch_folder_id) REFERENCES translation_watch_folders (id) ON DELETE SET NULL
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_translation_jobs_watch_folder_id ON translation_jobs (watch_folder_id)"))
            conn.execute(text("CREATE INDEX ix_translation_jobs_status ON translation_jobs (status)"))
            conn.execute(text("CREATE INDEX ix_translation_jobs_mode ON translation_jobs (mode)"))
        if "translation_items" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE translation_items (
                    id INTEGER NOT NULL PRIMARY KEY,
                    job_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    source_title TEXT,
                    source_plot TEXT,
                    translated_title TEXT,
                    translated_plot TEXT,
                    source_title_field VARCHAR(40),
                    source_plot_field VARCHAR(40),
                    status VARCHAR(20) NOT NULL,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES translation_jobs (id) ON DELETE CASCADE
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_translation_items_job_id ON translation_items (job_id)"))
            conn.execute(text("CREATE INDEX ix_translation_items_status ON translation_items (status)"))
            conn.execute(text("CREATE INDEX ix_translation_items_file_path ON translation_items (file_path)"))
        table_names = set(inspector.get_table_names())
        if "translation_file_states" not in table_names:
            conn.execute(text(
                """
                CREATE TABLE translation_file_states (
                    id INTEGER NOT NULL PRIMARY KEY,
                    watch_folder_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    modified_time DATETIME,
                    size INTEGER NOT NULL DEFAULT 0,
                    last_job_id INTEGER,
                    last_status VARCHAR(20) NOT NULL DEFAULT 'seen',
                    last_seen_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(watch_folder_id) REFERENCES translation_watch_folders (id) ON DELETE CASCADE,
                    FOREIGN KEY(last_job_id) REFERENCES translation_jobs (id) ON DELETE SET NULL
                )
                """
            ))
            conn.execute(text("CREATE INDEX ix_translation_file_states_watch_folder_id ON translation_file_states (watch_folder_id)"))
            conn.execute(text("CREATE INDEX ix_translation_file_states_last_status ON translation_file_states (last_status)"))
