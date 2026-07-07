# 115 Media Indexer

面向 CloudDrive2 挂载目录的只读媒体文件索引。第一阶段只读取目录项及文件系统元数据，不打开或下载视频内容，也不提供移动、改名、删除、上传或元数据站点抓取能力。

## Windows Docker Desktop 启动

前提：Docker Desktop 已切换到 Linux containers，并且 CloudDrive2 挂载目录在宿主机上可以正常浏览。

在 PowerShell 中执行：

```powershell
Copy-Item .env.example .env
notepad .env
```

将 `CLOUDDRIVE_MOUNT_PATH` 改成真实路径，并使用正斜杠：

```dotenv
CLOUDDRIVE_MOUNT_PATH=D:/CloudDrive/115
```

路径含空格时直接填写，不要额外添加引号：

```dotenv
CLOUDDRIVE_MOUNT_PATH=D:/Media Library/115
```

运行预检与启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-windows.ps1
docker compose up --build -d
```

打开 `http://localhost:8080`。网页添加扫描源时必须填写容器内路径 `/mnt/clouddrive`，不能填写 `D:/...` 的 Windows 宿主机路径。

Compose 使用长格式 bind mount，等价关系如下：

```text
${CLOUDDRIVE_MOUNT_PATH} -> /mnt/clouddrive (read_only)
```

可以在容器启动后确认映射：

```powershell
docker compose exec backend python -c "from pathlib import Path; p=Path('/mnt/clouddrive'); print('exists=',p.exists(),'dir=',p.is_dir())"
```

如果显示目录不存在或空目录，请在 Docker Desktop 的文件共享设置中确认对应盘符可访问，并确认 CloudDrive2 已先完成挂载。

Windows Docker Desktop 建议保持 Linux containers 模式。若 CloudDrive2 使用盘符挂载，必须先确认该盘符在资源管理器中可读，再运行 `scripts/check-windows.ps1`。

## 其他平台启动

复制 `.env.example` 为 `.env`，将 `CLOUDDRIVE_MOUNT_PATH` 设置为实际挂载路径，然后执行：

```shell
docker compose up --build -d
```

## NAS Docker Compose 部署

将项目复制到 NAS，例如 `/volume1/docker/115-media-indexer`，并创建 `.env`：

```dotenv
CLOUDDRIVE_MOUNT_PATH=/volume1/CloudDrive/115
APP_PORT=8080
SCAN_BATCH_SIZE=250
SCAN_WORKERS=2
READ_ONLY_MODE=true
ENABLE_REMOTE_WRITE=false
ENABLE_EXTERNAL_METADATA=false
```

启动：

```shell
cd /volume1/docker/115-media-indexer
docker compose config
docker compose up --build -d
```

不同 NAS 的实际共享目录可能是 `/volume1/...`、`/share/...` 或 `/mnt/...`。`CLOUDDRIVE_MOUNT_PATH` 必须填写 NAS 宿主机真实路径，网页中的扫描路径仍固定填写 `/mnt/clouddrive`。

CloudDrive2 映射关系示例：

```text
Windows: D:/CloudDrive/115       -> /mnt/clouddrive (只读)
Synology: /volume1/CloudDrive/115 -> /mnt/clouddrive (只读)
QNAP: /share/CloudDrive/115       -> /mnt/clouddrive (只读)
```

## 真实运行前检查清单

### Windows Docker Desktop

