# 第一阶段架构

```text
Browser -> Nginx/Vue -> FastAPI -> SQLAlchemy -> SQLite
                              |
                              +-> Provider abstraction
                                    +-> local_fs (implemented, metadata only)
                                    +-> p115 (mock only)
```

`media_files` 保存 provider、provider_file_id、local_path、path、filename、size、modified_time、番号及索引状态。`sources` 使用 `provider_type` 区分 `local_fs` 与 `p115`，二者分别使用 `root_path` 与 `root_file_id`。

CloudDrive2 宿主路径只读挂载到 `/mnt/clouddrive`。后端只允许扫描 `ALLOWED_SCAN_ROOTS` 指定根目录及其子目录。
