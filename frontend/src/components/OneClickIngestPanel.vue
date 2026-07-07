<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { loadAppSettings } from '../services/appSettings'

const FORM_STORAGE_KEY = 'one-click-ingest-form-v2'

const defaultForm = {
  source_root: '/mnt/clouddrive/115open/云下载',
  output_root: '/mnt/clouddrive/115open/原始库/不正常视频/qb/骑兵/洗版'
}

function loadStoredForm() {
  try {
    const raw = window.localStorage.getItem(FORM_STORAGE_KEY)
    if (!raw) return { ...defaultForm }
    const parsed = JSON.parse(raw)
    return {
      source_root: parsed.source_root || defaultForm.source_root,
      output_root: parsed.output_root || defaultForm.output_root
    }
  } catch {
    return { ...defaultForm }
  }
}

const form = ref(loadStoredForm())
const loading = ref(false)
const error = ref('')
const systemStatus = ref(null)
const ingestResult = ref(null)

const canWriteMove = computed(() =>
  Boolean(
    systemStatus.value &&
      systemStatus.value.read_only_mode === false &&
      systemStatus.value.enable_remote_write === true &&
      systemStatus.value.enable_real_move === true
  )
)

watch(
  form,
  value => {
    window.localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(value))
  },
  { deep: true }
)

async function api(path, options) {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  return response.status === 204 ? null : response.json()
}

async function loadSystemStatus() {
  systemStatus.value = await api('/api/v1/system/status')
}

async function loadDefaultSettings() {
  try {
    const settings = await loadAppSettings()
    form.value = {
      ...form.value,
      source_root: settings.one_click_ingest.source_root || form.value.source_root,
      output_root: settings.one_click_ingest.output_root || form.value.output_root
    }
  } catch {}
}

async function refreshState() {
  error.value = ''
  await loadSystemStatus()
}

