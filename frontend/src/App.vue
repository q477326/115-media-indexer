<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import NfoTagManager from './components/NfoTagManager.vue'
import OneClickIngestPanel from './components/OneClickIngestPanel.vue'
import OrganizerTaskPanel from './components/OrganizerTaskPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import TranslationPanel from './components/TranslationPanel.vue'
import WesternPosterPanel from './components/WesternPosterPanel.vue'

const files = ref([])
const view = ref('library')
const metadataItems = ref([])
const metadataTotal = ref(0)
const metadataPage = ref(1)
const metadataQuery = ref('')
const actorQuery = ref('')
const studioQuery = ref('')
const selectedMetadata = ref(null)
const importResult = ref(null)
const collectionKind = ref('actors')
const collectionItems = ref([])
const collectionTotal = ref(0)
const collectionPage = ref(1)
const collectionQuery = ref('')
const collectionSort = ref('file_count')
const collectionOrder = ref('desc')
const selectedCollection = ref(null)
const collectionFiles = ref([])
const collectionFileTotal = ref(0)
const collectionFilePage = ref(1)
const collectionFileQuery = ref('')
const systemStatus = ref(null)
const enrichmentJobs = ref([])
const selectedEnrichmentJob = ref(null)
const enrichmentLogs = ref([])
const enrichmentLogTotal = ref(0)
const enrichmentForm = ref({ scope: 'missing', identifiers: '', providers: ['reference_metadata', 'local_nfo', 'local_db', 'manual_csv'] })
const referenceHarvestForm = ref({
  reference_source_id: '',
  reference_scope_prefix: '骑兵/',
  providers: ['reference_metadata', 'local_nfo']
})
const enrichmentProviderOptions = [
  { name: 'reference_metadata', label: 'Reference Metadata', disabled: false },
  { name: 'local_nfo', label: 'Local NFO', disabled: false },
  { name: 'local_db', label: 'Local DB', disabled: false },
  { name: 'manual_csv', label: 'Manual CSV', disabled: false },
  { name: 'javbus', label: 'JavBus（禁用）', disabled: true },
  { name: 'jav321', label: 'Jav321（禁用）', disabled: true },
  { name: 'dmm', label: 'DMM（禁用）', disabled: true },
  { name: 'missav', label: 'MissAV（禁用）', disabled: true },
  { name: 'theporndb', label: 'ThePornDB（禁用）', disabled: true }
]
const enrichmentLogQuery = ref('')
const enrichmentLogProvider = ref('')
const enrichmentLogStatus = ref('')
let enrichmentPollTimer = null
const organizerJobs = ref([])
const selectedOrganizerJob = ref(null)
const organizerItems = ref([])
const organizerTotal = ref(0)
const organizerPage = ref(1)
const organizerQuery = ref('')
const organizerStatus = ref('')
const organizerForm = ref({
  mode: 'template_based',
  rule_template: '{prefix}/{identifier}/{filename}',
  scope: 'all',
  source_id: '',
  reference_source_id: '',
  reference_scope_prefix: '骑兵/',
  output_root: '/vol02/1000-1-2846ebc3/吴猛/小姐姐/骑兵',
  filename_strategy: 'match_reference_filename_with_source_suffix'
})
const organizerExamples = [
  '{prefix}/{identifier}/{filename}',
  '{studio}/{series}/{identifier}/{filename}',
  '{actor}/{identifier}/{filename}'
]
let organizerPollTimer = null
const sources = ref([])
const referenceSources = ref([])
const stats = ref({ total: 0, identified: 0, unidentified: 0, missing: 0, last_scan_at: null })
const total = ref(0)
const page = ref(1)
const pageSize = 50
const q = ref('')
const status = ref('')
const sourceId = ref('')
const loading = ref(false)
const scanningId = ref(null)
const activeScan = ref(null)
let pollTimer = null
const error = ref('')
const form = ref({ name: 'CloudDrive2', root_path: '/mnt/clouddrive' })

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const metadataPages = computed(() => Math.max(1, Math.ceil(metadataTotal.value / pageSize)))
const collectionPages = computed(() => Math.max(1, Math.ceil(collectionTotal.value / 24)))
const collectionFilePages = computed(() => Math.max(1, Math.ceil(collectionFileTotal.value / pageSize)))
const organizerPages = computed(() => Math.max(1, Math.ceil(organizerTotal.value / 100)))
const queryString = computed(() => {
  const params = new URLSearchParams()
  if (q.value) params.set('q', q.value)
  if (status.value) params.set('status', status.value)
  if (sourceId.value) params.set('source_id', sourceId.value)
  return params.toString()
})

async function api(path, options) {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  return response.status === 204 ? null : response.json()
}

async function loadFiles(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const suffix = [queryString.value, `page=${page.value}`, `page_size=${pageSize}`].filter(Boolean).join('&')
    const data = await api(`/api/v1/files?${suffix}`)
    files.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadOverview() {
  try {
    ;[sources.value, stats.value] = await Promise.all([api('/api/v1/sources'), api('/api/v1/stats')])
  } catch (e) {
    error.value = e.message
  }
}

async function loadMetadata(reset = false) {
  if (reset) metadataPage.value = 1
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ page: metadataPage.value, page_size: pageSize })
    if (metadataQuery.value) params.set('q', metadataQuery.value)
    if (actorQuery.value) params.set('actor', actorQuery.value)
    if (studioQuery.value) params.set('studio', studioQuery.value)
    const data = await api(`/api/v1/metadata?${params}`)
    metadataItems.value = data.items
    metadataTotal.value = data.total
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function openMetadata() {
  view.value = 'metadata'
  await loadReferenceSources()
  await loadMetadata()
}

function collectionName(item) {
  return item[collectionKind.value === 'actors' ? 'actor' : collectionKind.value === 'studios' ? 'studio' : 'series']
}

function collectionLabel(kind = collectionKind.value) {
  return kind === 'actors' ? '演员' : kind === 'studios' ? '厂商' : '系列'
}

