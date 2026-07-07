<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { loadAppSettings } from '../services/appSettings'

const FORM_STORAGE_KEY = 'organizer-task-panel-form-v4'
const STATE_STORAGE_KEY = 'organizer-task-panel-state-v4'

const defaultForm = {
  source_root: '/mnt/clouddrive/115open/原始库/小姐姐/骑兵',
  output_root: '/mnt/clouddrive/115open/小姐姐/骑兵',
  reference_scope_prefix: '骑兵/'
}

const FINAL_SCAN_STATUSES = ['success', 'failed', 'stopped']
const FINAL_JOB_STATUSES = ['success', 'failed', 'stopped']
const EXECUTE_CHUNK_LIMIT = 5000

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function loadStoredForm() {
  try {
    const raw = window.localStorage.getItem(FORM_STORAGE_KEY)
    if (!raw) return { ...defaultForm }
    const parsed = JSON.parse(raw)
    return {
      source_root: parsed.source_root || defaultForm.source_root,
      output_root: parsed.output_root || defaultForm.output_root,
      reference_scope_prefix: parsed.reference_scope_prefix || defaultForm.reference_scope_prefix
    }
  } catch {
    return { ...defaultForm }
  }
}

const form = ref(loadStoredForm())
const loading = ref(false)
const executing = ref(false)
const error = ref('')
const systemStatus = ref(null)
const activeSource = ref(null)
const activeScan = ref(null)
const activeJob = ref(null)
const summary = ref(null)
const results = ref([])
const resultMode = ref('最近结果')
const pipelineStage = ref('')
const pipelineDetail = ref('')
const scanPolling = ref(null)
const organizerPolling = ref(null)

const busy = computed(() => loading.value || executing.value)

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

