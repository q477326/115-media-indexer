<script setup>
import { onMounted, ref } from 'vue'
import { api, loadAppSettings } from '../services/appSettings'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const success = ref('')
const settings = ref(null)
const runtime = ref(null)
const translationApi = ref({
  enabled: false,
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  model_name: 'gpt-4.1-mini',
  has_api_key: false,
  api_key_masked: '',
})
const testResult = ref(null)

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [appSettings, systemStatus, translationSettings] = await Promise.all([
      loadAppSettings(),
      api('/api/v1/system/status'),
      api('/api/v1/translation/settings'),
    ])
    settings.value = appSettings
    runtime.value = systemStatus
    translationApi.value = {
      enabled: translationSettings.enabled,
      api_key: '',
      base_url: translationSettings.base_url,
      model_name: translationSettings.model_name,
      has_api_key: translationSettings.has_api_key,
      api_key_masked: translationSettings.api_key_masked,
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function saveDefaults() {
  if (!settings.value) return
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    settings.value = await api('/api/v1/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings.value),
    })
    success.value = '默认设置已保存到数据库，换浏览器后也会直接生效。'
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function saveTranslationApi() {
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const payload = {
      enabled: translationApi.value.enabled,
      api_key: translationApi.value.api_key || null,
      base_url: translationApi.value.base_url,
      model_name: translationApi.value.model_name,
    }
    const saved = await api('/api/v1/translation/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    translationApi.value = {
      enabled: saved.enabled,
      api_key: '',
      base_url: saved.base_url,
      model_name: saved.model_name,
      has_api_key: saved.has_api_key,
      api_key_masked: saved.api_key_masked,
    }
    success.value = 'AI 翻译接口设置已保存。'
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function testTranslationApi() {
  testing.value = true
  error.value = ''
  testResult.value = null
  try {
    testResult.value = await api('/api/v1/translation/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: translationApi.value.enabled,
        api_key: translationApi.value.api_key || null,
        base_url: translationApi.value.base_url,
        model_name: translationApi.value.model_name,
      }),
    })
  } catch (err) {
    error.value = err.message
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

<template>
  <section class="settings-panel">
    <div class="settings-head">
      <div>
        <span class="eyebrow">SETTINGS CENTER</span>
        <h3>设置中心</h3>
        <p>把常用目录、提示词和接口参数统一保存到数据库，换浏览器或换设备也能直接继续用。</p>
      </div>
      <button @click="loadAll">刷新</button>
    </div>

    <p v-if="error" class="task-error">{{ error }}</p>
    <p v-if="success" class="task-success">{{ success }}</p>

    <div v-if="runtime" class="settings-runtime">
      <div><span>READ_ONLY_MODE</span><strong :class="runtime.read_only_mode ? 'good' : 'bad'">{{ runtime.read_only_mode }}</strong></div>
      <div><span>ENABLE_REMOTE_WRITE</span><strong :class="runtime.enable_remote_write ? 'bad' : 'good'">{{ runtime.enable_remote_write }}</strong></div>
      <div><span>ENABLE_REAL_MOVE</span><strong :class="runtime.enable_real_move ? 'bad' : 'good'">{{ runtime.enable_real_move }}</strong></div>
      <div><span>CMS 同步</span><strong :class="runtime.cms_sync_configured ? 'good' : 'bad'">{{ runtime.cms_sync_configured ? '已配置' : '未配置' }}</strong></div>
    </div>

    <div v-if="settings" class="settings-grid">
      <section class="settings-card">
        <h4>整理任务默认值</h4>
        <label>
          <span>源目录</span>
          <input v-model="settings.organizer_task.source_root">
        </label>
        <label>
          <span>输出目录</span>
          <input v-model="settings.organizer_task.output_root">
        </label>
        <label>
          <span>参考范围前缀</span>
          <input v-model="settings.organizer_task.reference_scope_prefix">
        </label>
      </section>

      <section class="settings-card">
        <h4>一键入库默认值</h4>
        <label>
          <span>云下载目录</span>
          <input v-model="settings.one_click_ingest.source_root">
        </label>
        <label>
          <span>整理输出目录</span>
          <input v-model="settings.one_click_ingest.output_root">
        </label>
      </section>

      <section class="settings-card">
        <h4>AI 翻译默认值</h4>
        <label>
          <span>监控名称</span>
          <input v-model="settings.translation_defaults.name">
        </label>
        <label>
          <span>默认目录</span>
          <input v-model="settings.translation_defaults.folder_path">
        </label>
        <div class="settings-row">
          <label><input v-model="settings.translation_defaults.enabled" type="checkbox"> 启用目录配置</label>
          <label><input v-model="settings.translation_defaults.recursive" type="checkbox"> 递归</label>
          <label><input v-model="settings.translation_defaults.auto_translate" type="checkbox"> 自动翻译</label>
        </div>
        <label>
          <span>默认提示词</span>
          <textarea v-model="settings.translation_defaults.prompt_template" rows="10"></textarea>
        </label>
      </section>

      <section class="settings-card">
        <h4>NFO 标签默认值</h4>
        <label>
          <span>默认目录</span>
          <input v-model="settings.nfo_tag_defaults.folder_path">
        </label>
        <label>
          <span>默认搜索方式</span>
          <select v-model="settings.nfo_tag_defaults.search_type">
            <option value="title">标题</option>
            <option value="tag">标签</option>
          </select>
        </label>
      </section>

      <section class="settings-card">
        <h4>欧美图片整理默认值</h4>
        <label>
          <span>根目录</span>
          <input v-model="settings.western_poster_defaults.root">
        </label>
        <label>
          <span>状态文件</span>
          <input v-model="settings.western_poster_defaults.state_file">
        </label>
        <div class="settings-row">
          <label><input v-model="settings.western_poster_defaults.process_all" type="checkbox"> 默认全量重跑</label>
          <label><input v-model="settings.western_poster_defaults.dry_run" type="checkbox"> 默认先 dry-run</label>
        </div>
      </section>

      <section class="settings-card">
        <h4>AI 接口设置</h4>
        <label>
          <span>启用接口</span>
          <select v-model="translationApi.enabled">
            <option :value="true">启用</option>
            <option :value="false">关闭</option>
          </select>
        </label>
        <label>
          <span>API Key</span>
          <input v-model="translationApi.api_key" type="password" :placeholder="translationApi.has_api_key ? translationApi.api_key_masked || '已配置' : 'sk-...'">
        </label>
        <label>
          <span>Base URL</span>
          <input v-model="translationApi.base_url" placeholder="https://4sapi.com/v1">
        </label>
        <label>
          <span>模型名称</span>
          <input v-model="translationApi.model_name" placeholder="grok-4.20-beta">
        </label>
        <div class="settings-actions">
          <button :disabled="testing" @click="testTranslationApi">{{ testing ? '测试中…' : '测试连接' }}</button>
          <button class="primary" :disabled="saving" @click="saveTranslationApi">保存 AI 接口设置</button>
        </div>
        <p v-if="testResult" class="settings-test" :class="testResult.ok ? 'good' : 'bad'">
          {{ testResult.message }}
        </p>
      </section>
    </div>

    <div v-if="settings" class="settings-footer">
      <button class="primary" :disabled="saving" @click="saveDefaults">
        {{ saving ? '保存中…' : '保存默认设置' }}
      </button>
      <span>这些默认值会被整理任务、一键入库、AI 翻译、NFO 标签和欧美图片整理页面直接读取。</span>
    </div>
  </section>
</template>

<style scoped>
.settings-panel { display: grid; gap: 18px; }
.settings-head, .settings-runtime, .settings-actions, .settings-footer, .settings-row { display: flex; gap: 12px; }
.settings-head, .settings-footer { justify-content: space-between; align-items: center; }
.settings-runtime { flex-wrap: wrap; }
.settings-runtime > div {
  min-width: 180px;
  background: rgba(11, 18, 32, 0.06);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.settings-runtime span { color: #6b7280; font-size: 12px; }
.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}
.settings-card {
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,246,242,0.96));
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 20px;
  padding: 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
  display: grid;
  gap: 12px;
}
.settings-card h4 { margin: 0 0 6px; font-size: 16px; }
.settings-card label { display: grid; gap: 6px; }
.settings-card span { font-size: 12px; color: #6b7280; }
.settings-card textarea {
  width: 100%;
  border: 1px solid #dcd9d2;
  border-radius: 12px;
  padding: 12px;
  background: #fbfaf8;
  resize: vertical;
}
.settings-row { flex-wrap: wrap; align-items: center; }
.settings-row label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #374151;
}
.settings-row input[type="checkbox"] { width: auto; }
.settings-actions { justify-content: flex-start; align-items: center; }
.task-success, .settings-test {
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 13px;
}
.task-success { background: #e8f7ef; color: #176a46; }
.settings-footer span { color: #6b7280; font-size: 13px; }
@media (max-width: 860px) {
  .settings-head, .settings-footer { flex-direction: column; align-items: flex-start; }
  .settings-runtime { flex-direction: column; }
  .settings-runtime > div { width: 100%; }
}
</style>
