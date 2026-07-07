<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { loadAppSettings } from '../services/appSettings'

const STORAGE_KEY = 'translation-panel-form-v1'
const SETTINGS_STORAGE_KEY = 'translation-api-settings-v1'
const RECENT_LIMIT = 3
const RESULTS_PAGE_SIZE = 20

const defaultPrompt = `你负责把当前目录中的 NFO 标题和简介整理成自然、顺口、像中文成人影视简介的简体中文。

要求：
1. 标题只写标题，不要把简介内容塞进标题，也不要写成长句或宣传语。
2. 保留番号、演员名、系列名、厂牌名等专有名词；人名优先使用常见中文译法。
3. 简介可以适度润色，但不要编造不存在的信息，不要过度扩写。
4. 允许露骨、直白、带有成人内容语气，但必须像中文成人影视简介，不能像逐字直译或关键词堆砌。
5. 避免生硬直译、词语硬拼、机械排比、奇怪口号式句子。
6. 避免类似“极致XXSEX”“敏感高潮臀”这类不自然表达，优先改成中文里更顺、更有情色文案感的说法。
7. 不要输出 HTML 标签，不要输出 <br>、<br/>、<br />，简介请直接用纯文本换行。
8. 如果原文已经是合格中文，只做轻微修正。`

const defaultForm = {
  name: 'JAV 本地媒体',
  folder_path: '/mnt/local-media/小姐姐/骑兵',
  prompt_template: defaultPrompt,
  enabled: true,
  recursive: true,
  auto_translate: false,
}

function loadStoredForm() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaultForm }
    return { ...defaultForm, ...JSON.parse(raw) }
  } catch {
    return { ...defaultForm }
  }
}

const form = ref(loadStoredForm())
const runtime = ref(null)
const apiSettings = ref({
  enabled: false,
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  model_name: 'gpt-4.1-mini',
  has_api_key: false,
  api_key_masked: '',
})
const folders = ref([])
const jobs = ref([])
const activeJob = ref(null)
const recentItems = ref([])
const recentTotal = ref(0)
const resultItems = ref([])
const resultTotal = ref(0)
const resultPage = ref(1)
const searchQuery = ref('')
const searchResults = ref([])
const searchTotal = ref(0)
const loading = ref(false)
const error = ref('')
const pageView = ref('panel')
const expandedItemIds = ref([])
let pollTimer = null

const canTranslate = computed(() =>
  Boolean(
    runtime.value &&
    runtime.value.read_only_mode === false &&
    runtime.value.enable_remote_write === true &&
    apiSettings.value.enabled === true &&
    (apiSettings.value.api_key.trim() || apiSettings.value.has_api_key)
  )
)

const resultPages = computed(() => Math.max(1, Math.ceil(resultTotal.value / RESULTS_PAGE_SIZE)))
const currentWatchFolder = computed(() => folders.value.find(folder => folder.folder_path === form.value.folder_path) || null)

const paginationItems = computed(() => {
  const total = resultPages.value
  const current = resultPage.value
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1)
  const pages = [1]
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  if (start > 2) pages.push('...')
  for (let page = start; page <= end; page += 1) pages.push(page)
  if (end < total - 1) pages.push('...')
  pages.push(total)
  return pages
})

watch(
  form,
  value => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  },
  { deep: true }
)

watch(
  () => form.value.folder_path,
  () => {
    searchResults.value = []
    searchTotal.value = 0
  }
)

function isJobActive(status) {
  return ['pending', 'running', 'stopping'].includes(status)
}

function isExpanded(itemId) {
  return expandedItemIds.value.includes(itemId)
}

function toggleExpanded(itemId) {
  if (isExpanded(itemId)) {
    expandedItemIds.value = expandedItemIds.value.filter(id => id !== itemId)
  } else {
    expandedItemIds.value = [...expandedItemIds.value, itemId]
  }
}