watch(
  [activeScan, activeJob],
  () => {
    window.localStorage.setItem(
      STATE_STORAGE_KEY,
      JSON.stringify({
        activeScanId: activeScan.value?.id || null,
        activeJobId: activeJob.value?.id || null
      })
    )
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

function clearPipeline() {
  pipelineStage.value = ''
  pipelineDetail.value = ''
}

function setPipeline(stage, detail = '') {
  pipelineStage.value = stage
  pipelineDetail.value = detail
}

function mapExecutionItems(items) {
  return items.map(item => ({
    organizer_item_id: item.organizer_item_id,
    identifier: item.identifier,
    source_path: item.source_path,
    target_path: item.container_target_path || item.display_target_path,
    status: item.status,
    error_message: item.error_message
  }))
}

function resetActiveTaskState() {
  activeSource.value = null
  activeScan.value = null
  activeJob.value = null
  summary.value = null
  results.value = []
  clearTimeout(scanPolling.value)
  clearTimeout(organizerPolling.value)
  window.localStorage.setItem(
    STATE_STORAGE_KEY,
    JSON.stringify({
      activeScanId: null,
      activeJobId: null
    })
  )
}

async function loadSystemStatus() {
  systemStatus.value = await api('/api/v1/system/status')
}

async function loadDefaultSettings() {
  try {
    const settings = await loadAppSettings()
    form.value = {
      ...form.value,
      source_root: settings.organizer_task.source_root || form.value.source_root,
      output_root: settings.organizer_task.output_root || form.value.output_root,
      reference_scope_prefix: settings.organizer_task.reference_scope_prefix || form.value.reference_scope_prefix
    }
  } catch {}
}

async function loadSummary(jobId = activeJob.value?.id) {
  if (!jobId) return
  summary.value = await api(`/api/v1/organizer/task/jobs/${jobId}/summary`)
}

async function loadExecutions(jobId = activeJob.value?.id) {
  if (!jobId) return
  const data = await api(`/api/v1/organizer/jobs/${jobId}/executions?page=1&page_size=20`)
  results.value = mapExecutionItems(data.items)
  resultMode.value = '最近执行日志'
}

function scheduleScanPoll(delay = 800) {
  clearTimeout(scanPolling.value)
  scanPolling.value = window.setTimeout(pollScan, delay)
}

function normalizePath(value) {
  return (value || '').replace(/\\/g, '/').replace(/\/+$/, '')
}

async function syncLatestTaskForCurrentSource() {
  const normalizedSourceRoot = normalizePath(form.value.source_root)
  if (!normalizedSourceRoot) return

  const sources = await api('/api/v1/sources')
  const matchedSource = sources.find(item => normalizePath(item.root_path) === normalizedSourceRoot)
  if (!matchedSource) return

  activeSource.value = matchedSource

  const scans = await api('/api/v1/scans?limit=20')
  const latestScan = scans.find(item => item.source_id === matchedSource.id)
  if (latestScan) {
    activeScan.value = latestScan
    if (!FINAL_SCAN_STATUSES.includes(latestScan.status)) {
      scheduleScanPoll(100)
    }
  }

  const jobs = await api('/api/v1/organizer/jobs')
  const latestJob = jobs.find(
    item =>
      item.mode === 'reference_based' &&
      item.source_id === matchedSource.id &&
      normalizePath(item.reference_scope_prefix || '') === normalizePath(form.value.reference_scope_prefix)
  )
  if (latestJob) {
    activeJob.value = latestJob
    await loadSummary(latestJob.id)
    if (!FINAL_JOB_STATUSES.includes(latestJob.status)) {
      scheduleOrganizerPoll(100)
    } else {
      await loadExecutions(latestJob.id)
    }
  }
}

async function pollScan() {
  if (!activeScan.value) return
  try {
    activeScan.value = await api(`/api/v1/scans/${activeScan.value.id}`)
    if (!FINAL_SCAN_STATUSES.includes(activeScan.value.status)) {
      scheduleScanPoll()
      return
    }
    if (activeJob.value) {
      await loadSummary(activeJob.value.id)
    }
  } catch (err) {
    error.value = err.message
    scheduleScanPoll(1500)
  }
}

function scheduleOrganizerPoll(delay = 800) {
  clearTimeout(organizerPolling.value)
  organizerPolling.value = window.setTimeout(pollOrganizerJob, delay)
}

async function pollOrganizerJob() {
  if (!activeJob.value) return
  try {
    activeJob.value = await api(`/api/v1/organizer/jobs/${activeJob.value.id}`)
    await loadSummary(activeJob.value.id)
    if (!FINAL_JOB_STATUSES.includes(activeJob.value.status)) {
      scheduleOrganizerPoll()
      return
    }
    await loadExecutions(activeJob.value.id)
  } catch (err) {
    error.value = err.message
    scheduleOrganizerPoll(1500)
  }
}

async function waitForScan(jobId) {
  while (true) {
    const job = await api(`/api/v1/scans/${jobId}`)
    activeScan.value = job
    if (FINAL_SCAN_STATUSES.includes(job.status)) {
      if (job.status !== 'success') {
        throw new Error(`扫描未成功结束：${job.status}`)
      }
      return job
    }
    setPipeline('扫描中', `scan_job #${job.id} · 已扫描 ${job.scanned_count ?? 0}`)
    await sleep(800)
  }
}

async function waitForOrganizerJob(jobId) {
  while (true) {
    const job = await api(`/api/v1/organizer/jobs/${jobId}`)
    activeJob.value = job
    await loadSummary(job.id)
    if (FINAL_JOB_STATUSES.includes(job.status)) {
      if (job.status !== 'success') {
        throw new Error(`dry-run 未成功结束：${job.status}`)
      }
      return job
    }
    setPipeline('生成 dry-run', `organizer_job #${job.id} · 已处理 ${job.processed_count ?? 0}/${job.total_count ?? 0}`)
    await sleep(800)
  }
}

async function refreshReferenceSource() {
  setPipeline('刷新参考库', '正在同步 NAS STRM 参考结构')
  const sources = await api('/api/v1/reference-sources')
  const source = sources.find(item => item.enabled) || sources[0]
  if (!source) {
    throw new Error('没有可用的 reference source')
  }
  return api(`/api/v1/reference-sources/${source.id}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
}

async function refreshState() {
  error.value = ''
  await loadSystemStatus()
  await syncLatestTaskForCurrentSource()
  if (activeScan.value?.id) {
    activeScan.value = await api(`/api/v1/scans/${activeScan.value.id}`)
  }
  if (activeJob.value?.id) {
    activeJob.value = await api(`/api/v1/organizer/jobs/${activeJob.value.id}`)
    await loadSummary(activeJob.value.id)
    await loadExecutions(activeJob.value.id)
  }
}

async function restoreState() {
  await loadSystemStatus()
  try {
    await syncLatestTaskForCurrentSource()
    const raw = window.localStorage.getItem(STATE_STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!activeScan.value && parsed.activeScanId) {
      activeScan.value = await api(`/api/v1/scans/${parsed.activeScanId}`)
      if (!FINAL_SCAN_STATUSES.includes(activeScan.value.status)) {
        scheduleScanPoll(100)
      }
    }
    if (!activeJob.value && parsed.activeJobId) {
      activeJob.value = await api(`/api/v1/organizer/jobs/${parsed.activeJobId}`)
      await loadSummary(activeJob.value.id)
      if (!FINAL_JOB_STATUSES.includes(activeJob.value.status)) {
        scheduleOrganizerPoll(100)
      } else {
        await loadExecutions(activeJob.value.id)
      }
    }
  } catch (err) {
    error.value = err.message
  }
}

async function runPreflightForAllReady() {
  if (!activeJob.value) {
    throw new Error('缺少 organizer job')
  }
  await loadSummary(activeJob.value.id)
  const limit = Number(summary.value?.ready_count ?? 0)
  if (limit <= 0) {
    return { requested_count: 0, passed_count: 0, failed_count: 0, items: [] }
  }

  executing.value = true
  try {
    setPipeline('执行 preflight', `检查当前任务全部 ready：${limit} 条`)
    let offset = 0
    let requested = 0
    let passed = 0
    let failed = 0
    const mergedItems = []
    while (offset < limit) {
      const chunk = Math.min(EXECUTE_CHUNK_LIMIT, limit - offset)
      const data = await api(`/api/v1/organizer/jobs/${activeJob.value.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status_filter: 'ready',
          limit: chunk,
          mode: 'preflight',
          confirm: false
        })
      })
      requested += data.requested_count || 0
      passed += data.passed_count || 0
      failed += data.failed_count || 0
      mergedItems.push(...(data.items || []))
      offset += chunk
      if ((data.requested_count || 0) < chunk) break
      setPipeline('执行 preflight', `已检查 ${Math.min(offset, limit)}/${limit} 条`)
    }
    const merged = {
      organizer_job_id: activeJob.value.id,
      requested_count: requested,
      passed_count: passed,
      failed_count: failed,
      items: mergedItems
    }
    results.value = mapExecutionItems(merged.items || [])
    resultMode.value = `Preflight: ${merged.passed_count}/${merged.requested_count} 通过`
    await loadSummary(activeJob.value.id)
    setPipeline('preflight 完成', `${merged.passed_count}/${merged.requested_count} 通过`)
    return merged
  } finally {
    executing.value = false
  }
}