async function loadCollections(reset = false) {
  if (reset) collectionPage.value = 1
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({
      page: collectionPage.value,
      page_size: 24,
      sort_by: collectionSort.value,
      sort_order: collectionOrder.value
    })
    if (collectionQuery.value) params.set('q', collectionQuery.value)
    const data = await api(`/api/v1/collections/${collectionKind.value}?${params}`)
    collectionItems.value = data.items
    collectionTotal.value = data.total
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function openCollections(kind = collectionKind.value) {
  collectionKind.value = kind
  collectionPage.value = 1
  view.value = 'collections'
  await loadCollections()
}

async function openSystem() {
  view.value = 'system'
  await loadSystemStatus()
}

function openSettings() {
  view.value = 'settings'
}

async function openEnrichment() {
  view.value = 'enrichment'
  await loadReferenceSources()
  await loadEnrichmentJobs()
}

async function openOrganizer() {
  view.value = 'organizer'
  await loadOverview()
  await loadReferenceSources()
  await loadOrganizerJobs()
}

function openTaskPanel() {
  view.value = 'task-panel'
}

function openOneClickIngest() {
  view.value = 'one-click-ingest'
}

function openTranslation() {
  view.value = 'translation'
}

function openNfoTags() {
  view.value = 'nfo-tags'
}

function openWesternPosters() {
  view.value = 'western-posters'
}

async function loadReferenceSources() {
  try {
    referenceSources.value = await api('/api/v1/reference-sources')
    if (!organizerForm.value.reference_source_id && referenceSources.value.length) {
      organizerForm.value.reference_source_id = referenceSources.value[0].id
    }
    if (!organizerForm.value.source_id && sources.value.length) {
      organizerForm.value.source_id = sources.value[0].id
    }
  } catch (e) {
    error.value = e.message
  }
}

async function loadOrganizerJobs() {
  try {
    organizerJobs.value = await api('/api/v1/organizer/jobs?limit=30')
    const running = organizerJobs.value.find(job => ['pending', 'running'].includes(job.status))
    if (running) {
      selectedOrganizerJob.value = running
      scheduleOrganizerPoll()
    } else if (!selectedOrganizerJob.value && organizerJobs.value.length) {
      await selectOrganizerJob(organizerJobs.value[0])
    }
  } catch (e) {
    error.value = e.message
  }
}

async function createOrganizerJob() {
  error.value = ''
  try {
    const payload = { ...organizerForm.value }
    if (payload.mode === 'reference_based') {
      payload.source_id = Number(payload.source_id)
      payload.reference_source_id = Number(payload.reference_source_id)
    } else {
      delete payload.source_id
      delete payload.reference_source_id
      delete payload.reference_scope_prefix
      delete payload.output_root
      delete payload.filename_strategy
    }
    selectedOrganizerJob.value = await api('/api/v1/organizer/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    organizerItems.value = []
    await loadOrganizerJobs()
    scheduleOrganizerPoll(100)
  } catch (e) {
    error.value = e.message
  }
}

async function selectOrganizerJob(job) {
  selectedOrganizerJob.value = job
  organizerPage.value = 1
  await loadOrganizerItems()
  if (['pending', 'running'].includes(job.status)) scheduleOrganizerPoll()
}

async function loadOrganizerItems(reset = false) {
  if (reset) organizerPage.value = 1
  if (!selectedOrganizerJob.value) return
  const params = new URLSearchParams({ page: organizerPage.value, page_size: 100 })
  if (organizerQuery.value) params.set('q', organizerQuery.value)
  if (organizerStatus.value) params.set('status', organizerStatus.value)
  try {
    const data = await api(`/api/v1/organizer/jobs/${selectedOrganizerJob.value.id}/items?${params}`)
    organizerItems.value = data.items
    organizerTotal.value = data.total
  } catch (e) {
    error.value = e.message
  }
}

function scheduleOrganizerPoll(delay = 700) {
  clearTimeout(organizerPollTimer)
  organizerPollTimer = setTimeout(pollOrganizerJob, delay)
}

async function pollOrganizerJob() {
  if (!selectedOrganizerJob.value) return
  try {
    selectedOrganizerJob.value = await api(`/api/v1/organizer/jobs/${selectedOrganizerJob.value.id}`)
    await loadOrganizerItems()
    if (['pending', 'running'].includes(selectedOrganizerJob.value.status)) {
      scheduleOrganizerPoll()
    } else {
      await loadOrganizerJobs()
    }
  } catch (e) {
    error.value = e.message
    scheduleOrganizerPoll(1500)
  }
}

function exportOrganizerPlan() {
  if (selectedOrganizerJob.value) {
    window.location.href = `/api/v1/organizer/jobs/${selectedOrganizerJob.value.id}/export.csv`
  }
}

async function loadEnrichmentJobs() {
  try {
    enrichmentJobs.value = await api('/api/v1/metadata/enrichment/jobs?limit=30')
    const running = enrichmentJobs.value.find(job => ['pending', 'running', 'stopping'].includes(job.status))
    if (running) {
      selectedEnrichmentJob.value = running
      scheduleEnrichmentPoll()
    } else if (!selectedEnrichmentJob.value && enrichmentJobs.value.length) {
      await selectEnrichmentJob(enrichmentJobs.value[0])
    }
  } catch (e) {
    error.value = e.message
  }
}

async function createEnrichmentJob() {
  error.value = ''
  try {
    const identifiers = enrichmentForm.value.identifiers.split(/[\s,;]+/).filter(Boolean)
    selectedEnrichmentJob.value = await api('/api/v1/metadata/enrichment/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope: enrichmentForm.value.scope,
        identifiers,
        providers: enrichmentForm.value.providers
      })
    })
    await loadEnrichmentJobs()
    scheduleEnrichmentPoll(100)
  } catch (e) {
    error.value = e.message
  }
}