async function runOneClickIngest() {
  if (loading.value) return
  if (!canWriteMove.value) {
    error.value = '当前仍是只读状态，一键入库需要先打开三重写入开关'
    return
  }

  const confirmed = window.confirm(
    `将按旧流程顺序执行：整理云下载 → 移动到骑兵洗版 → CMS增量同步\n\n源目录：${form.value.source_root}\n目标目录：${form.value.output_root}\n\n确认开始？`
  )
  if (!confirmed) return

  loading.value = true
  error.value = ''
  try {
    ingestResult.value = await api('/api/v1/one-click-ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value)
    })
    await loadSystemStatus()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

const movedSamples = computed(() => {
  const items = ingestResult.value?.move?.items || []
  return items.filter(item => item.ok).slice(0, 20)
})

const failedSamples = computed(() => {
  const items = ingestResult.value?.move?.items || []
  return items.filter(item => !item.ok).slice(0, 20)
})

onMounted(async () => {
  await loadDefaultSettings()
  loadSystemStatus()
})
</script>

<template>
  <section class="task-panel">
    <div class="task-head">
      <div>
        <span class="eyebrow">ONE CLICK INGEST</span>
        <h3>一键入库</h3>
        <p>保留旧流程：整理云下载 → 移动到骑兵洗版 → CMS 增量同步。</p>
      </div>
      <button @click="refreshState">刷新状态</button>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>

    <div class="task-form">
      <label class="grow">
        <span>云下载目录</span>
        <input v-model="form.source_root" placeholder="/mnt/clouddrive/115open/云下载">
      </label>
      <label class="grow">
        <span>骑兵洗版目录</span>
        <input v-model="form.output_root" placeholder="/mnt/clouddrive/115open/原始库/不正常视频/qb/骑兵/洗版">
      </label>
    </div>

    <div class="task-actions task-actions-primary">
      <button class="danger" :disabled="loading || !canWriteMove" @click="runOneClickIngest">
        {{ loading ? '执行中…' : '开始一键入库' }}
      </button>
    </div>

    <div class="task-note">
      <p>当前写入状态：READ_ONLY_MODE={{ systemStatus?.read_only_mode }}, ENABLE_REMOTE_WRITE={{ systemStatus?.enable_remote_write }}, ENABLE_REAL_MOVE={{ systemStatus?.enable_real_move }}</p>
      <p>CMS 同步配置：{{ systemStatus?.cms_sync_configured ? '已配置' : '未配置' }}</p>
      <p>这个按钮会直接执行整理、移动和同步，不再需要你手动点多个步骤。</p>
    </div>

    <div v-if="ingestResult" class="task-grid">
      <div class="task-card stats">
        <h4>整理统计</h4>
        <div class="stats-grid">
          <div><strong>{{ ingestResult.preview.rename_count }}</strong><span>建议重命名</span></div>
          <div><strong>{{ ingestResult.preview.move_to_root_count }}</strong><span>建议提取到根目录</span></div>
          <div><strong>{{ ingestResult.preview.delete_count }}</strong><span>建议删除垃圾</span></div>
          <div><strong>{{ ingestResult.organize.rename_count }}</strong><span>实际整理</span></div>
          <div><strong>{{ ingestResult.organize.delete_count }}</strong><span>实际删除</span></div>
          <div><strong>{{ ingestResult.organize.conflict_count }}</strong><span>整理冲突</span></div>
        </div>
      </div>

      <div class="task-card stats">
        <h4>移动与同步</h4>
        <div class="stats-grid">
          <div><strong>{{ ingestResult.move.moved_count }}</strong><span>已移动</span></div>
          <div><strong>{{ ingestResult.move.failed_count }}</strong><span>移动失败</span></div>
          <div><strong>{{ ingestResult.cms_sync?.ok ? '成功' : (ingestResult.cms_sync ? '失败' : '跳过') }}</strong><span>CMS 同步</span></div>
        </div>
      </div>
    </div>

    <div v-if="ingestResult" class="task-card">
      <div class="result-head">
        <h4>最近移动成功样本</h4>
        <small>最多显示 20 条</small>
      </div>
      <div class="table-wrap">
        <table class="task-table">
          <thead>
            <tr>
              <th>文件</th>
              <th>源路径</th>
              <th>目标路径</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!movedSamples.length">
              <td colspan="4" class="empty">这次没有移动成功样本。</td>
            </tr>
            <tr v-for="row in movedSamples" :key="`${row.file}-${row.to}`">
              <td>{{ row.file }}</td>
              <td class="path" :title="row.from">{{ row.from }}</td>
              <td class="path" :title="row.to">{{ row.to }}</td>
              <td><span class="task-status moved">moved</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="ingestResult" class="task-card">
      <div class="result-head">
        <h4>失败样本</h4>
        <small>最多显示 20 条</small>
      </div>
      <div class="table-wrap">
        <table class="task-table">
          <thead>
            <tr>
              <th>文件</th>
              <th>源路径</th>
              <th>目标路径</th>
              <th>错误</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!failedSamples.length">
              <td colspan="4" class="empty">这次没有失败样本。</td>
            </tr>
            <tr v-for="row in failedSamples" :key="`${row.file}-${row.from}-${row.error}`">
              <td>{{ row.file }}</td>
              <td class="path" :title="row.from">{{ row.from || '—' }}</td>
              <td class="path" :title="row.to">{{ row.to || '—' }}</td>
              <td>{{ row.error || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.task-panel {
  display: grid;
  gap: 1rem;
}

.task-head,
.task-actions,
.task-grid,
.result-head {
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  align-items: center;
}

.task-actions-primary {
  justify-content: flex-start;
}

.task-form {
  display: grid;
  gap: 0.9rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.task-form label,
.task-card {
  background: rgba(11, 18, 32, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 1rem;
}

.task-form label {
  display: grid;
  gap: 0.45rem;
}

.task-form input {
  width: 100%;
}

.task-note,
.task-error {
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  padding: 0.9rem 1rem;
}

.task-error {
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.25);
}

.task-grid {
  align-items: stretch;
}

.task-grid .task-card {
  flex: 1;
}

.stats-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.stats-grid div {
  display: grid;
  gap: 0.25rem;
}

.stats-grid strong {
  font-size: 1.3rem;
}

.danger {
  min-width: 12rem;
  background: linear-gradient(135deg, #b91c1c, #ef4444);
  color: #fff;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.task-table {
  width: 100%;
  border-collapse: collapse;
}

.task-table th,
.task-table td {
  padding: 0.8rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  text-align: left;
  vertical-align: top;
}

.task-table .path {
  max-width: 24rem;
  word-break: break-all;
}

.task-status {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.15);
}

.task-status.moved {
  background: rgba(34, 197, 94, 0.18);
  color: #bbf7d0;
}

@media (max-width: 1100px) {
  .task-form {
    grid-template-columns: 1fr;
  }

  .task-head,
  .task-actions,
  .task-grid,
  .result-head {
    flex-direction: column;
    align-items: stretch;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .task-actions > * {
    width: 100%;
  }

  .danger {
    width: 100%;
    min-width: 0;
  }

  .table-wrap {
    margin: 0 -0.25rem;
    padding: 0 0.25rem 0.25rem;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .task-table {
    min-width: 760px;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
