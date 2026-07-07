<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { loadAppSettings } from '../services/appSettings'

const STORAGE_KEY = 'western-poster-panel-form-v1'

const defaultForm = {
  root: '/mnt/local-media/data/strm/原始库/不正常视频/link/欧美',
  state_file: '/data/western-poster-state.json',
  process_all: false,
  dry_run: true,
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
const systemStatus = ref(null)

const canWrite = computed(() =>
  Boolean(
    systemStatus.value &&
      systemStatus.value.read_only_mode === false &&
      systemStatus.value.enable_remote_write === true
  )
)

watch(
  form,
  value => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
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
      root: settings.western_poster_defaults.root || form.value.root,
      state_file: settings.western_poster_defaults.state_file || form.value.state_file,
      process_all: settings.western_poster_defaults.process_all,
      dry_run: settings.western_poster_defaults.dry_run,
    }
  } catch {}
}

async function refreshState() {
  error.value = ''
  await loadSystemStatus()
}

async function runTask() {
  if (loading.value) return
  if (!form.value.dry_run && !canWrite.value) {
    error.value = '当前仍是只读状态，正式整理 poster/fanart 需要先打开 READ_ONLY_MODE=false 和 ENABLE_REMOTE_WRITE=true'
    return
  }

  const confirmed =
    form.value.dry_run ||
    window.confirm(
      `将真实写入 poster.jpg / fanart.jpg\n\n根目录：${form.value.root}\n状态文件：${form.value.state_file}\n模式：${form.value.process_all ? '全量重跑' : '增量处理'}\n\n确认开始？`
    )
  if (!confirmed) return

  loading.value = true
  error.value = ''
  try {
    result.value = await api('/api/v1/western-posters/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    await loadSystemStatus()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadDefaultSettings()
  loadSystemStatus()
})
</script>

<template>
  <section class="task-panel">
    <div class="task-head">
      <div>
        <span class="eyebrow">WESTERN POSTERS</span>
        <h3>欧美图片整理</h3>
        <p>把目录中的 <code>thumb.jpg</code> 统一整理成 <code>poster.jpg</code> 和 <code>fanart.jpg</code>，支持增量与 dry-run。</p>
      </div>
      <button @click="refreshState">刷新状态</button>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>

    <div class="task-form">
      <label class="grow">
        <span>根目录</span>
        <input v-model="form.root" placeholder="/mnt/local-media/data/strm/原始库/不正常视频/link/欧美">
      </label>
      <label class="grow">
        <span>状态文件</span>
        <input v-model="form.state_file" placeholder="/data/western-poster-state.json">
      </label>
      <label>
        <span>处理范围</span>
        <select v-model="form.process_all">
          <option :value="false">只处理新增/变更目录</option>
          <option :value="true">全量重跑</option>
        </select>
      </label>
      <label>
        <span>执行模式</span>
        <select v-model="form.dry_run">
          <option :value="true">先试跑（不改文件）</option>
          <option :value="false">正式执行</option>
        </select>
      </label>
    </div>

    <div class="task-actions task-actions-primary">
      <button class="primary" :disabled="loading" @click="runTask">
        {{ loading ? '执行中…' : form.dry_run ? '开始 dry-run' : '开始整理' }}
      </button>
    </div>

    <div class="task-note">
      <p>当前写入状态：READ_ONLY_MODE={{ systemStatus?.read_only_mode }}, ENABLE_REMOTE_WRITE={{ systemStatus?.enable_remote_write }}</p>
      <p>正式执行会复制 <code>thumb.jpg</code> 到 <code>poster.jpg</code> / <code>fanart.jpg</code>，并删除同目录旧的 <code>poster.jpeg</code> / <code>poster.png</code>。</p>
    </div>

    <div v-if="result" class="task-grid">
      <div class="task-card stats">
        <h4>执行统计</h4>
        <div class="stats-grid">
          <div><strong>{{ result.processed }}</strong><span>正式处理</span></div>
          <div><strong>{{ result.dry_run }}</strong><span>dry-run 命中</span></div>
          <div><strong>{{ result.skipped }}</strong><span>跳过</span></div>
          <div><strong>{{ result.touched.length }}</strong><span>展示样本</span></div>
        </div>
      </div>

      <div class="task-card stats">
        <h4>本次参数</h4>
        <div class="stats-grid">
          <div><strong>{{ result.process_all ? '全量' : '增量' }}</strong><span>处理范围</span></div>
          <div><strong>{{ result.dry_run_mode ? 'dry-run' : '正式' }}</strong><span>执行模式</span></div>
        </div>
      </div>
    </div>

    <div v-if="result" class="task-card">
      <div class="result-head">
        <h4>命中目录</h4>
        <small>最多显示 200 条</small>
      </div>
      <div class="table-wrap">
        <table class="task-table">
          <thead>
            <tr>
              <th>目录</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!result.touched.length">
              <td class="empty">这次没有命中任何需要处理的目录。</td>
            </tr>
            <tr v-for="path in result.touched" :key="path">
              <td class="path" :title="path">{{ path }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
