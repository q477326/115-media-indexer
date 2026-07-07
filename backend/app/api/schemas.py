from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class SourceCreate(BaseModel):
    name: str
    provider_type: Literal["local_fs", "p115"] = "local_fs"
    root_path: str | None = None
    root_file_id: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_root(self):
        if self.provider_type == "local_fs" and not self.root_path:
            raise ValueError("local_fs 必须配置 root_path")
        if self.provider_type == "p115" and not self.root_file_id:
            raise ValueError("p115 必须配置 root_file_id")
        return self


class SourceRead(SourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class WesternPosterRunRequest(BaseModel):
    root: str
    state_file: str | None = None
    process_all: bool = False
    dry_run: bool = True


class WesternPosterResult(BaseModel):
    root: str
    state_file: str
    processed: int
    skipped: int
    dry_run: int
    touched: list[str]
    process_all: bool
    dry_run_mode: bool


class OrganizerTaskDefaults(BaseModel):
    source_root: str
    output_root: str
    reference_scope_prefix: str


class OneClickIngestDefaults(BaseModel):
    source_root: str
    output_root: str


class TranslationDefaults(BaseModel):
    name: str
    folder_path: str
    prompt_template: str
    enabled: bool
    recursive: bool
    auto_translate: bool


class NfoTagDefaults(BaseModel):
    folder_path: str
    search_type: str


class WesternPosterDefaults(BaseModel):
    root: str
    state_file: str
    process_all: bool
    dry_run: bool


class AppSettingsRead(BaseModel):
    organizer_task: OrganizerTaskDefaults
    one_click_ingest: OneClickIngestDefaults
    translation_defaults: TranslationDefaults
    nfo_tag_defaults: NfoTagDefaults
    western_poster_defaults: WesternPosterDefaults


class AppSettingsUpdate(AppSettingsRead):
    pass


class ReferenceSourceCreate(BaseModel):
    name: str
    provider_type: Literal["local_strm"] = "local_strm"
    root_path: str
    enabled: bool = True


class ReferenceSourceRead(ReferenceSourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class ReferenceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    identifier: str | None
    reference_path: str
    reference_dir: str
    filename: str
    ext: str
    size: int
    modified_time: datetime | None
    status: Literal["identified", "unidentified", "duplicate"]
    created_at: datetime
    updated_at: datetime


class ReferenceItemPage(BaseModel):
    items: list[ReferenceItemRead]
    total: int
    page: int
    page_size: int


class ReferenceScanResult(BaseModel):
    source_id: int
    scanned_count: int
    identified_count: int
    unidentified_count: int
    duplicate_count: int
    error_count: int


class MetadataSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    identifier: str
    title: str | None
    plot: str | None
    actors: list[str]
    studio: str | None
    cover_url: str | None


class MediaFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    provider: str
    provider_file_id: str | None
    local_path: str | None
    filename: str
    path: str
    size: int
    modified_time: datetime | None
    identifier: str | None
    status: str
    indexed_at: datetime
    metadata: MetadataSummary | None = None


class FilePage(BaseModel):
    items: list[MediaFileRead]
    total: int
    page: int
    page_size: int


class ScanJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    scanned_count: int
    identified_count: int
    unidentified_count: int
    error_count: int
    error_message: str | None


class StatsRead(BaseModel):
    total: int
    identified: int
    unidentified: int
    missing: int
    last_scan_at: datetime | None


class MetadataRead(MetadataSummary):
    id: int
    series: str | None
    release_date: date | None
    title_locked: bool
    plot_locked: bool
    actors_locked: bool
    studio_locked: bool
    series_locked: bool
    release_date_locked: bool
    source: str
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime


class MetadataPage(BaseModel):
    items: list[MetadataRead]
    total: int
    page: int
    page_size: int


class AssociatedFile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    path: str
    size: int
    status: str


class MetadataDetail(MetadataRead):
    files: list[AssociatedFile]


class MetadataImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[dict[str, str | int]]


class MetadataEnrichmentJobCreate(BaseModel):
    scope: Literal["missing", "partial", "selected"] = "missing"
    identifiers: list[str] = []
    providers: list[str] = []

    @model_validator(mode="after")
    def validate_selected(self):
        if self.scope == "selected" and not self.identifiers:
            raise ValueError("selected 任务必须提供 identifiers")
        return self


class MetadataReferenceHarvestCreate(BaseModel):
    reference_source_id: int
    reference_scope_prefix: str | None = None
    providers: list[str] = ["reference_metadata", "local_nfo"]


class MetadataEnrichmentJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    scope: str
    provider_names: list[str]
    total_count: int
    processed_count: int
    completed_count: int
    unchanged_count: int
    failed_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class MetadataTaskLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    identifier: str
    provider: str
    status: str
    duration_ms: int
    error_message: str | None
    attempt: int
    score: float | None
    created_at: datetime


class MetadataTaskLogPage(BaseModel):
    items: list[MetadataTaskLogRead]
    total: int
    page: int
    page_size: int


class ActorCollectionItem(BaseModel):
    actor: str
    file_count: int
    identifier_count: int
    latest_release_date: date | None
    cover_url: str | None


class StudioCollectionItem(BaseModel):
    studio: str
    file_count: int
    identifier_count: int
    latest_release_date: date | None
    cover_url: str | None


class SeriesCollectionItem(BaseModel):
    series: str
    file_count: int
    identifier_count: int
    latest_release_date: date | None
    cover_url: str | None


class ActorCollectionPage(BaseModel):
    items: list[ActorCollectionItem]
    total: int
    page: int
    page_size: int


class StudioCollectionPage(BaseModel):
    items: list[StudioCollectionItem]
    total: int
    page: int
    page_size: int


class SeriesCollectionPage(BaseModel):
    items: list[SeriesCollectionItem]
    total: int
    page: int
    page_size: int


class CollectionFileRead(BaseModel):
    id: int
    filename: str
    path: str
    identifier: str
    title: str | None
    actors: list[str]
    studio: str | None
    series: str | None
    size: int


class CollectionFilePage(BaseModel):
    items: list[CollectionFileRead]
    total: int
    page: int
    page_size: int


class MountStatus(BaseModel):
    path: str
    readable: bool
    error: str | None = None


class SystemStatusRead(BaseModel):
    backend_status: str
    sqlite_status: str
    sqlite_error: str | None = None
    mount_readable: bool
    mounts: list[MountStatus]
    source_count: int
    last_scan_at: datetime | None
    read_only_mode: bool
    enable_remote_write: bool
    enable_external_metadata: bool
    enable_real_move: bool
    cms_sync_configured: bool


class OrganizerJobCreate(BaseModel):
    mode: Literal["template_based", "reference_based"] = "template_based"
    rule_template: str = "{prefix}/{identifier}/{filename}"
    scope: Literal["all", "identified", "with_metadata", "missing_metadata"] = "all"
    source_id: int | None = None
    reference_source_id: int | None = None
    reference_scope_prefix: str = "骑兵/"
    output_root: str | None = None
    filename_strategy: Literal["preserve_source_filename", "match_reference_filename_with_source_suffix"] = "match_reference_filename_with_source_suffix"

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "reference_based":
            if self.source_id is None:
                raise ValueError("reference_based requires source_id")
            if self.reference_source_id is None:
                raise ValueError("reference_based requires reference_source_id")
            if not self.reference_scope_prefix or not self.reference_scope_prefix.strip():
                raise ValueError("reference_scope_prefix cannot be empty")
            if not self.output_root or not self.output_root.strip():
                raise ValueError("reference_based requires output_root")
        return self


class OrganizerJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_template: str
    scope: str
    mode: str
    source_id: int | None
    reference_source_id: int | None
    reference_scope_prefix: str | None
    output_root: str | None
    filename_strategy: str | None
    status: str
    total_count: int
    processed_count: int
    status_counts: dict[str, int]
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class OrganizerItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    media_file_id: int
    source_path: str
    target_path: str | None
    identifier: str | None
    rule_template: str
    status: Literal["ready", "missing_metadata", "missing_reference", "duplicate_reference", "unidentified", "conflict", "invalid_path", "skipped"]
    error_message: str | None
    created_at: datetime


class OrganizerItemPage(BaseModel):
    items: list[OrganizerItemRead]
    total: int
    page: int
    page_size: int


class OrganizerExecuteRequest(BaseModel):
    status_filter: Literal["ready"] = "ready"
    limit: int = 10
    mode: Literal["move", "preflight"] = "preflight"
    confirm: bool = False

    @model_validator(mode="after")
    def validate_execute(self):
        if self.limit < 1 or self.limit > 5000:
            raise ValueError("当前阶段 limit 只能在 1 到 5000 之间")
        if self.mode == "move" and self.confirm is not True:
            raise ValueError("真实执行必须传 confirm=true")
        if self.mode == "preflight" and self.confirm is not False:
            raise ValueError("preflight 必须传 confirm=false")
        return self


class OrganizerExecutionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organizer_job_id: int
    organizer_item_id: int
    identifier: str | None
    source_path: str
    display_target_path: str
    container_target_path: str
    action: str
    status: Literal["pending", "moved", "skipped", "failed"]
    error_message: str | None
    executed_at: datetime


class OrganizerExecutionLogPage(BaseModel):
    items: list[OrganizerExecutionLogRead]
    total: int
    page: int
    page_size: int


class OrganizerExecutionResult(BaseModel):
    organizer_job_id: int
    requested_count: int
    moved_count: int
    skipped_count: int
    failed_count: int
    moved_samples: list[OrganizerExecutionLogRead]
    failed_samples: list[OrganizerExecutionLogRead]
    rollback_hint: str


class OrganizerPreflightItemRead(BaseModel):
    organizer_item_id: int
    identifier: str | None
    source_path: str
    display_target_path: str
    container_target_path: str
    source_exists: bool
    target_exists: bool
    status: Literal["passed", "failed"]
    error_message: str | None


class OrganizerPreflightResult(BaseModel):
    organizer_job_id: int
    requested_count: int
    passed_count: int
    failed_count: int
    items: list[OrganizerPreflightItemRead]


class OrganizerTaskScanRequest(BaseModel):
    source_root: str
    name: str | None = None


class OrganizerTaskScanResponse(BaseModel):
    source: SourceRead
    scan_job: ScanJobRead


class OrganizerTaskJobCreate(BaseModel):
    source_root: str
    output_root: str
    reference_scope_prefix: str = "骑兵/"
    reference_source_id: int | None = None
    batch_limit: int = 100

    @model_validator(mode="after")
    def validate_payload(self):
        if not self.source_root.strip():
            raise ValueError("source_root 不能为空")
        if not self.output_root.strip():
            raise ValueError("output_root 不能为空")
        if not self.reference_scope_prefix.strip():
            raise ValueError("reference_scope_prefix 不能为空")
        if self.batch_limit < 1 or self.batch_limit > 5000:
            raise ValueError("batch_limit 只能在 1 到 5000 之间")
        return self


class OrganizerTaskSummaryRead(BaseModel):
    organizer_job_id: int
    source_id: int
    source_root: str
    output_root: str
    reference_source_id: int
    reference_scope_prefix: str
    status: str
    scanned_count: int
    identified_count: int
    ready_count: int
    moved_count: int
    remaining_ready_count: int
    missing_reference_count: int
    unidentified_count: int
    conflict_count: int
    failed_count: int
    read_only_mode: bool
    enable_remote_write: bool
    enable_real_move: bool


class CmsSyncResult(BaseModel):
    ok: bool
    status_code: int | None
    message: str
    response_text: str | None
    triggered_at: datetime


class OneClickIngestRequest(BaseModel):
    source_root: str = "/mnt/clouddrive/115open/云下载"
    output_root: str = "/mnt/clouddrive/115open/原始库/不正常视频/qb/骑兵/洗版"


class OneClickIngestPreviewRead(BaseModel):
    rename_count: int
    move_to_root_count: int
    delete_count: int
    remove_dir_count: int


class OneClickIngestOrganizeRead(BaseModel):
    root: str
    rename_count: int
    delete_count: int
    dir_cleanup_count: int
    conflict_count: int
    renamed: list[dict]
    deleted: list[str]
    removed_dirs: list[str]
    conflicts: list[dict]


class OneClickIngestMoveItemRead(BaseModel):
    ok: bool
    file: str
    from_: str | None = None
    to: str | None = None
    error: str | None = None


class OneClickIngestMoveRead(BaseModel):
    source_root: str
    target_root: str
    moved_count: int
    failed_count: int
    items: list[dict]


class OneClickIngestResult(BaseModel):
    source_root: str
    output_root: str
    preview: OneClickIngestPreviewRead
    organize: OneClickIngestOrganizeRead
    move: OneClickIngestMoveRead
    cms_sync: CmsSyncResult | None = None


class TranslationWatchFolderCreate(BaseModel):
    name: str
    folder_path: str
    prompt_template: str
    enabled: bool = True
    recursive: bool = True
    auto_translate: bool = False


class TranslationWatchFolderRead(TranslationWatchFolderCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    monitor_initialized: bool
    last_scan_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TranslationJobCreate(BaseModel):
    watch_folder_id: int | None = None
    folder_path: str | None = None
    prompt_template: str | None = None
    mode: Literal["analyze", "translate"] = "analyze"

    @model_validator(mode="after")
    def validate_payload(self):
        if self.watch_folder_id is None:
            if not self.folder_path or not self.folder_path.strip():
                raise ValueError("folder_path 不能为空")
            if not self.prompt_template or not self.prompt_template.strip():
                raise ValueError("prompt_template 不能为空")
        return self


class TranslationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    watch_folder_id: int | None
    folder_path: str
    prompt_template: str
    mode: str
    status: str
    total_count: int
    processed_count: int
    translated_count: int
    skipped_count: int
    failed_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TranslationItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    file_path: str
    source_title: str | None
    source_plot: str | None
    translated_title: str | None
    translated_plot: str | None
    source_title_field: str | None
    source_plot_field: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TranslationItemPage(BaseModel):
    items: list[TranslationItemRead]
    total: int
    page: int
    page_size: int


class TranslationFileSearchRead(BaseModel):
    file_path: str
    filename: str
    identifier: str | None
    parent_path: str
    last_item_status: str | None = None
    last_item_updated_at: datetime | None = None


class TranslationFileSearchPage(BaseModel):
    items: list[TranslationFileSearchRead]
    total: int
    page: int
    page_size: int


class TranslationSingleFileRunRequest(BaseModel):
    file_path: str
    watch_folder_id: int | None = None
    prompt_template: str | None = None
    mode: Literal["analyze", "translate"] = "translate"

    @model_validator(mode="after")
    def validate_payload(self):
        if self.watch_folder_id is None:
            if not self.prompt_template or not self.prompt_template.strip():
                raise ValueError("prompt_template 不能为空")
        return self


class NfoTagSearchRead(BaseModel):
    file_path: str
    filename: str
    identifier: str | None
    title: str | None
    originaltitle: str | None
    raw_tags: list[str]


class NfoTagSearchPage(BaseModel):
    items: list[NfoTagSearchRead]
    total: int
    page: int
    page_size: int


class NfoTagBatchAddRequest(BaseModel):
    file_paths: list[str]
    tag_name: str


class NfoTagBatchAddItem(BaseModel):
    file_path: str
    status: str
    error_message: str | None = None


class NfoTagBatchAddResult(BaseModel):
    matched_count: int
    added_count: int
    skipped_count: int
    items: list[NfoTagBatchAddItem]


class TranslationRuntimeRead(BaseModel):
    read_only_mode: bool
    enable_remote_write: bool
    enable_ai_translation: bool
    ai_translation_configured: bool
    allowed_translation_roots: list[str]


class TranslationAPISettingsUpdate(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4.1-mini"


class TranslationAPISettingsRead(BaseModel):
    provider_name: str
    enabled: bool
    has_api_key: bool
    api_key_masked: str
    base_url: str
    model_name: str


class TranslationConnectionTestRequest(BaseModel):
    enabled: bool = True
    api_key: str
    base_url: str
    model_name: str


class TranslationConnectionTestRead(BaseModel):
    ok: bool
    provider_name: str
    base_url: str
    model_name: str
    message: str
