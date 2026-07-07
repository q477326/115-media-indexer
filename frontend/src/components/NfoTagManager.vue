<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { loadAppSettings } from '../services/appSettings'

const STORAGE_KEY = 'nfo-tag-manager-form-v1'

const defaultForm = {
  folder_path: '/mnt/local-media/小姐姐/骑兵',
  search_type: 'title',
  q: '',
  tag_name: '',
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
const loading = ref(false)
const error = ref('')
const result = ref(null)
const items = ref([])
const selectedPaths = ref([])
const systemStatus = ref(null)

watch(
  form,
  value => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  },
  { deep: true }
)

const canWrite = computed(() =>
  Boolean(systemStatus.value && systemStatus.value.read_only_mode === false && systemStatus.value.enable_remote_write === true)
)

const allSelected = computed(() => items.value.length > 0 && selectedPaths.value.length === items.value.length)

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
      folder_path: settings.nfo_tag_defaults.folder_path || form.value.folder_path,
      search_type: settings.nfo_tag_defaults.search_type || form.value.search_type,
    }
  } catch {}
}

async function search() {
  if (!form.value.folder_path.trim() || !form.value.q.trim()) return
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({
      folder_path: form.value.folder_path.trim(),
      search_type: form.value.search_type,
      q: form.value.q.trim(),
      page: '1',
      page_size: '200',
    })
    result.value = await api(`/api/v1/nfo-tags/search?${params.toString()}`)
    items.value = result.value.items || []
    selectedPaths.value = items.value.map(item => item.file_path)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function toggleSelectAll() {
  selectedPaths.value = allSelected.value ? [] : items.value.map(item => item.file_path)
}

function togglePath(filePath) {
  if (selectedPaths.value.includes(filePath)) {
    selectedPaths.value = selectedPaths.value.filter(item => item !== filePath)
  } else {
    selectedPaths.value = [...selectedPaths.value, filePath]
  }
}

async function batchAddTag() {
  if (!selectedPaths.value.length || !form.value.tag_name.trim()) return
  loading.value = true
  error.value = ''
  try {
    const data = await api('/api/v1/nfo-tags/batch-add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_paths: selectedPaths.value,
        tag_name: form.value.tag_name.trim(),
      }),
    })
    await search()
    alert(`处理完成：命中 ${data.matched_count}，新增 ${data.added_count}，跳过 ${data.skipped_count}`)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadDefaultSettings()
  await loadSystemStatus()
})
</script>

<template>
  <section class="tag-panel">
    <div class="panel-head">
      <div>
        <span class="eyebrow">NFO TAG MANAGER</span>
        <h3>NFO 标签补充</h3>
        <p>按标题或原始标签搜索 NFO，然后增量补充一个公共标签；不会删除原标签，也不会重复写入。</p>
      </div>
      <button @click="loadSystemStatus">刷新状态</button>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>

    <div v-if="systemStatus" class="task-note">
      <p>
        当前写入状态：
        READ_ONLY_MODE={{ systemStatus.read_only_mode }},
        ENABLE_REMOTE_WRITE={{ systemStatus.enable_remote_write }}
      </p>
    </div>

    <div class="task-card">
      <div class="task-form">
        <label class="grow">
          <span>NFO 目录</span>
          <input v-model="form.folder_path" placeholder="/mnt/local-media/小姐姐/骑兵">
        </label>
        <label>
          <span>搜索方式</span>
          <select v-model="form.search_type">
            <option value="title">按标题搜索</option>
            <option value="raw_tag">按原始标签搜索</option>
          </select>
        </label>
        <label class="grow">
          <span>关键词</span>
          <input v-model="form.q" placeholder="例如：美腿 / 连裤袜 / 腿控" @keyup.enter="search">
        </label>
        <label>
          <span>追加标签</span>
          <input v-model="form.tag_name" placeholder="例如：美腿">
        </label>
      </div>

      <div class="task-actions">
        <button class="primary" :disabled="loading || !form.folder_path.trim() || !form.q.trim()" @click="search">搜索</button>
        <button class="ghost" :disabled="loading || !items.length" @click="toggleSelectAll">
          {{ allSelected ? '取消全选' : '全选结果' }}
        </button>
        <button
          class="danger"
          :disabled="loading || !canWrite || !selectedPaths.length || !form.tag_name.trim()"
          @click="batchAddTag"
        >
          增量追加标签
        </button>
      </div>
    </div>

    <div class="task-card">
      <div class="result-head">
        <div>
          <h4>搜索结果</h4>
          <small>当前 {{ selectedPaths.length }} / {{ result?.total || 0 }} 条已选</small>
        </div>
      </div>

      <div class="result-list">
        <article v-if="!items.length" class="empty-card">先搜索标题或原始标签，再对结果批量追加标签。</article>
        <article v-for="item in items" :key="item.file_path" class="result-item">
          <div class="result-summary">
            <label class="pick-row">
              <input
                :checked="selectedPaths.includes(item.file_path)"
                type="checkbox"
                @change="togglePath(item.file_path)"
              >
              <div class="result-main">
                <b class="identifier">{{ item.identifier || item.filename.replace(/\.nfo$/i, '') }}</b>
                <p class="result-title">{{ item.title || item.originaltitle || item.filename }}</p>
              </div>
            </label>
          </div>

          <div class="result-detail always-open">
            <div class="detail-block">
              <strong>文件路径</strong>
              <p>{{ item.file_path }}</p>
            </div>
            <div class="detail-block">
              <strong>当前原始标签</strong>
              <p>{{ item.raw_tags.length ? item.raw_tags.join('、') : '—' }}</p>
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.tag-panel {
  display: grid;
  gap: 1rem;
}

.panel-head,
.task-actions,
.result-head,
.result-summary {
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  align-items: center;
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.task-form label {
  display: grid;
  gap: 0.45rem;
}

.task-form .grow {
  grid-column: span 2;
}

.task-form input,
.task-form select {
  width: 100%;
}

.task-note {
  border-radius: 16px;
}

.task-error {
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.25);
}

.result-list {
  display: grid;
  gap: 0.75rem;
}

.pick-row {
  display: flex;
  gap: 0.8rem;
  align-items: flex-start;
  width: 100%;
}

.pick-row input {
  width: auto;
  margin-top: 0.2rem;
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

.result-detail {
  display: grid;
  gap: 0.75rem;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  padding-top: 0.9rem;
}

.always-open {
  padding-top: 0.9rem;
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

.empty-card {
  color: #94a3b8;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 760px) {
  .panel-head,
  .task-actions,
  .result-head,
  .result-summary {
    flex-direction: column;
    align-items: stretch;
  }

  .task-form {
    grid-template-columns: 1fr;
  }

  .task-form .grow {
    grid-column: span 1;
  }

  .task-actions > * {
    width: 100%;
  }
}
</style>