async function createReferenceHarvestJob() {
  error.value = ''
  try {
    if (!referenceHarvestForm.value.reference_source_id) {
      throw new Error('请先选择参考源')
    }
    selectedEnrichmentJob.value = await api('/api/v1/metadata/harvest/reference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_source_id: Number(referenceHarvestForm.value.reference_source_id),
        reference_scope_prefix: referenceHarvestForm.value.reference_scope_prefix,
        providers: referenceHarvestForm.value.providers
      })
    })
    await loadEnrichmentJobs()
    scheduleEnrichmentPoll(100)
  } catch (e) {
    error.value = e.message
  }
}

async function selectEnrichmentJob(job) {
  selectedEnrichmentJob.value = job
  await loadEnrichmentLogs()
  if (['pending', 'running', 'stopping'].includes(job.status)) scheduleEnrichmentPoll()
}

async function loadEnrichmentLogs() {
  if (!selectedEnrichmentJob.value) return
  const params = new URLSearchParams({ page_size: 100 })
  if (enrichmentLogQuery.value) params.set('q', enrichmentLogQuery.value)
  if (enrichmentLogProvider.value) params.set('provider', enrichmentLogProvider.value)
  if (enrichmentLogStatus.value) params.set('status', enrichmentLogStatus.value)
  try {
    const data = await api(`/api/v1/metadata/enrichment/jobs/${selectedEnrichmentJob.value.id}/logs?${params}`)
    enrichmentLogs.value = data.items
    enrichmentLogTotal.value = data.total
  } catch (e) {
    error.value = e.message
  }
}

function scheduleEnrichmentPoll(delay = 700) {
  clearTimeout(enrichmentPollTimer)
  enrichmentPollTimer = setTimeout(pollEnrichmentJob, delay)
}

async function pollEnrichmentJob() {
  if (!selectedEnrichmentJob.value) return
  try {
    selectedEnrichmentJob.value = await api(`/api/v1/metadata/enrichment/jobs/${selectedEnrichmentJob.value.id}`)
    await loadEnrichmentLogs()
    if (['pending', 'running', 'stopping'].includes(selectedEnrichmentJob.value.status)) {
      scheduleEnrichmentPoll()
    } else {
      await Promise.all([loadEnrichmentJobs(), loadMetadata(), loadFiles()])
    }
  } catch (e) {
    error.value = e.message
    scheduleEnrichmentPoll(1500)
  }
}

async function stopEnrichmentJob() {
  if (!selectedEnrichmentJob.value) return
  try {
    selectedEnrichmentJob.value = await api(
      `/api/v1/metadata/enrichment/jobs/${selectedEnrichmentJob.value.id}/stop`,
      { method: 'POST' }
    )
    scheduleEnrichmentPoll(100)
  } catch (e) {
    error.value = e.message
  }
}

async function loadSystemStatus() {
  loading.value = true
  error.value = ''
  try {
    systemStatus.value = await api('/api/v1/system/status')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function downloadBackup(filename) {
  window.location.href = `/api/v1/backups/${filename}`
}

function downloadMissingMetadata() {
  window.location.href = '/api/v1/metadata/missing.csv'
}

async function openCollection(item) {
  selectedCollection.value = { kind: collectionKind.value, name: collectionName(item), item }
  collectionFilePage.value = 1
  collectionFileQuery.value = ''
  view.value = 'collection-detail'
  await loadCollectionFiles()
}

async function loadCollectionFiles(reset = false) {
  if (reset) collectionFilePage.value = 1
  if (!selectedCollection.value) return
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ page: collectionFilePage.value, page_size: pageSize })
    if (collectionFileQuery.value) params.set('q', collectionFileQuery.value)
    const selected = selectedCollection.value
    const data = await api(`/api/v1/collections/${selected.kind}/${encodeURIComponent(selected.name)}/files?${params}`)
    collectionFiles.value = data.items
    collectionFileTotal.value = data.total
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function showMetadata(identifier) {
  error.value = ''
  try {
    selectedMetadata.value = await api(`/api/v1/metadata/${encodeURIComponent(identifier)}`)
    view.value = 'detail'
  } catch (e) {
    error.value = e.message
  }
}

async function importCsv(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  importResult.value = null
  try {
    importResult.value = await api('/api/v1/metadata/import/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
      body: await file.arrayBuffer()
    })
    await Promise.all([loadMetadata(true), loadFiles(), loadOverview()])
  } catch (e) {
    error.value = e.message
  } finally {
    event.target.value = ''
  }
}

async function restoreActiveScan() {
  try {
    const scans = await api('/api/v1/scans?limit=1')
    if (scans.length && ['pending', 'running', 'stopping'].includes(scans[0].status)) {
      activeScan.value = scans[0]
      scanningId.value = scans[0].source_id
      schedulePoll()
    }
  } catch (e) {
    error.value = e.message
  }
}

async function addSource() {
  error.value = ''
  try {
    await api('/api/v1/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form.value, provider_type: 'local_fs' })
    })
    await loadOverview()
  } catch (e) {
    error.value = e.message
  }
}

async function scan(source) {
  scanningId.value = source.id
  error.value = ''
  try {
    activeScan.value = await api(`/api/v1/sources/${source.id}/scans`, { method: 'POST' })
    schedulePoll(100)
  } catch (e) {
    error.value = e.message
    scanningId.value = null
  }
}

function schedulePoll(delay = 700) {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(pollScan, delay)
}

async function pollScan() {
  if (!activeScan.value) return
  try {
    activeScan.value = await api(`/api/v1/scans/${activeScan.value.id}`)
    if (['pending', 'running', 'stopping'].includes(activeScan.value.status)) {
      schedulePoll()
    } else {
      scanningId.value = null
      await Promise.all([loadFiles(true), loadOverview()])
    }
  } catch (e) {
    error.value = e.message
    schedulePoll(1500)
  }
}

async function stopScan() {
  if (!activeScan.value) return
  try {
    activeScan.value = await api(`/api/v1/scans/${activeScan.value.id}/stop`, { method: 'POST' })
    schedulePoll(100)
  } catch (e) {
    error.value = e.message
  }
}