async function retryItem(item) {
  loading.value = true
  error.value = ''
  try {
    await api(`/api/v1/translation/items/${item.id}/retry`, { method: 'POST' })
    resetExpanded()
    await Promise.all([loadJobs(), loadRecentItems(), loadResultItems()])
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function resetExpanded() {
  expandedItemIds.value = []
}

function resultIdentifier(item) {
  const rawPath = item?.file_path || ''
  const filename = rawPath.split('/').pop() || rawPath.split('\\').pop() || ''
  return filename.replace(/\.nfo$/i, '') || '未识别'
}

async function api(path, options) {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const err = new Error(body.detail || `请求失败 (${response.status})`)
    err.status = response.status
    throw err
  }
  return response.status === 204 ? null : response.json()
}

async function loadRuntime() {
  runtime.value = await api('/api/v1/translation/runtime')
}

async function loadDefaultSettings() {
  try {
    const settings = await loadAppSettings()
    form.value = {
      ...form.value,
      name: settings.translation_defaults.name || form.value.name,
      folder_path: settings.translation_defaults.folder_path || form.value.folder_path,
      prompt_template: settings.translation_defaults.prompt_template || form.value.prompt_template,
      enabled: settings.translation_defaults.enabled,
      recursive: settings.translation_defaults.recursive,
      auto_translate: settings.translation_defaults.auto_translate,
    }
  } catch {}
}

async function loadApiSettings() {
  const saved = await api('/api/v1/translation/settings')
  let local = {}
  try {
    local = JSON.parse(window.localStorage.getItem(SETTINGS_STORAGE_KEY) || '{}')
  } catch {}
  apiSettings.value = {
    enabled: saved.enabled,
    api_key: local.api_key || '',
    base_url: saved.base_url,
    model_name: saved.model_name,
    has_api_key: saved.has_api_key,
    api_key_masked: saved.api_key_masked,
  }
}

async function loadFolders() {
  folders.value = await api('/api/v1/translation/watch-folders')
}

async function loadJobs() {
  jobs.value = await api('/api/v1/translation/jobs?limit=20')
  const activeStillExists = activeJob.value && jobs.value.some(job => job.id === activeJob.value.id)
  const preferredJob = jobs.value.find(
    job =>
      job.processed_count > 0 ||
      job.translated_count > 0 ||
      job.failed_count > 0 ||
      ['success', 'partial', 'failed'].includes(job.status)
  ) || jobs.value[0]

  const activeHasVisibleResults =
    activeJob.value &&
    (activeJob.value.processed_count > 0 || activeJob.value.translated_count > 0 || activeJob.value.failed_count > 0)

  if (
    jobs.value.length &&
    (!activeJob.value || !activeStillExists || (!activeHasVisibleResults && preferredJob?.id !== activeJob.value?.id))
  ) {
    await selectJob(preferredJob)
  }
}

async function loadRecentItems() {
  const data = await api(`/api/v1/translation/items?page=1&page_size=${RECENT_LIMIT}`)
  recentItems.value = data.items
  recentTotal.value = data.total
}

async function loadResultItems() {
  const data = await api(`/api/v1/translation/items?page=${resultPage.value}&page_size=${RESULTS_PAGE_SIZE}`)
  resultItems.value = data.items
  resultTotal.value = data.total
}

async function searchFiles() {
  if (!searchQuery.value.trim() || !form.value.folder_path.trim()) {
    searchResults.value = []
    searchTotal.value = 0
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({
      q: searchQuery.value.trim(),
      folder_path: form.value.folder_path.trim(),
      page: '1',
      page_size: '20',
    })
    const data = await api(`/api/v1/translation/files/search?${params.toString()}`)
    searchResults.value = data.items
    searchTotal.value = data.total
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function runSingleFile(item) {
  loading.value = true
  error.value = ''
  try {
    activeJob.value = await api('/api/v1/translation/files/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: item.file_path,
        watch_folder_id: currentWatchFolder.value?.id || null,
        prompt_template: form.value.prompt_template,
        mode: 'translate',
      }),
    })
    pageView.value = 'panel'
    resultPage.value = 1
    resetExpanded()
    await Promise.all([loadJobs(), loadRecentItems(), loadResultItems(), searchFiles()])
    schedulePoll(120)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function selectJob(job) {
  activeJob.value = job
  pageView.value = 'panel'
  resultPage.value = 1
  resetExpanded()
  await Promise.all([loadRecentItems(), loadResultItems()])
  if (isJobActive(job.status)) schedulePoll()
}

function applyFolder(folder) {
  form.value = {
    name: folder.name,
    folder_path: folder.folder_path,
    prompt_template: folder.prompt_template,
    enabled: folder.enabled,
    recursive: folder.recursive,
    auto_translate: folder.auto_translate,
  }
}

async function scanWatchFolder(folder) {
  loading.value = true
  error.value = ''
  try {
    const result = await api(`/api/v1/translation/watch-folders/${folder.id}/monitor-scan`, { method: 'POST' })
    await Promise.all([loadFolders(), loadJobs()])
    alert(`检查完成：已加入 ${result.queued_count} 个翻译任务`)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function removeWatchFolder(folder) {
  const ok = window.confirm(`移除目录配置：${folder.name}\n\n只会删除这个监控配置和基线记录，不会删除任何 NFO 或媒体文件。`)
  if (!ok) return
  loading.value = true
  error.value = ''
  try {
    await api(`/api/v1/translation/watch-folders/${folder.id}`, { method: 'DELETE' })
    if (form.value.folder_path === folder.folder_path) {
      form.value = { ...defaultForm }
    }
    await loadFolders()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function saveFolder() {
  loading.value = true
  error.value = ''
  try {
    await api('/api/v1/translation/watch-folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    await loadFolders()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function saveApiSettings() {
  loading.value = true
  error.value = ''
  try {
    const saved = await api('/api/v1/translation/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: apiSettings.value.enabled,
        api_key: apiSettings.value.api_key,
        base_url: apiSettings.value.base_url,
        model_name: apiSettings.value.model_name,
      }),
    })
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({ api_key: apiSettings.value.api_key }))
    apiSettings.value = {
      ...apiSettings.value,
      enabled: saved.enabled,
      has_api_key: saved.has_api_key,
      api_key_masked: saved.api_key_masked,
      base_url: saved.base_url,
      model_name: saved.model_name,
    }
    await loadRuntime()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function testApiSettings() {
  loading.value = true
  error.value = ''
  try {
    const result = await api('/api/v1/translation/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: apiSettings.value.enabled,
        api_key: apiSettings.value.api_key,
        base_url: apiSettings.value.base_url,
        model_name: apiSettings.value.model_name,
      }),
    })
    alert(`测试成功：${result.message}`)
  } catch (err) {
    error.value = err.message
    alert(`测试失败：${err.message}`)
  } finally {
    loading.value = false
  }
}

async function runJob(mode) {
  loading.value = true
  error.value = ''
  try {
    activeJob.value = await api('/api/v1/translation/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        folder_path: form.value.folder_path,
        prompt_template: form.value.prompt_template,
        mode,
      }),
    })
    pageView.value = 'panel'
    resultPage.value = 1
    resetExpanded()
    await Promise.all([loadFolders(), loadJobs(), loadRecentItems(), loadResultItems()])
    schedulePoll(120)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function stopJob() {
  if (!activeJob.value) return
  try {
    activeJob.value = await api(`/api/v1/translation/jobs/${activeJob.value.id}/stop`, { method: 'POST' })
    schedulePoll(120)
  } catch (err) {
    error.value = err.message
  }
}

async function openResultsPage() {
  pageView.value = 'results'
  resultPage.value = 1
  resetExpanded()
  await loadResultItems()
}

async function changeResultPage(page) {
  if (page < 1 || page > resultPages.value || page === resultPage.value) return
  resultPage.value = page
  resetExpanded()
  await loadResultItems()
}

function schedulePoll(delay = 900) {
  clearTimeout(pollTimer)
  pollTimer = window.setTimeout(pollJob, delay)
}

async function pollJob() {
  if (!activeJob.value) return
  try {
    activeJob.value = await api(`/api/v1/translation/jobs/${activeJob.value.id}`)
    await Promise.all([loadRecentItems(), loadResultItems()])
    if (isJobActive(activeJob.value.status)) {
      schedulePoll()
    } else {
      await loadJobs()
    }
  } catch (err) {
    if (err.status === 404) {
      clearTimeout(pollTimer)
      activeJob.value = null
      recentItems.value = []
      recentTotal.value = 0
      resultItems.value = []
      resultTotal.value = 0
      resultPage.value = 1
      resetExpanded()
      await loadJobs()
      return
    }
    error.value = err.message
    schedulePoll(1500)
  }
}

onMounted(async () => {
  await loadDefaultSettings()
  await Promise.all([loadRuntime(), loadApiSettings(), loadFolders(), loadJobs(), loadRecentItems(), loadResultItems()])
})

onUnmounted(() => {
  clearTimeout(pollTimer)
})
</script>

<template>
  <section class="translation-panel">
    <div class="panel-head">
      <div>
        <span class="eyebrow">AI TRANSLATION</span>
        <h3>AI 翻译</h3>
        <p>针对本地 NFO 做标题 / 简介分析与 AI 翻译，适合后续接目录监控。</p>
      </div>
      <div class="panel-actions">
        <button @click="loadRuntime">刷新状态</button>
        <button @click="loadFolders">刷新目录配置</button>
      </div>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>

    <div v-if="runtime" class="task-note">
      <p>
        当前状态：
        READ_ONLY_MODE={{ runtime.read_only_mode }},
        ENABLE_REMOTE_WRITE={{ runtime.enable_remote_write }},
        ENABLE_AI_TRANSLATION={{ runtime.enable_ai_translation }},
        API_KEY={{ runtime.ai_translation_configured ? '已配置' : '未配置' }}
      </p>
      <p>允许翻译目录：{{ runtime.allowed_translation_roots.join(' / ') }}</p>
    </div>

    <div class="task-card">
      <h4>OpenAI 相关配置</h4>
      <div class="task-form single">
        <label>
          <span>启用 AI 翻译</span>
          <select v-model="apiSettings.enabled">
            <option :value="true">true</option>
            <option :value="false">false</option>
          </select>
        </label>
        <label>
          <span>API 密钥</span>
          <input v-model="apiSettings.api_key" type="password" placeholder="sk-xxx">
          <small v-if="apiSettings.has_api_key && !apiSettings.api_key">已保存：{{ apiSettings.api_key_masked }}</small>
        </label>
        <label>
          <span>Base URL</span>
          <input v-model="apiSettings.base_url" placeholder="https://api.deepseek.com / https://4sapi.com/v1">
        </label>
        <label>
          <span>模型名称</span>
          <input v-model="apiSettings.model_name" placeholder="gpt-4.1 / deepseek-chat / grok-4.20-beta">
        </label>
      </div>
      <div class="task-actions task-actions-primary">
        <button :disabled="loading" @click="saveApiSettings">保存接口配置</button>
        <button class="primary" :disabled="loading" @click="testApiSettings">测试连接</button>
      </div>
    </div>

    <div class="translation-layout">
      <div class="task-card">
        <h4>翻译目录配置</h4>
        <div class="task-form single">
          <label>
            <span>配置名称</span>
            <input v-model="form.name" placeholder="JAV 本地媒体">
          </label>
          <label>
            <span>目录路径</span>
            <input v-model="form.folder_path" placeholder="/mnt/local-media/小姐姐/骑兵">
          </label>
          <label>
            <span>目录专用提示词</span>
            <textarea
              v-model="form.prompt_template"
              rows="10"
              placeholder="不同目录可以写不同提示词，例如 JAV / 欧美 / 纪录片。"
            />
          </label>
          <div class="toggle-grid">
            <label class="toggle-row">
              <input v-model="form.enabled" type="checkbox">
              <span>启用目录配置</span>
            </label>
            <label class="toggle-row">
              <input v-model="form.recursive" type="checkbox">
              <span>递归监控子目录</span>
            </label>
            <label class="toggle-row">
              <input v-model="form.auto_translate" type="checkbox">
              <span>自动翻译新增或修改的 NFO</span>
            </label>
          </div>
        </div>
        <div class="task-actions task-actions-primary">
          <button :disabled="loading" @click="saveFolder">保存目录配置</button>
          <button class="primary" :disabled="loading" @click="runJob('analyze')">先分析</button>
          <button class="danger" :disabled="loading || !canTranslate" @click="runJob('translate')">执行 AI 翻译</button>
          <button
            v-if="activeJob && ['pending', 'running', 'stopping'].includes(activeJob.status)"
            :disabled="loading"
            @click="stopJob"
          >
            停止任务
          </button>
        </div>

        <div class="inline-search">
          <div class="result-head">
            <div>
              <h4>按番号搜索并单独翻译</h4>
              <small>例如：SONE-001 / CAWD-950 / PRED-107</small>
            </div>
          </div>
          <div class="task-actions">
            <input
              v-model="searchQuery"
              class="search-input"
              placeholder="输入番号或文件名关键词"
              @keyup.enter="searchFiles"
            >
            <button class="ghost" :disabled="loading || !form.folder_path.trim()" @click="searchFiles">搜索</button>
          </div>
          <div class="folder-list">
            <div v-for="item in searchResults" :key="item.file_path" class="folder-row folder-config-row">
              <div class="folder-pick">
                <b>{{ item.identifier || item.filename.replace(/\.nfo$/i, '') }}</b>
                <small>{{ item.file_path }}</small>
                <small>
                  上次状态：{{ item.last_item_status || '未翻译' }} /
                  最近更新：{{ item.last_item_updated_at || '-' }}
                </small>
              </div>
              <div class="folder-actions">
                <button class="primary" :disabled="loading || !canTranslate" @click="runSingleFile(item)">翻译这一条</button>
              </div>
            </div>
            <p v-if="searchQuery.trim() && !searchResults.length" class="empty">当前目录下没有匹配到结果。</p>
            <p v-else-if="!searchQuery.trim()" class="empty">输入番号后搜索，可以只翻译单个 NFO。</p>
            <small v-if="searchResults.length" class="search-total">找到 {{ searchTotal }} 条，当前最多展示 20 条。</small>
          </div>
        </div>
      </div>

      <div class="task-card">
        <h4>已保存目录</h4>
        <div class="folder-list">
          <div v-for="folder in folders" :key="folder.id" class="folder-row folder-config-row">
            <button class="folder-pick" @click="applyFolder(folder)">
              <b>{{ folder.name }}</b>
              <small>{{ folder.folder_path }}</small>
              <small>
                {{ folder.enabled ? '启用' : '停用' }} /
                {{ folder.auto_translate ? '自动翻译' : '手动' }} /
                {{ folder.recursive ? '递归' : '当前目录' }}
              </small>
              <small>
                基线：{{ folder.monitor_initialized ? '已建立' : '未建立' }} /
                最近检查：{{ folder.last_scan_at || '-' }}
              </small>
              <small v-if="folder.last_error" class="folder-error">{{ folder.last_error }}</small>
            </button>
            <div class="folder-actions">
              <button class="ghost" :disabled="loading" @click="scanWatchFolder(folder)">立即检查</button>
              <button class="danger ghost-danger" :disabled="loading" @click="removeWatchFolder(folder)">移除</button>
            </div>
          </div>
          <p v-if="!folders.length" class="empty">还没有保存目录配置。</p>
        </div>
      </div>
    </div>

    <div class="task-grid">
      <div class="task-card">
        <h4>最近任务</h4>
        <div class="folder-list">
          <button
            v-for="job in jobs"
            :key="job.id"
            class="folder-row"
            :class="{ active: activeJob?.id === job.id }"
            @click="selectJob(job)"
          >
            <b>#{{ job.id }} / {{ job.mode }}</b>
            <small>{{ job.status }} / {{ job.processed_count }} / {{ job.total_count }}</small>
          </button>
          <p v-if="!jobs.length" class="empty">还没有翻译任务。</p>
        </div>
      </div>

      <div v-if="activeJob" class="task-card stats">
        <h4>任务统计</h4>
        <div class="stats-grid">
          <div><strong>{{ activeJob.total_count }}</strong><span>total_count</span></div>
          <div><strong>{{ activeJob.processed_count }}</strong><span>processed_count</span></div>
          <div><strong>{{ activeJob.translated_count }}</strong><span>translated_count</span></div>
          <div><strong>{{ activeJob.skipped_count }}</strong><span>skipped_count</span></div>
          <div><strong>{{ activeJob.failed_count }}</strong><span>failed_count</span></div>
          <div><strong>{{ activeJob.status }}</strong><span>status</span></div>
        </div>
        <p class="job-path">{{ activeJob.folder_path }}</p>
      </div>
    </div>

    <div v-if="pageView === 'panel'" class="task-card">
      <div class="result-head">
        <div>
          <h4>最近结果</h4>
          <small>当前显示 {{ recentItems.length }} / {{ recentTotal }}</small>
        </div>
        <div class="result-actions">
          <button v-if="recentTotal > RECENT_LIMIT" @click="openResultsPage">查看更多</button>
        </div>
      </div>

      <div class="result-list">
        <div v-if="!recentItems.length" class="empty-card">
          先跑一次“分析”或“执行 AI 翻译”。
        </div>
        <article v-for="item in recentItems" v-else :key="item.id" class="result-item">
          <div class="result-summary">
            <div class="result-main">
              <b class="identifier">{{ resultIdentifier(item) }}</b>
              <p class="result-title">{{ item.translated_title || '-' }}</p>
            </div>
            <div class="result-side">
              <span :class="['task-status', item.status]">{{ item.status }}</span>
              <button v-if="item.status === 'failed'" class="danger ghost-danger" :disabled="loading" @click="retryItem(item)">
                重试
              </button>
              <button class="ghost" @click="toggleExpanded(item.id)">
                {{ isExpanded(item.id) ? '收起' : '展开' }}
              </button>
            </div>
          </div>

          <div v-if="isExpanded(item.id)" class="result-detail">
            <div class="detail-block">
              <strong>文件路径</strong>
              <p>{{ item.file_path }}</p>
            </div>
            <div class="detail-block">
              <strong>原标题</strong>
              <p>{{ item.source_title || '-' }}</p>
            </div>
            <div class="detail-block">
              <strong>翻译后标题</strong>
              <p>{{ item.translated_title || '-' }}</p>
            </div>
            <div class="detail-grid">
              <div class="detail-block">
                <strong>Original Plot</strong>
                <p>{{ item.source_plot || '-' }}</p>
              </div>
              <div class="detail-block">
                <strong>Translated Plot</strong>
                <p>{{ item.translated_plot || '-' }}</p>
              </div>
            </div>
            <div v-if="item.error_message" class="detail-block">
              <strong>错误信息</strong>
              <p>{{ item.error_message }}</p>
            </div>
          </div>
        </article>
      </div>
    </div>

    <div v-else class="task-card">
      <div class="result-head">
        <div>
          <h4>翻译结果</h4>
          <small>第 {{ resultPage }} / {{ resultPages }} 页，共 {{ resultTotal }} 条</small>
        </div>
        <div class="result-actions">
          <button @click="pageView = 'panel'; resetExpanded()">返回最近结果</button>
        </div>
      </div>

      <div class="result-list">
        <div v-if="!resultItems.length" class="empty-card">当前没有可显示的翻译结果。</div>
        <article v-for="item in resultItems" v-else :key="item.id" class="result-item">
          <div class="result-summary">
            <div class="result-main">
              <b class="identifier">{{ resultIdentifier(item) }}</b>
              <p class="result-title">{{ item.translated_title || '-' }}</p>
            </div>
            <div class="result-side">
              <span :class="['task-status', item.status]">{{ item.status }}</span>
              <button v-if="item.status === 'failed'" class="danger ghost-danger" :disabled="loading" @click="retryItem(item)">
                重试
              </button>
              <button class="ghost" @click="toggleExpanded(item.id)">
                {{ isExpanded(item.id) ? '收起' : '展开' }}
              </button>
            </div>
          </div>

          <div v-if="isExpanded(item.id)" class="result-detail">
            <div class="detail-block">
              <strong>文件路径</strong>
              <p>{{ item.file_path }}</p>
            </div>
            <div class="detail-block">
              <strong>原标题</strong>
              <p>{{ item.source_title || '-' }}</p>
            </div>
            <div class="detail-block">
              <strong>翻译后标题</strong>
              <p>{{ item.translated_title || '-' }}</p>
            </div>
            <div class="detail-grid">
              <div class="detail-block">
                <strong>Original Plot</strong>
                <p>{{ item.source_plot || '-' }}</p>
              </div>
              <div class="detail-block">
                <strong>Translated Plot</strong>
                <p>{{ item.translated_plot || '-' }}</p>
              </div>
            </div>
            <div v-if="item.error_message" class="detail-block">
              <strong>错误信息</strong>
              <p>{{ item.error_message }}</p>
            </div>
          </div>
        </article>
      </div>

      <div v-if="resultTotal > RESULTS_PAGE_SIZE" class="pagination-bar">
        <button :disabled="resultPage <= 1" @click="changeResultPage(resultPage - 1)">上一页</button>
        <button
          v-for="pageItem in paginationItems"
          :key="`${pageItem}-${resultPage}`"
          :disabled="pageItem === '...'"
          :class="{ active: pageItem === resultPage, dots: pageItem === '...' }"
          @click="typeof pageItem === 'number' && changeResultPage(pageItem)"
        >
          {{ pageItem }}
        </button>
        <button :disabled="resultPage >= resultPages" @click="changeResultPage(resultPage + 1)">下一页</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.translation-panel {
  display: grid;
  gap: 1rem;
}

.panel-head,
.panel-actions,
.translation-layout,
.task-grid,
.task-actions,
.result-head,
.result-actions,
.result-summary,
.result-side,
.pagination-bar {
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  align-items: center;
}

.translation-layout,
.task-grid {
  align-items: stretch;
}

.translation-layout > *,
.task-grid > * {
  flex: 1;
}

.task-card,
.task-note,
.task-error,
.task-form label,
.result-item,
.empty-card {
  background: rgba(11, 18, 32, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 1rem;
}

.task-form {
  display: grid;
  gap: 0.9rem;
}

.task-form label {
  display: grid;
  gap: 0.45rem;
}

.task-form input,
.task-form textarea,
.task-form select {
  width: 100%;
}

.task-form.single {
  grid-template-columns: 1fr;
}

.task-form textarea {
  resize: vertical;
  min-height: 12rem;
}

.task-note {
  border-radius: 16px;
}

.task-error {
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.25);
}

.folder-list,
.result-list {
  display: grid;
  gap: 0.75rem;
}

.folder-row {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.3rem;
}

.folder-config-row {
  grid-template-columns: 1fr auto;
  align-items: center;
}

.folder-actions {
  display: grid;
  gap: 0.5rem;
}

.inline-search {
  display: grid;
  gap: 0.9rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
}

.search-input {
  min-width: 18rem;
}

.search-total {
  color: #94a3b8;
}

.folder-pick {
  text-align: left;
  display: grid;
  gap: 0.3rem;
}

.folder-error {
  color: #fecaca;
}

.toggle-grid {
  display: grid;
  gap: 0.6rem;
}

.toggle-row {
  display: flex !important;
  align-items: center;
  gap: 0.6rem !important;
}

.toggle-row input {
  width: auto;
}

.folder-row.active {
  border-color: rgba(255, 92, 53, 0.65);
}

.job-path {
  margin-top: 1rem;
  font-size: 0.9rem;
  word-break: break-all;
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

.result-item {
  display: grid;
  gap: 0.85rem;
}

.result-main {
  display: grid;
  gap: 0.3rem;
  min-width: 0;
}

.identifier {
  color: #ffb4a1;
  font-size: 0.95rem;
}

.result-title {
  margin: 0;
  font-size: 1rem;
  line-height: 1.45;
  word-break: break-word;
}

.result-side {
  flex-shrink: 0;
}

.result-detail {
  display: grid;
  gap: 0.75rem;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  padding-top: 0.9rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.detail-block {
  display: grid;
  gap: 0.35rem;
}

.detail-block strong {
  color: #cbd5e1;
  font-size: 0.9rem;
}

.detail-block p {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #e2e8f0;
  line-height: 1.55;
}

.task-status {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.15);
}

.task-status.candidate,
.task-status.translated,
.task-status.success {
  background: rgba(34, 197, 94, 0.18);
  color: #bbf7d0;
}

.task-status.failed,
.task-status.skipped {
  background: rgba(248, 113, 113, 0.18);
  color: #fecaca;
}

.danger {
  background: linear-gradient(135deg, #b91c1c, #ef4444);
  color: #fff;
}

.primary {
  background: #ff5c35;
  color: #fff;
}

.ghost {
  background: transparent;
  border: 1px solid rgba(148, 163, 184, 0.28);
}

.ghost-danger {
  border-color: rgba(248, 113, 113, 0.4);
}

.empty,
.empty-card {
  color: #94a3b8;
}

.result-actions {
  justify-content: flex-end;
}

.pagination-bar {
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 1rem;
}

.pagination-bar button.active {
  background: #ff5c35;
  color: #fff;
}

.pagination-bar button.dots {
  cursor: default;
  opacity: 0.7;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 1100px) {
  .panel-head,
  .panel-actions,
  .translation-layout,
  .task-grid,
  .task-actions,
  .result-head,
  .result-actions,
  .result-summary,
  .result-side {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .translation-panel {
    gap: 0.85rem;
  }

  .task-card,
  .task-note,
  .task-error,
  .task-form label,
  .result-item,
  .empty-card {
    padding: 0.85rem;
  }

  .panel-actions,
  .task-actions,
  .result-actions,
  .folder-actions {
    width: 100%;
  }

  .task-actions > *,
  .panel-actions > *,
  .folder-actions > * {
    width: 100%;
  }

  .folder-config-row {
    grid-template-columns: 1fr;
  }

  .search-input {
    min-width: 0;
    width: 100%;
  }

  .result-summary,
  .result-side {
    align-items: stretch;
  }

  .result-side {
    width: 100%;
  }

  .result-side > * {
    width: 100%;
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
