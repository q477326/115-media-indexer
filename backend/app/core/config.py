import os
from pathlib import Path


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 必须是 true 或 false")


class Settings:
    app_name = "115 Media Indexer"
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/index.db")
    allowed_scan_roots = tuple(
        Path(item.strip()).resolve()
        for item in os.getenv("ALLOWED_SCAN_ROOTS", "/mnt/clouddrive").split(",")
        if item.strip()
    )
    scan_batch_size = max(1, int(os.getenv("SCAN_BATCH_SIZE", "250")))
    scan_workers = max(1, int(os.getenv("SCAN_WORKERS", "2")))
    read_only_mode = env_bool("READ_ONLY_MODE", True)
    enable_remote_write = env_bool("ENABLE_REMOTE_WRITE", False)
    enable_external_metadata = env_bool("ENABLE_EXTERNAL_METADATA", False)
    enable_real_move = env_bool("ENABLE_REAL_MOVE", False)
    enable_ai_translation = env_bool("ENABLE_AI_TRANSLATION", False)
    cms_sync_url = os.getenv("CMS_SYNC_URL", "").strip()
    cms_sync_timeout_seconds = max(3, int(os.getenv("CMS_SYNC_TIMEOUT_SECONDS", "30")))
    ai_translation_api_key = os.getenv("AI_TRANSLATION_API_KEY", "").strip()
    ai_translation_base_url = os.getenv("AI_TRANSLATION_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    ai_translation_model = os.getenv("AI_TRANSLATION_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    translation_monitor_interval_seconds = max(10, int(os.getenv("TRANSLATION_MONITOR_INTERVAL_SECONDS", "60")))
    translation_monitor_max_jobs_per_scan = max(1, int(os.getenv("TRANSLATION_MONITOR_MAX_JOBS_PER_SCAN", "20")))
    clouddrive_host_root = os.getenv("CLOUDDRIVE_HOST_ROOT", os.getenv("CLOUDDRIVE_MOUNT_PATH", "./sample-media"))
    clouddrive_container_root = os.getenv("CLOUDDRIVE_CONTAINER_ROOT", "/mnt/clouddrive")
    reference_container_root = os.getenv("REFERENCE_STRM_CONTAINER_ROOT", "/mnt/reference-strm")
    local_media_container_root = os.getenv("LOCAL_MEDIA_CONTAINER_ROOT", "/mnt/local-media")
    allowed_translation_roots = tuple(
        Path(item.strip()).resolve()
        for item in os.getenv(
            "ALLOWED_TRANSLATION_ROOTS",
            f"{local_media_container_root},{reference_container_root},{clouddrive_container_root}",
        ).split(",")
        if item.strip()
    )


def validate_safety_flags(config) -> None:
    errors = []
    if config.enable_external_metadata is not False:
        errors.append("ENABLE_EXTERNAL_METADATA 必须为 false")
    if config.enable_real_move and config.read_only_mode is True:
        errors.append("ENABLE_REAL_MOVE=true 时 READ_ONLY_MODE 必须为 false")
    if config.enable_real_move and config.enable_remote_write is not True:
        errors.append("ENABLE_REAL_MOVE=true 时 ENABLE_REMOTE_WRITE 必须为 true")
    if errors:
        raise RuntimeError("不安全的启动配置：" + "；".join(errors))


settings = Settings()