function formatSize(bytes) {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 2 : 0)} ${units[index]}`
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '尚未扫描'
}

function safeCover(url) {
  return url && (url.startsWith('data:image/') || url.startsWith('/')) ? url : null
}

function exportCsv() {
  window.location.href = `/api/v1/exports/files.csv?${queryString.value}`
}

onMounted(async () => {
  await Promise.all([loadFiles(), loadOverview()])
  await restoreActiveScan()
})
onUnmounted(() => {
  clearTimeout(pollTimer)
  clearTimeout(enrichmentPollTimer)
  clearTimeout(organizerPollTimer)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">115</span><div><h1>Media Indexer</h1><p>只读资源索引</p></div></div>
      <nav class="side-nav">
        <button :class="{ active: view === 'library' }" @click="view = 'library'">文件库</button>
        <button :class="{ active: ['metadata', 'detail'].includes(view) }" @click="openMetadata">番号元数据</button>
        <button :class="{ active: view === 'enrichment' }" @click="openEnrichment">补全任务</button>
        <button :class="{ active: view === 'translation' }" @click="openTranslation">AI 翻译</button>
        <button :class="{ active: view === 'nfo-tags' }" @click="openNfoTags">NFO标签</button>
        <button :class="{ active: view === 'western-posters' }" @click="openWesternPosters">欧美图片整理</button>
        <button :class="{ active: view === 'one-click-ingest' }" @click="openOneClickIngest">一键入库</button>
        <button :class="{ active: view === 'task-panel' }" @click="openTaskPanel">整理任务</button>
        <button :class="{ active: view === 'organizer' }" @click="openOrganizer">整理计划</button>
        <button :class="{ active: ['collections', 'collection-detail'].includes(view) }" @click="openCollections()">虚拟合集</button>
        <button :class="{ active: view === 'settings' }" @click="openSettings">设置中心</button>
        <button :class="{ active: view === 'system' }" @click="openSystem">系统状态</button>
      </nav>
      <div class="readonly">• READ ONLY</div>
    </aside>

    <main class="content">
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="view === 'library'">
    <section class="hero">
      <div><span class="eyebrow">LIBRARY OVERVIEW</span><h2>让挂载目录变得<br><em>清晰可查。</em></h2></div>
      <div class="stats">
        <div><strong>{{ stats.total }}</strong><span>全部文件</span></div>
        <div><strong>{{ stats.identified }}</strong><span>已识别</span></div>
        <div><strong>{{ stats.unidentified }}</strong><span>未识别</span></div>
        <div class="last-scan"><strong>{{ formatDate(stats.last_scan_at) }}</strong><span>最近扫描</span></div>
      </div>
    </section>

    <section class="source-panel">
      <div class="section-title"><div><span>01</span><h3>扫描源</h3></div><small>CloudDrive2 挂载目录需映射到容器内</small></div>
      <form @submit.prevent="addSource">
        <label>名称<input v-model="form.name" required placeholder="CloudDrive2"></label>
        <label class="grow">容器内路径<input v-model="form.root_path" required placeholder="/mnt/clouddrive"></label>
        <button class="primary" type="submit">添加目录</button>
      </form>
      <div v-if="sources.length" class="source-list">
        <div v-for="source in sources" :key="source.id" class="source-row">
          <div><b>{{ source.name }}</b><code>{{ source.root_path || source.root_file_id }}</code></div>
          <span class="provider">{{ source.provider_type }}</span>
          <button :disabled="scanningId !== null || source.provider_type !== 'local_fs'" @click="scan(source)">
            {{ scanningId === source.id ? '扫描中…' : '开始扫描' }}
          </button>
        </div>
      </div>
      <div v-if="activeScan" class="scan-progress">
        <div class="progress-head">
          <div><b>扫描任务 #{{ activeScan.id }}</b><span>{{ activeScan.status }}</span></div>
          <button v-if="['pending', 'running'].includes(activeScan.status)" class="stop" @click="stopScan">停止扫描</button>
        </div>
        <div class="progress-counts">
          <div><strong>{{ activeScan.scanned_count }}</strong><span>当前扫描</span></div>
          <div><strong>{{ activeScan.identified_count }}</strong><span>已识别</span></div>
          <div><strong>{{ activeScan.unidentified_count }}</strong><span>未识别</span></div>
          <div><strong>{{ activeScan.error_count }}</strong><span>错误</span></div>
        </div>
      </div>
    </section>

    <section class="files-panel">
      <div class="section-title"><div><span>02</span><h3>文件索引</h3></div><small>{{ total }} 条结果</small></div>
      <div class="toolbar">
        <input v-model="q" class="search" placeholder="搜索文件名、路径或番号…" @keyup.enter="loadFiles(true)">
        <select v-model="sourceId" @change="loadFiles(true)"><option value="">全部扫描源</option><option v-for="source in sources" :key="source.id" :value="source.id">{{ source.name }}</option></select>
        <select v-model="status" @change="loadFiles(true)"><option value="">全部状态</option><option value="identified">已识别</option><option value="unidentified">未识别</option><option value="missing">已离线</option></select>
        <button @click="loadFiles(true)">搜索</button>
        <button @click="exportCsv">导出 CSV</button>
      </div>
      <div class="table-wrap">
        <table class="files-table">
          <thead><tr><th>封面</th><th>文件</th><th>番号</th><th>标题</th><th>演员</th><th>厂商</th><th>大小</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="8" class="empty">正在读取索引…</td></tr>
            <tr v-else-if="!files.length"><td colspan="8" class="empty">暂无文件。添加挂载目录并开始第一次扫描。</td></tr>
            <tr v-for="file in files" v-else :key="file.id">
              <td><img v-if="safeCover(file.metadata?.cover_url)" class="cover-thumb" :src="safeCover(file.metadata.cover_url)" alt=""><span v-else class="cover-empty">—</span></td>
              <td><div class="filename" :title="file.filename">{{ file.filename }}</div><div class="path" :title="file.path">{{ file.path }}</div></td>
              <td><button v-if="file.metadata" class="identifier link" @click="showMetadata(file.identifier)">{{ file.identifier }}</button><span v-else-if="file.identifier" class="identifier">{{ file.identifier }}</span><span v-else>—</span></td>
              <td>{{ file.metadata?.title || '—' }}</td>
              <td>{{ file.metadata?.actors?.join('、') || '—' }}</td>
              <td>{{ file.metadata?.studio || '—' }}</td>
              <td class="nowrap">{{ formatSize(file.size) }}</td>
              <td><span :class="['status', file.status]">{{ file.status === 'identified' ? '已识别' : file.status === 'unidentified' ? '未识别' : '已离线' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination"><button :disabled="page <= 1" @click="page--; loadFiles()">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++; loadFiles()">下一页</button></div>
    </section>
    </template>

    <section v-else-if="view === 'metadata'" class="metadata-panel">
      <div class="section-title"><div><span>03</span><h3>番号元数据</h3></div><small>{{ metadataTotal }} 条元数据 · 仅来自 CSV 或 mock</small></div>
      <div class="metadata-actions">
        <label class="csv-upload">导入 CSV<input type="file" accept=".csv,text/csv" @change="importCsv"></label>
        <span>字段：identifier, title, plot, actors, studio, series, release_date, cover_url</span>
      </div>
            <div class="metadata-actions">
        <label>Reference Source
          <select v-model="referenceHarvestForm.reference_source_id">
            <option value="" disabled>Select reference source</option>
            <option v-for="source in referenceSources" :key="source.id" :value="source.id">{{ source.name }} #{{ source.id }}</option>
          </select>
        </label>
        <label>Scope Prefix
          <input v-model="referenceHarvestForm.reference_scope_prefix" placeholder="kibin/">
        </label>
        <button @click="createReferenceHarvestJob">Run Reference Harvest</button>
      </div>
<p v-if="importResult" class="success">导入完成：新增 {{ importResult.created }}，更新 {{ importResult.updated }}，跳过 {{ importResult.skipped }}</p>
      <div class="toolbar">
        <input v-model="metadataQuery" class="search" placeholder="搜索番号或标题…" @keyup.enter="loadMetadata(true)">
        <input v-model="actorQuery" placeholder="按演员搜索" @keyup.enter="loadMetadata(true)">
        <input v-model="studioQuery" placeholder="按厂商搜索" @keyup.enter="loadMetadata(true)">
        <button @click="loadMetadata(true)">搜索</button>
      </div>
      <div class="metadata-grid">
        <button v-for="item in metadataItems" :key="item.id" class="metadata-card" @click="showMetadata(item.identifier)">
          <div class="poster"><img v-if="safeCover(item.cover_url)" :src="safeCover(item.cover_url)" alt=""><span v-else>NO COVER</span></div>
          <div class="card-body"><b class="identifier">{{ item.identifier }}</b><h4>{{ item.title || '未填写标题' }}</h4><p>{{ item.actors.join('、') || '未填写演员' }}</p><small>{{ item.studio || '未填写厂商' }} · {{ item.source }}</small><p class="plot-preview">{{ item.plot || 'No plot' }}</p></div>
        </button>
        <p v-if="!loading && !metadataItems.length" class="empty">暂无元数据，请导入 UTF-8 CSV。</p>
      </div>
      <div class="pagination"><button :disabled="metadataPage <= 1" @click="metadataPage--; loadMetadata()">上一页</button><span>{{ metadataPage }} / {{ metadataPages }}</span><button :disabled="metadataPage >= metadataPages" @click="metadataPage++; loadMetadata()">下一页</button></div>
    </section>

    <section v-else-if="view === 'collections'" class="collections-panel">
      <div class="section-title"><div><span>04</span><h3>虚拟合集</h3></div><small>{{ collectionTotal }} 个{{ collectionLabel() }}合集</small></div>
      <div class="collection-tabs"><button v-for="kind in ['actors', 'studios', 'series']" :key="kind" :class="{ active: collectionKind === kind }" @click="openCollections(kind)">{{ collectionLabel(kind) }}</button></div>
      <div class="toolbar">
        <input v-model="collectionQuery" class="search" :placeholder="`搜索${collectionLabel()}…`" @keyup.enter="loadCollections(true)">
        <select v-model="collectionSort" @change="loadCollections(true)"><option value="file_count">按文件数</option><option value="latest_release_date">按最新发行日期</option></select>
        <select v-model="collectionOrder" @change="loadCollections(true)"><option value="desc">降序</option><option value="asc">升序</option></select>
        <button @click="loadCollections(true)">搜索</button>
      </div>
      <div class="collection-grid">
        <button v-for="item in collectionItems" :key="collectionName(item)" class="collection-card" @click="openCollection(item)">
          <div class="collection-cover"><img v-if="safeCover(item.cover_url)" :src="safeCover(item.cover_url)" alt=""><span v-else>{{ collectionLabel() }}</span></div>
          <div><h4>{{ collectionName(item) }}</h4><p><b>{{ item.file_count }}</b> 个文件 · {{ item.identifier_count }} 个番号</p><small>最新发行：{{ item.latest_release_date || '未知' }}</small></div>
        </button>
        <p v-if="!loading && !collectionItems.length" class="empty">没有符合条件的合集。</p>
      </div>
      <div class="pagination"><button :disabled="collectionPage <= 1" @click="collectionPage--; loadCollections()">上一页</button><span>{{ collectionPage }} / {{ collectionPages }}</span><button :disabled="collectionPage >= collectionPages" @click="collectionPage++; loadCollections()">下一页</button></div>
    </section>

    <section v-else-if="view === 'collection-detail' && selectedCollection" class="collection-detail-panel">
      <button class="back" @click="view = 'collections'">← 返回{{ collectionLabel(selectedCollection.kind) }}合集</button>
      <div class="collection-detail-head">
        <div class="mini-cover"><img v-if="safeCover(selectedCollection.item.cover_url)" :src="safeCover(selectedCollection.item.cover_url)" alt=""><span v-else>{{ collectionLabel(selectedCollection.kind) }}</span></div>
        <div><span class="eyebrow">{{ collectionLabel(selectedCollection.kind) }}合集</span><h2>{{ selectedCollection.name }}</h2><p>{{ collectionFileTotal }} 个文件 · {{ selectedCollection.item.identifier_count }} 个番号</p></div>
      </div>
      <div class="toolbar"><input v-model="collectionFileQuery" class="search" placeholder="搜索文件名、路径、番号或标题…" @keyup.enter="loadCollectionFiles(true)"><button @click="loadCollectionFiles(true)">搜索</button></div>
      <div class="table-wrap">
        <table class="collection-files-table"><thead><tr><th>文件名</th><th>路径</th><th>番号</th><th>标题</th><th>演员</th><th>厂商</th><th>系列</th><th>大小</th></tr></thead>
          <tbody><tr v-if="loading"><td colspan="8" class="empty">正在加载合集…</td></tr><tr v-else-if="!collectionFiles.length"><td colspan="8" class="empty">没有符合条件的文件。</td></tr>
            <tr v-for="file in collectionFiles" v-else :key="file.id"><td class="filename" :title="file.filename">{{ file.filename }}</td><td class="path" :title="file.path">{{ file.path }}</td><td><button class="identifier link" @click="showMetadata(file.identifier)">{{ file.identifier }}</button></td><td>{{ file.title || '—' }}</td><td>{{ file.actors.join('、') || '—' }}</td><td>{{ file.studio || '—' }}</td><td>{{ file.series || '—' }}</td><td class="nowrap">{{ formatSize(file.size) }}</td></tr>
          </tbody></table>
      </div>
      <div class="pagination"><button :disabled="collectionFilePage <= 1" @click="collectionFilePage--; loadCollectionFiles()">上一页</button><span>{{ collectionFilePage }} / {{ collectionFilePages }}</span><button :disabled="collectionFilePage >= collectionFilePages" @click="collectionFilePage++; loadCollectionFiles()">下一页</button></div>
    </section>

    <section v-else-if="view === 'one-click-ingest'">
      <OneClickIngestPanel />
    </section>

    <section v-else-if="view === 'task-panel'">
      <OrganizerTaskPanel />
    </section>

    <section v-else-if="view === 'translation'">
      <TranslationPanel />
    </section>

    <section v-else-if="view === 'nfo-tags'">
      <NfoTagManager />
    </section>

    <section v-else-if="view === 'western-posters'">
      <WesternPosterPanel />
    </section>

    <section v-else-if="view === 'organizer'" class="organizer-panel">
      <div class="section-title"><div><span>05</span><h3>整理计划 Dry-run</h3></div><button :disabled="!selectedOrganizerJob" @click="exportOrganizerPlan">导出计划 CSV</button></div>
      <div class="dry-run-warning"><b>只生成虚拟目标路径</b><span>本模块没有移动、改名、删除或执行计划的接口。</span></div>
      <div class="organizer-create">
        <label>模式<select v-model="organizerForm.mode"><option value="template_based">模板模式</option><option value="reference_based">参考 STRM（Dry-run）</option></select></label>
        <template v-if="organizerForm.mode === 'template_based'">
          <label class="grow">整理模板<input v-model="organizerForm.rule_template" list="organizer-templates" placeholder="{prefix}/{identifier}/{filename}"><datalist id="organizer-templates"><option v-for="example in organizerExamples" :key="example" :value="example"></option></datalist></label>
          <label>范围<select v-model="organizerForm.scope"><option value="all">全部索引文件</option><option value="identified">已识别番号</option><option value="with_metadata">已有 metadata</option><option value="missing_metadata">缺失 metadata</option></select></label>
        </template>
        <template v-else>
          <label>媒体源<select v-model="organizerForm.source_id"><option value="" disabled>请选择</option><option v-for="source in sources" :key="source.id" :value="source.id">{{ source.name }} #{{ source.id }}</option></select></label>
          <label>参考源<select v-model="organizerForm.reference_source_id"><option value="" disabled>请选择</option><option v-for="source in referenceSources" :key="source.id" :value="source.id">{{ source.name }} #{{ source.id }}</option></select></label>
          <label class="grow">参考范围前缀<input v-model="organizerForm.reference_scope_prefix" placeholder="骑兵/"></label>
          <label class="grow">输出根目录<input v-model="organizerForm.output_root" placeholder="/vol02/1000-1-2846ebc3/吴猛/小姐姐/骑兵"></label>
          <label class="grow">命名策略<select v-model="organizerForm.filename_strategy"><option value="match_reference_filename_with_source_suffix">match_reference_filename_with_source_suffix</option><option value="preserve_source_filename">preserve_source_filename</option></select></label>
        </template>
        <button class="primary" @click="createOrganizerJob">生成 Dry-run</button>
      </div>
      <div class="template-help"><code>{actor}</code><code>{studio}</code><code>{series}</code><code>{identifier}</code><code>{prefix}</code><code>{title}</code><code>{year}</code><code>{filename}</code><code>{ext}</code><span>多人演员第一版取第一位；filename 保留扩展名。</span></div>
      <div class="organizer-layout">
        <aside class="job-list"><h4>最近计划</h4><button v-for="job in organizerJobs" :key="job.id" :class="{ active: selectedOrganizerJob?.id === job.id }" @click="selectOrganizerJob(job)"><span>#{{ job.id }} · {{ job.mode || job.scope }}</span><b>{{ job.status }}</b><small>{{ job.processed_count }} / {{ job.total_count }}</small></button><p v-if="!organizerJobs.length" class="empty">暂无计划</p></aside>
        <div v-if="selectedOrganizerJob" class="organizer-detail">
          <div class="organizer-summary"><div><b>计划 #{{ selectedOrganizerJob.id }}</b><code>{{ selectedOrganizerJob.mode === 'reference_based' ? `${selectedOrganizerJob.output_root} · ${selectedOrganizerJob.reference_scope_prefix} · ${selectedOrganizerJob.filename_strategy} · source #${selectedOrganizerJob.source_id} · reference #${selectedOrganizerJob.reference_source_id}` : selectedOrganizerJob.rule_template }}</code></div><span :class="['plan-state', selectedOrganizerJob.status]">{{ selectedOrganizerJob.status }}</span></div>
          <div class="plan-counts"><div v-for="statusName in ['ready','missing_metadata','missing_reference','duplicate_reference','unidentified','conflict','invalid_path','skipped']" :key="statusName"><strong>{{ selectedOrganizerJob.status_counts?.[statusName] || 0 }}</strong><span>{{ statusName }}</span></div></div>
          <div class="toolbar"><input v-model="organizerQuery" class="search" placeholder="搜索源路径、目标路径或番号…" @keyup.enter="loadOrganizerItems(true)"><select v-model="organizerStatus" @change="loadOrganizerItems(true)"><option value="">全部状态</option><option value="ready">ready</option><option value="missing_metadata">missing_metadata</option><option value="missing_reference">missing_reference</option><option value="duplicate_reference">duplicate_reference</option><option value="unidentified">unidentified</option><option value="conflict">conflict</option><option value="invalid_path">invalid_path</option><option value="skipped">skipped</option></select><button @click="loadOrganizerItems(true)">筛选</button></div>
          <div class="table-wrap"><table class="organizer-table"><thead><tr><th>状态</th><th>番号</th><th>源路径</th><th>虚拟目标路径</th><th>错误原因</th></tr></thead><tbody><tr v-if="!organizerItems.length"><td colspan="5" class="empty">暂无计划条目</td></tr><tr v-for="item in organizerItems" :key="item.id"><td><span :class="['organizer-status', item.status]">{{ item.status }}</span></td><td class="identifier">{{ item.identifier || '—' }}</td><td class="path" :title="item.source_path">{{ item.source_path }}</td><td class="path" :title="item.target_path">{{ item.target_path || '—' }}</td><td>{{ item.error_message || '—' }}</td></tr></tbody></table></div>
          <div class="pagination"><button :disabled="organizerPage <= 1" @click="organizerPage--; loadOrganizerItems()">上一页</button><span>{{ organizerPage }} / {{ organizerPages }} · {{ organizerTotal }} 条</span><button :disabled="organizerPage >= organizerPages" @click="organizerPage++; loadOrganizerItems()">下一页</button></div>
        </div>
      </div>
    </section>

    <section v-else-if="view === 'enrichment'" class="enrichment-panel">
      <div class="section-title"><div><span>06</span><h3>元数据补全任务</h3></div><button @click="downloadMissingMetadata">导出缺失番号 CSV</button></div>
      <div class="enrichment-create">
        <h4>创建离线补全任务</h4>
        <div class="enrichment-form">
          <label>任务范围<select v-model="enrichmentForm.scope"><option value="missing">缺失元数据</option><option value="partial">部分元数据</option><option value="selected">指定番号</option></select></label>
          <label v-if="enrichmentForm.scope === 'selected'" class="grow">番号列表<textarea v-model="enrichmentForm.identifiers" placeholder="SSIS-001, IPZZ-123"></textarea></label>
          <button class="primary" @click="createEnrichmentJob">创建任务</button>
        </div>
        <div class="provider-options"><label v-for="provider in enrichmentProviderOptions" :key="provider.name" :class="{ disabled: provider.disabled }"><input v-model="enrichmentForm.providers" type="checkbox" :value="provider.name" :disabled="provider.disabled">{{ provider.label }}</label></div>
        <small>外部 Provider 第一版全部禁用，不会发起网络请求。</small>
      </div>
      <div class="enrichment-create">
        <h4>Reference Harvest</h4>
        <div class="enrichment-form">
          <label>Reference Source<select v-model="referenceHarvestForm.reference_source_id"><option value="" disabled>Select reference source</option><option v-for="source in referenceSources" :key="source.id" :value="source.id">{{ source.name }} #{{ source.id }}</option></select></label>
          <label class="grow">Scope Prefix<input v-model="referenceHarvestForm.reference_scope_prefix" placeholder="kibin/"></label>
          <button class="primary" @click="createReferenceHarvestJob">Create Reference Harvest</button>
        </div>
        <div class="provider-options"><label v-for="provider in enrichmentProviderOptions.filter(item => ['reference_metadata', 'local_nfo'].includes(item.name))" :key="provider.name"><input v-model="referenceHarvestForm.providers" type="checkbox" :value="provider.name">{{ provider.label }}</label></div>
        <small>This uses local reference STRM and local NFO only. No external requests.</small>
      </div>
      <div class="enrichment-layout">
        <aside class="job-list"><h4>最近任务</h4><button v-for="job in enrichmentJobs" :key="job.id" :class="{ active: selectedEnrichmentJob?.id === job.id }" @click="selectEnrichmentJob(job)"><span>#{{ job.id }} · {{ job.scope }}</span><b>{{ job.status }}</b><small>{{ job.processed_count }} / {{ job.total_count }}</small></button><p v-if="!enrichmentJobs.length" class="empty">暂无任务</p></aside>
        <div v-if="selectedEnrichmentJob" class="job-detail">
          <div class="progress-head"><div><b>任务 #{{ selectedEnrichmentJob.id }}</b><span>{{ selectedEnrichmentJob.status }}</span></div><button v-if="['pending', 'running'].includes(selectedEnrichmentJob.status)" class="stop" @click="stopEnrichmentJob">停止任务</button></div>
          <div class="enrichment-progress"><div class="bar" :style="{ width: `${selectedEnrichmentJob.total_count ? selectedEnrichmentJob.processed_count / selectedEnrichmentJob.total_count * 100 : 100}%` }"></div></div>
          <div class="progress-counts light"><div><strong>{{ selectedEnrichmentJob.total_count }}</strong><span>总数</span></div><div><strong>{{ selectedEnrichmentJob.processed_count }}</strong><span>已处理</span></div><div><strong>{{ selectedEnrichmentJob.completed_count }}</strong><span>已补全</span></div><div><strong>{{ selectedEnrichmentJob.unchanged_count }}</strong><span>未变化</span></div><div><strong>{{ selectedEnrichmentJob.failed_count }}</strong><span>失败</span></div></div>
          <div class="toolbar log-filter"><input v-model="enrichmentLogQuery" class="search" placeholder="筛选番号" @keyup.enter="loadEnrichmentLogs"><select v-model="enrichmentLogProvider" @change="loadEnrichmentLogs"><option value="">全部 Provider</option><option v-for="provider in enrichmentProviderOptions" :key="provider.name" :value="provider.name">{{ provider.name }}</option></select><select v-model="enrichmentLogStatus" @change="loadEnrichmentLogs"><option value="">全部状态</option><option value="cache_hit">cache_hit</option><option value="hit">hit</option><option value="miss">miss</option><option value="disabled">disabled</option><option value="timeout">timeout</option><option value="error">error</option></select><button @click="loadEnrichmentLogs">筛选</button></div>
          <div class="table-wrap"><table class="log-table"><thead><tr><th>番号</th><th>Provider</th><th>状态</th><th>耗时</th><th>重试</th><th>评分</th><th>错误</th></tr></thead><tbody><tr v-if="!enrichmentLogs.length"><td colspan="7" class="empty">暂无日志</td></tr><tr v-for="log in enrichmentLogs" :key="log.id"><td class="identifier">{{ log.identifier }}</td><td>{{ log.provider }}</td><td><span :class="['log-status', log.status]">{{ log.status }}</span></td><td>{{ log.duration_ms }} ms</td><td>{{ log.attempt }}</td><td>{{ log.score ?? '—' }}</td><td class="path">{{ log.error_message || '—' }}</td></tr></tbody></table></div>
          <small>共 {{ enrichmentLogTotal }} 条日志，当前显示最近 100 条。</small>
        </div>
      </div>
    </section>

    <section v-else-if="view === 'settings'">
      <SettingsPanel />
    </section>

    <section v-else-if="view === 'system'" class="system-panel">
      <div class="section-title"><div><span>07</span><h3>系统状态与备份</h3></div><button @click="loadSystemStatus">刷新状态</button></div>
      <div v-if="systemStatus" class="health-grid">
        <div class="health-card"><span>后端</span><b :class="systemStatus.backend_status === 'ok' ? 'good' : 'bad'">{{ systemStatus.backend_status }}</b></div>
        <div class="health-card"><span>SQLite</span><b :class="systemStatus.sqlite_status === 'ok' ? 'good' : 'bad'">{{ systemStatus.sqlite_status }}</b><small v-if="systemStatus.sqlite_error">{{ systemStatus.sqlite_error }}</small></div>
        <div class="health-card"><span>挂载目录</span><b :class="systemStatus.mount_readable ? 'good' : 'bad'">{{ systemStatus.mount_readable ? '可读' : '异常' }}</b></div>
        <div class="health-card"><span>扫描源</span><b>{{ systemStatus.source_count }}</b></div>
        <div class="health-card wide"><span>最近扫描</span><b>{{ formatDate(systemStatus.last_scan_at) }}</b></div>
      </div>
      <div v-if="systemStatus" class="safety-panel">
        <h4>安全开关</h4><div><span>READ_ONLY_MODE</span><b :class="systemStatus.read_only_mode ? 'good' : 'bad'">{{ systemStatus.read_only_mode }}</b></div><div><span>ENABLE_REMOTE_WRITE</span><b :class="!systemStatus.enable_remote_write ? 'good' : 'bad'">{{ systemStatus.enable_remote_write }}</b></div><div><span>ENABLE_EXTERNAL_METADATA</span><b :class="!systemStatus.enable_external_metadata ? 'good' : 'bad'">{{ systemStatus.enable_external_metadata }}</b></div>
      </div>
      <div v-if="systemStatus" class="mount-list"><h4>允许的挂载目录</h4><div v-for="mount in systemStatus.mounts" :key="mount.path"><code>{{ mount.path }}</code><span :class="mount.readable ? 'good' : 'bad'">{{ mount.readable ? '可读' : mount.error }}</span></div></div>
      <div class="backup-panel"><h4>手动备份导出</h4><p>SQLite 下载使用在线一致性快照，不会暂停扫描或修改媒体文件。</p><div class="backup-actions"><button class="primary" @click="downloadBackup('index.db')">导出 index.db</button><button @click="downloadBackup('metadata.csv')">导出 metadata CSV</button><button @click="downloadBackup('files.csv')">导出 files CSV</button></div></div>
    </section>

    <section v-else-if="view === 'detail' && selectedMetadata" class="detail-panel">
      <button class="back" @click="view = 'metadata'">← 返回元数据</button>
      <div class="detail-layout">
        <div class="detail-cover"><img v-if="safeCover(selectedMetadata.cover_url)" :src="safeCover(selectedMetadata.cover_url)" alt=""><span v-else>NO COVER</span></div>
        <div class="detail-content"><b class="identifier">{{ selectedMetadata.identifier }}</b><h2>{{ selectedMetadata.title || '未填写标题' }}</h2>
          <dl><dt>演员</dt><dd>{{ selectedMetadata.actors.join('、') || '—' }}</dd><dt>厂商</dt><dd>{{ selectedMetadata.studio || '—' }}</dd><dt>系列</dt><dd>{{ selectedMetadata.series || '—' }}</dd><dt>发行日期</dt><dd>{{ selectedMetadata.release_date || '—' }}</dd><dt>来源</dt><dd>{{ selectedMetadata.source }} / {{ selectedMetadata.confidence }}</dd></dl>
        </div>
      </div>
      <h3>关联文件</h3>
      <div v-for="file in selectedMetadata.files" :key="file.id" class="related-file"><b>{{ file.filename }}</b><code>{{ file.path }}</code><span>{{ formatSize(file.size) }}</span></div>
      <p v-if="!selectedMetadata.files.length" class="empty">当前没有关联文件。</p>
    </section>
      </main>
  </div>

  <footer>115 MEDIA INDEXER · 本系统不会读取视频内容或修改源文件</footer>
</template>