- [ ] Docker Desktop 已启动并使用 Linux containers。
- [ ] WSL 2/虚拟化工作正常，`docker version` 和 `docker compose version` 均成功。
- [ ] CloudDrive2 小目录已挂载，且能在 Windows 资源管理器中正常列出文件。
- [ ] `.env` 已从 `.env.example` 复制，Windows 路径使用正斜杠。
- [ ] `CLOUDDRIVE_MOUNT_PATH` 暂时指向 50–200 个视频的小目录，而不是完整媒体库。
- [ ] 三个安全开关分别为 `true`、`false`、`false`，没有改成其他值。
- [ ] `APP_PORT` 未被其他程序占用，Docker Desktop 有足够磁盘空间。
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/check-windows.ps1` 通过。
- [ ] `docker compose config` 中宿主目录映射到 `/mnt/clouddrive`，并显示只读挂载。
- [ ] 启动后 `docker compose ps` 显示 backend healthy、frontend running。
- [ ] 系统状态页显示后端和 SQLite 正常、挂载目录可读。

### NAS Docker Compose

- [ ] NAS CPU 架构可运行项目所用的 Python、Node 和 Nginx 官方镜像。
- [ ] Docker Engine 与 Compose v2 可用，项目目录及数据卷所在磁盘空间充足。
- [ ] CloudDrive2 小目录在 NAS 宿主机上可读，路径不是容器内部路径。
- [ ] 运行 Compose 的用户有读取媒体目录和写入 Docker 数据卷的权限。
- [ ] `.env` 使用 NAS 真实绝对路径，例如 `/volume1/CloudDrive/115-test`。
- [ ] 三个安全开关保持要求值，`APP_PORT` 没有与 NAS 服务冲突。
- [ ] `docker compose config` 展开的 bind mount 目标是 `/mnt/clouddrive` 且为只读。
- [ ] NAS 防火墙或反向代理只向可信局域网开放服务，不直接暴露到互联网。
- [ ] 启动后检查 `docker compose ps`、`docker compose logs backend` 和系统状态页。
- [ ] 已确认命名卷 `115-media-indexer-index-data` 存在并有独立备份位置。

## 首次试跑建议

### 1. 先用零字节 demo 冒烟测试

脚本只创建缺失的零字节文件，不覆盖、移动、改名或删除已有文件，也不包含真实视频内容：

```shell
python scripts/generate-demo-files.py --output demo-media
```

预览但不创建：

```shell
python scripts/generate-demo-files.py --dry-run
```

将 `.env` 临时设置为：

```dotenv
CLOUDDRIVE_MOUNT_PATH=./demo-media
```

启动后在网页添加 `/mnt/clouddrive` 并扫描。预期结果固定为：

```text
总视频数：20
已识别：16
未识别：4
预期识别率：80%
```

### 2. 再扫描一个真实小目录

选择一个已经存在、包含约 50–200 个视频的独立目录。不要先挂载完整媒体库。将宿主机小目录配置为 `CLOUDDRIVE_MOUNT_PATH`，网页扫描根目录仍填写 `/mnt/clouddrive`。

试跑时记录：

1. 扫描任务开始、结束时间及 `scanned_count`。
2. 扫描速度：`scanned_count ÷ 扫描秒数`，并观察 CloudDrive2 和 NAS/Windows 资源占用。
3. 识别率：`identified_count ÷ scanned_count × 100%`。
4. 随机抽查至少 10 个番号，确认大小写、下划线、空格和连字符均正确标准化。
5. 确认图片、字幕、NFO、TXT 以及不支持的视频扩展名没有进入文件列表。

扫描不应阻塞页面；试跑期间还应点击一次“停止扫描”，确认任务变为 `stopped`，然后重新发起完整试跑。

### 3. 验证导出

在文件库导出筛选后的 CSV，再到系统状态页依次导出：

- `files.csv`：行数与文件列表一致，中文路径在表格软件中可读。
- `metadata.csv`：重新导入后番号、标题、演员和厂商保持一致。
- `index.db`：文件开头应是有效 SQLite 数据库，且下载大小不为零。

### 4. 验证备份恢复

只在小目录试跑期间执行：

1. 记录文件总数、已识别数量和元数据数量。
2. 从系统状态页下载 `index.db`、`metadata.csv`、`files.csv`，存入独立备份目录。
3. 执行 `docker compose down`，确认容器已停止。
4. 另存当前数据卷后，将下载的 `index.db` 放入命名卷的 `/data/index.db`。
5. 执行 `docker compose up -d`，等待 backend healthy。
6. 打开系统状态页确认 SQLite 为 `ok`，并核对步骤 1 的三个数量。
7. 再导入一次 `metadata.csv`，确认结果是更新而不是产生重复番号。

上述检查全部通过后，再把 `CLOUDDRIVE_MOUNT_PATH` 改为较大目录。建议逐级扩大到约 1,000 个文件，最后才扫描完整媒体库。

## 安全开关

以下三个值是强制安全边界：

```dotenv
READ_ONLY_MODE=true
ENABLE_REMOTE_WRITE=false
ENABLE_EXTERNAL_METADATA=false
```

后端启动时会校验它们。任意值不符合要求时，FastAPI 拒绝启动；这些开关不能用于启用写文件或外部元数据功能。

## 备份与恢复

系统状态页提供三个手动下载入口：

- `index.db`：通过 SQLite 在线备份 API 创建的一致性数据库快照。
- `metadata.csv`：可重新导入的 UTF-8 元数据 CSV。
- `files.csv`：文件索引清单。

也可直接访问：

```text
GET /api/v1/backups/index.db
GET /api/v1/backups/metadata.csv
GET /api/v1/backups/files.csv
```

恢复完整数据库：

1. 停止服务：`docker compose down`。
2. 找到 `index-data` 命名卷，或临时启动一个只挂载该卷的容器。
3. 将备份文件替换为卷内的 `/data/index.db`。
4. 确认文件名仍为 `index.db`，然后执行 `docker compose up -d`。
5. 打开系统状态页，确认 SQLite 状态为 `ok`。

推荐的跨主机恢复方式：

```shell
docker compose down
docker run --rm -v 115-media-indexer-index-data:/data -v /path/to/backup:/backup alpine sh -c "cp /backup/index.db /data/index.db"
docker compose up -d
```

执行恢复前应另存当前数据库。Compose 将数据卷固定命名为 `115-media-indexer-index-data`，也可通过 `docker volume ls` 确认。

只恢复元数据时，无需替换数据库：打开“番号元数据”页面，重新导入 `metadata.csv`。相同番号会更新，未出现的现有番号不会被删除。

## 常见错误排查

- **后端反复重启**：查看 `docker compose logs backend`，确认三个安全开关严格使用要求值。
- **挂载目录不可读**：确认 `.env` 使用宿主机路径、网页使用 `/mnt/clouddrive`，并检查 Docker Desktop 盘符共享或 NAS 容器权限。
- **页面显示 SQLite error**：检查 `index-data` 卷可写、磁盘未满；恢复后确认数据库文件位于 `/data/index.db`。
- **端口 8080 被占用**：修改 `.env` 的 `APP_PORT`，例如 `APP_PORT=18080`。
- **CSV 中文乱码**：使用 UTF-8 或 UTF-8 BOM 保存 CSV。
- **扫描速度慢**：CloudDrive2 首次目录枚举可能触发大量远端元数据查询，可适当降低 `SCAN_WORKERS`，不要提高到大量并发。
- **Docker Compose 路径解析失败**：Windows 路径使用正斜杠，例如 `D:/CloudDrive/115`；先运行 `docker compose config` 检查展开结果。

如果暂时没有 CloudDrive2，可不创建 `.env`。Compose 会将项目内的 `sample-media` 作为只读演示目录挂载。

## 只读边界

- CloudDrive2 目录在 Compose 中以 `read_only: true` 挂载。
- `local_fs` provider 只遍历目录并调用文件 `stat`，不打开文件内容。
- 只索引 `.mp4`、`.mkv`、`.avi`、`.wmv`、`.mov`、`.ts`、`.m2ts`；图片、字幕、NFO 和文本文件会在遍历阶段跳过。
- 不跟随符号链接，不索引符号链接文件。
- API 中不存在远端文件移动、改名、删除、上传或下载端点。
- `p115` 当前是显式失败的 mock，不导入或调用 `p115client`。

## Provider 接口

所有 provider 实现统一提供：

- `provider_name`
- `list_files(root_path_or_id)`
- `get_file_metadata(file)`

第一版实现 `local_fs`，并保留 `p115` mock 作为后续扩展点。

## 番号元数据

元数据完全离线，只支持手动 CSV 与本地 mock provider。系统不包含 JavDB、JavBus、DMM 或其他网站客户端，也不会爬取网页或由后端请求外网。

CSV 必须使用 UTF-8 编码，表头固定为：

```csv
identifier,title,actors,studio,series,release_date,cover_url
ssis001,示例标题,"演员 A|演员 B",示例厂商,示例系列,2025-01-02,/covers/ssis001.jpg
ipzz_123,另一个标题,"[""演员 C"",""演员 D""]",示例厂商,,,
```

- 番号会标准化，例如 `ssis001` 变成 `SSIS-001`，`ipzz_123` 变成 `IPZZ-123`。
- 演员可使用 `|`、逗号、分号、斜杠、顿号分隔，也可以使用 JSON 字符串数组。
- 发行日期使用 `YYYY-MM-DD`。
- 相同番号再次导入时更新现有记录，不创建重复项。
- 封面 URL 会保存原值，但页面只自动加载同源相对地址或 `data:image`，不会自动请求外部图片站点。

相关 API：

```text
POST /api/v1/metadata/import/csv
GET  /api/v1/metadata?actor=演员&studio=厂商
GET  /api/v1/metadata/{identifier}
POST /api/v1/metadata/{identifier}/lookup  # 仅本地 mock
```

## 多源元数据补全

补全任务是独立的只读索引工作流，只根据番号读写 SQLite，不读取或修改媒体文件。第一版注册的 Provider：

| Provider | 状态 | 网络访问 |
|---|---|---|
| `local_db` | 已实现 | 无 |
| `manual_csv` | 已实现 | 无 |
| `javbus` | disabled mock | 无 |
| `jav321` | disabled mock | 无 |
| `dmm` | disabled mock | 无 |
| `missav` | disabled mock | 无 |
| `theporndb` | disabled mock | 无 |

聚合器优先查询 `metadata_provider_cache`，再按 Provider 优先级查询。结果按字段完整度和来源置信度评分，只填补空字段，不使用低优先级结果覆盖已有字段。任务支持后台执行、进度查询、日志筛选和停止。

```text
POST /api/v1/metadata/enrichment/jobs
GET  /api/v1/metadata/enrichment/jobs
GET  /api/v1/metadata/enrichment/jobs/{job_id}
GET  /api/v1/metadata/enrichment/jobs/{job_id}/logs
POST /api/v1/metadata/enrichment/jobs/{job_id}/stop
GET  /api/v1/metadata/missing.csv
```

缺失番号 CSV 与手动导入模板使用相同字段，可下载后离线填写并重新导入。`ENABLE_EXTERNAL_METADATA=false` 时，启动检查会拒绝任何标记为网络 Provider 的注册项。

当前方向不接入真实外网 Provider；系统没有 HTTP 客户端、真实站点请求或页面解析代码。上述外部名称仅保留为 disabled mock。

## Organizer 整理计划（仅 Dry-run）

Organizer 只读取文件索引和已有 metadata，在 SQLite 中保存虚拟规划结果。系统没有执行计划、移动、改名、删除、写入 115 或写入 CloudDrive2 的接口，也不会生成 STRM、NFO、海报或 Emby 元数据。

## Reference Structure Provider（STRM 参考结构）

本模块用于扫描 NAS 上已经整理好的 STRM 目录结构，并把它作为后续生成 115 资源整理计划的参考标准。它不会把 STRM 写入 `media_files`，而是写入独立的 `reference_sources` 与 `reference_items` 表。

Compose 增加一个只读参考目录映射：

```dotenv
REFERENCE_STRM_PATH=/vol1/1000/media/小姐姐
```

容器内固定路径：

```text
/mnt/reference-strm
```

映射关系：

```text
/vol1/1000/media/小姐姐 -> /mnt/reference-strm (read_only)
```

示例 STRM：

```text
/vol1/1000/media/小姐姐/骑兵/阿由叶亚美/PRED-107/PRED-107.strm
```

以 `/mnt/reference-strm` 作为 reference root 扫描后，应得到：

```text
identifier = PRED-107
reference_path = 骑兵/阿由叶亚美/PRED-107/PRED-107.strm
reference_dir = 骑兵/阿由叶亚美/PRED-107
filename = PRED-107.strm
ext = strm
```

注意：

- `reference_path` 和 `reference_dir` 永远是相对 reference root 的路径。
- 不包含 `/mnt/reference-strm`。
- 不包含 NAS 宿主机路径 `/vol1/1000/media/小姐姐`。
- 只扫描 `.strm` 文件。
- 不读取 STRM 文件内容。
- 不请求外网。
- 不修改 STRM 目录。
- 不移动、不改名、不删除 115 或 CloudDrive2 文件。

当前阶段只提供 Reference Structure 扫描与查询 API：

```text
GET  /api/v1/reference-sources
POST /api/v1/reference-sources
POST /api/v1/reference-sources/{source_id}/scan
GET  /api/v1/reference-items
```

支持的模板字段：

```text
{actor} {studio} {series} {identifier} {prefix}
{title} {year} {filename} {ext}
```

- `{filename}` 是包含原扩展名的完整文件名。
- `{ext}` 是不含点的小写扩展名。
- `{actor}` 有多位演员时第一版使用第一位。
- 没有 metadata 时只能可靠使用 `{identifier}`、`{prefix}`、`{filename}`、`{ext}`。
- 目标路径始终是相对虚拟路径，不代表已经创建目录或移动文件。

示例：

```text
{prefix}/{identifier}/{filename}
{studio}/{series}/{identifier}/{filename}
{actor}/{identifier}/{filename}
```

计划条目状态：

- `ready`：模板字段齐全且目标路径合法。
- `missing_metadata`：模板依赖的 metadata 字段缺失。
- `unidentified`：文件没有可识别番号。
- `conflict`：多个文件生成同一个目标路径。
- `invalid_path`：包含路径穿越、非法字符或非法组件。
- `skipped`：文件已在最近扫描中标记为离线。

API：

```text
POST /api/v1/organizer/jobs
GET  /api/v1/organizer/jobs
GET  /api/v1/organizer/jobs/{job_id}
GET  /api/v1/organizer/jobs/{job_id}/items
GET  /api/v1/organizer/jobs/{job_id}/export.csv
```

不存在 `execute`、`move` 或类似写文件端点。导出的 CSV 仅用于审核源路径、虚拟目标路径、模板、状态和错误原因。

## 虚拟合集

演员、厂商和系列合集由现有文件索引与番号元数据实时聚合，不创建副本，也不会移动、改名或删除任何文件。只有已经关联到本地文件的元数据会进入合集统计。

列表 API：

```text
GET /api/v1/collections/actors
GET /api/v1/collections/studios
GET /api/v1/collections/series
```

共同查询参数：

- `q`：搜索演员、厂商或系列名称。
- `sort_by`：`file_count` 或 `latest_release_date`。
- `sort_order`：`asc` 或 `desc`。
- `page`、`page_size`：分页参数。

合集文件 API：

```text
GET /api/v1/collections/actors/{actor}/files
GET /api/v1/collections/studios/{studio}/files
GET /api/v1/collections/series/{series}/files
```

详情接口支持 `q`、`page` 和 `page_size`，返回文件名、路径、番号、标题、演员、厂商、系列和文件大小。合集封面从该合集具有最新发行日期的本地元数据记录中选择，页面仍只加载同源地址或 `data:image`，不会请求外部图片站点。

## 大目录扫描

- 扫描在后台线程中执行，启动扫描的 HTTP 请求会立即返回。
- 页面轮询扫描任务，展示当前扫描、已识别、未识别和错误数量。
- 扫描可停止；停止后不会把尚未遍历到的旧索引误标为离线。
- 已有索引一次性载入内存，避免逐文件查询数据库。
- 默认每 250 个文件提交一次 SQLite，可通过 `SCAN_BATCH_SIZE` 调整。
- SQLite 使用 WAL、`synchronous=NORMAL` 和 30 秒 busy timeout。

## 开发验证

后端：

```shell
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest
```

前端：

```shell
cd frontend
npm install
npm run build
```


## Local Metadata Harvest

This project now supports offline local metadata harvest from reference STRM and local NFO.

Providers:
- `reference_metadata`: derive actor names from `reference_dir`
- `local_nfo`: read local `.nfo` files next to reference STRM

Safety rules:
- no external network requests
- `plot` is stored separately from `title`
- locked fields are never overwritten by provider merge

API:
```text
POST /api/v1/metadata/harvest/reference
```

Example payload:
```json
{
  "reference_source_id": 1,
  "reference_scope_prefix": "??/",
  "providers": ["reference_metadata", "local_nfo"]
}
```

## AI Translation Panel

The project now includes an `AI 翻译` page for local `.nfo` files.

- new local-media bind:
  - host: `/vol1/1000/media`
  - container: `/mnt/local-media`
- folder config stores:
  - folder path
  - custom prompt template
  - enabled state
- translation jobs support:
  - `analyze`: scan only, no write
  - `translate`: call an OpenAI-compatible API and write back `title` / `plot`

Recommended env additions:

```env
LOCAL_MEDIA_PATH=/vol1/1000/media
LOCAL_MEDIA_BIND_READ_ONLY=true
ENABLE_AI_TRANSLATION=false
AI_TRANSLATION_API_KEY=
AI_TRANSLATION_BASE_URL=https://api.openai.com/v1
AI_TRANSLATION_MODEL=gpt-4.1-mini
ALLOWED_TRANSLATION_ROOTS=/mnt/local-media,/mnt/reference-strm,/mnt/clouddrive
```

Notes:

- `.nfo` write-back creates `.nfo.bak` first.
- real write-back still requires:
  - `READ_ONLY_MODE=false`
  - `ENABLE_REMOTE_WRITE=true`
  - `ENABLE_AI_TRANSLATION=true`
- if you want to translate the NAS local library directly, the bind mount must not be read-only.