async function executeMoveAllReady({ requireConfirm = true } = {}) {
  if (!activeJob.value) {
    throw new Error('缺少 organizer job')
  }
  if (!canWriteMove.value) {
    throw new Error('当前仍是只读状态，真实 move 只有在三重写入开关全部打开后才可用')
  }

  await loadSummary(activeJob.value.id)
  const limit = Number(summary.value?.ready_count ?? 0)
  if (limit <= 0) {
    return { moved_count: 0, failed_count: 0, moved_samples: [], failed_samples: [] }
  }

  if (requireConfirm) {
    const confirmed = window.confirm(
      `将按当前设置目录执行全部 ready 条目。\n源目录：${form.value.source_root}\n输出目录：${form.value.output_root}\n参考范围：${form.value.reference_scope_prefix}\n\n本次会直接执行当前任务中全部可移动项（ready=${limit}）。确认继续？`
    )
    if (!confirmed) return null
  }

  executing.value = true
  try {
    setPipeline('执行真实 move', `执行当前任务全部 ready：${limit} 条`)
    let offset = 0
    let movedCount = 0
    let skippedCount = 0
    let failedCount = 0
    let movedSamples = []
    let failedSamples = []
    while (offset < limit) {
      const chunk = Math.min(EXECUTE_CHUNK_LIMIT, limit - offset)
      const data = await api(`/api/v1/organizer/jobs/${activeJob.value.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status_filter: 'ready',
          limit: chunk,
          mode: 'move',
          confirm: true
        })
      })
      movedCount += data.moved_count || 0
      skippedCount += data.skipped_count || 0
      failedCount += data.failed_count || 0
      movedSamples = movedSamples.concat(data.moved_samples || []).slice(0, 20)
      failedSamples = failedSamples.concat(data.failed_samples || []).slice(0, 20)
      offset += data.requested_count || 0
      setPipeline('执行真实 move', `已处理 ${Math.min(offset, limit)}/${limit} 条，已移动 ${movedCount} 条`)
      if ((data.failed_count || 0) > 0 || (data.requested_count || 0) === 0) {
        break
      }
    }
    const merged = {
      moved_count: movedCount,
      skipped_count: skippedCount,
      failed_count: failedCount,
      moved_samples: movedSamples,
      failed_samples: failedSamples
    }
    results.value = [
      ...mapExecutionItems(merged.moved_samples || []),
      ...mapExecutionItems(merged.failed_samples || [])
    ]
    resultMode.value = `Move：已移动 ${merged.moved_count} 条`
    await Promise.all([loadSystemStatus(), loadSummary(activeJob.value.id), loadExecutions(activeJob.value.id)])
    setPipeline('move 完成', `已移动 ${merged.moved_count} 条`)
    return merged
  } finally {
    executing.value = false
  }
}

async function runOneClickExecute() {
  if (busy.value) return
  if (!canWriteMove.value) {
    error.value = '当前仍是只读状态，一键执行需要先打开三重写入开关'
    return
  }

  const confirmed = window.confirm(
    `将严格按当前设置目录新建任务并直接执行全部可移动文件。\n\n源目录：${form.value.source_root}\n输出目录：${form.value.output_root}\n参考范围：${form.value.reference_scope_prefix}\n\n流程：扫描 → dry-run → preflight → move（全部 ready）\n确认继续？`
  )
  if (!confirmed) return

  loading.value = true
  error.value = ''
  resetActiveTaskState()
  results.value = []
  resultMode.value = '一键执行结果'

  try {
    setPipeline('提交扫描', form.value.source_root)
    const scanData = await api('/api/v1/organizer/task/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_root: form.value.source_root,
        name: 'Organizer Task Source'
      })
    })
    activeSource.value = scanData.source
    activeScan.value = scanData.scan_job

    await waitForScan(scanData.scan_job.id)

    setPipeline('提交 dry-run', form.value.output_root)
    activeJob.value = await api('/api/v1/organizer/task/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_root: form.value.source_root,
        output_root: form.value.output_root,
        reference_scope_prefix: form.value.reference_scope_prefix
      })
    })

    await waitForOrganizerJob(activeJob.value.id)

    loading.value = false
    const preflight = await runPreflightForAllReady()
    if (!preflight) {
      setPipeline('preflight 未返回结果', '已停止')
      return
    }
    if ((preflight.requested_count || 0) === 0) {
      setPipeline('没有可执行项目', '当前目录没有 ready 项')
      return
    }
    if ((preflight.failed_count || 0) > 0) {
      setPipeline('preflight 存在跳过项', `${preflight.passed_count}/${preflight.requested_count} 可执行，其余将按 skipped 处理`)
    }
    await executeMoveAllReady({ requireConfirm: false })
  } catch (err) {
    error.value = err.message
    setPipeline('执行失败', err.message)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadDefaultSettings()
  restoreState()
})

onUnmounted(() => {
  clearTimeout(scanPolling.value)
  clearTimeout(organizerPolling.value)
})
</script>

<template>
  <section class="task-panel">
    <div class="task-head">
      <div>
        <span class="eyebrow">ORGANIZER TASKS</span>
        <h3>整理任务面板</h3>
        <p>只保留一个入口：按当前设置目录，一键扫描、生成 dry-run、preflight，并执行全部 ready。</p>
      </div>
      <button @click="refreshState">刷新状态</button>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>

    <div v-if="pipelineStage" class="task-note task-stage">
      <p><strong>当前阶段：</strong>{{ pipelineStage }}</p>
      <p v-if="pipelineDetail">{{ pipelineDetail }}</p>
    </div>

    <div v-if="summary" class="task-note">
      <p><strong>当前任务 source_root：</strong>{{ summary.source_root }}</p>
      <p><strong>当前任务 output_root：</strong>{{ summary.output_root }}</p>
      <p><strong>当前任务 reference_scope_prefix：</strong>{{ summary.reference_scope_prefix }}</p>
    </div>

    <div class="task-form">
      <label class="grow">
        <span>源目录</span>
        <input v-model="form.source_root" placeholder="/mnt/clouddrive/115open/原始库/小姐姐/骑兵">
      </label>
      <label class="grow">
        <span>输出目录</span>
        <input v-model="form.output_root" placeholder="/mnt/clouddrive/115open/小姐姐/骑兵">
      </label>
      <label>
        <span>参考库范围</span>
        <input v-model="form.reference_scope_prefix" placeholder="骑兵/">
      </label>
    </div>

    <div class="task-actions task-actions-primary">
      <button class="danger" :disabled="busy" @click="runOneClickExecute">一键执行</button>
    </div>

    <div class="task-note">
      <p>现在不再需要填写批次数量，也不再保留预演 / 继续下一批入口。</p>
      <p>点击“一键执行”后，系统会按当前设置目录执行全部 ready 项；小批量增量整理更省心。</p>
      <p v-if="systemStatus">
        当前写入状态：
        READ_ONLY_MODE={{ systemStatus.read_only_mode }},
        ENABLE_REMOTE_WRITE={{ systemStatus.enable_remote_write }},
        ENABLE_REAL_MOVE={{ systemStatus.enable_real_move }}
      </p>
    </div>

    <div class="task-grid">
      <div class="task-card">
        <h4>当前任务</h4>
        <dl>
          <div><dt>source_id</dt><dd>{{ summary?.source_id || activeSource?.id || '—' }}</dd></div>
          <div><dt>scan_job</dt><dd>{{ activeScan?.id || '—' }}</dd></div>
          <div><dt>organizer_job</dt><dd>{{ activeJob?.id || summary?.organizer_job_id || '—' }}</dd></div>
          <div><dt>状态</dt><dd>{{ summary?.status || activeJob?.status || activeScan?.status || '—' }}</dd></div>
        </dl>
      </div>

      <div class="task-card stats">
        <h4>统计</h4>
        <div class="stats-grid">
          <div><strong>{{ summary?.scanned_count ?? 0 }}</strong><span>scanned_count</span></div>
          <div><strong>{{ summary?.identified_count ?? 0 }}</strong><span>identified_count</span></div>
          <div><strong>{{ summary?.ready_count ?? 0 }}</strong><span>ready_count</span></div>
          <div><strong>{{ summary?.moved_count ?? 0 }}</strong><span>moved_count</span></div>
          <div><strong>{{ summary?.remaining_ready_count ?? 0 }}</strong><span>remaining_ready_count</span></div>
          <div><strong>{{ summary?.missing_reference_count ?? 0 }}</strong><span>missing_reference_count</span></div>
          <div><strong>{{ summary?.unidentified_count ?? 0 }}</strong><span>unidentified_count</span></div>
          <div><strong>{{ summary?.conflict_count ?? 0 }}</strong><span>conflict_count</span></div>
          <div><strong>{{ summary?.failed_count ?? 0 }}</strong><span>failed_count</span></div>
        </div>
      </div>
    </div>

    <div class="task-card">
      <div class="result-head">
        <h4>{{ resultMode }}</h4>
        <small>最近结果最多显示 20 条</small>
      </div>
      <div class="table-wrap">
        <table class="task-table">
          <thead>
            <tr>
              <th>organizer_item_id</th>
              <th>identifier</th>
              <th>source_path</th>
              <th>target_path</th>
              <th>status</th>
              <th>error_message</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!results.length">
              <td colspan="6" class="empty">还没有执行结果，直接点“一键执行”即可。</td>
            </tr>
            <tr v-for="row in results" :key="`${row.status}-${row.organizer_item_id}-${row.target_path}`">
              <td>{{ row.organizer_item_id }}</td>
              <td>{{ row.identifier || '—' }}</td>
              <td class="path" :title="row.source_path">{{ row.source_path }}</td>
              <td class="path" :title="row.target_path">{{ row.target_path || '—' }}</td>
              <td><span :class="['task-status', row.status]">{{ row.status }}</span></td>
              <td>{{ row.error_message || '—' }}</td>
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

.task-form .grow {
  grid-column: span 1;
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

.task-stage {
  border-color: rgba(249, 115, 22, 0.35);
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

.task-card dl {
  margin: 0;
  display: grid;
  gap: 0.75rem;
}

.task-card dl div {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
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
  min-width: 10rem;
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
  max-width: 22rem;
  word-break: break-all;
}

.task-status {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.15);
}

.task-status.passed,
.task-status.moved,
.task-status.ready {
  background: rgba(34, 197, 94, 0.18);
  color: #bbf7d0;
}

.task-status.failed,
.task-status.skipped {
  background: rgba(248, 113, 113, 0.18);
  color: #fecaca;
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
  .task-panel {
    gap: 0.85rem;
  }

  .task-form label,
  .task-card,
  .task-note,
  .task-error {
    padding: 0.85rem;
  }

  .task-actions > * {
    width: 100%;
  }

  .danger {
    width: 100%;
    min-width: 0;
  }

  .task-card dl div,
  .result-head,
  .task-head {
    flex-direction: column;
    align-items: flex-start;
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

  .task-table .path {
    max-width: 14rem;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
