<template>
  <section class="page" data-module="chart">
    <header class="page-head">
      <div>
        <h2>可视化图表管理</h2>
        <p class="page-desc">维护可视化图表配置的输入、执行约束与结果记录，为图表展示提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记图表配置</button>
        <button class="btn" type="button" @click="exportRows">导出可视化图表清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无可视化图表数据，可先登记图表配置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条可视化图表记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="card" style="margin-top: 14px">
      <header class="detail-head">
        <div>
          <h4>聚合口径与试算证据</h4>
          <p class="page-desc">
            图表只读取聚合方案的发布版；草稿修改不会渗入这里。切换新版需显式确认，
            旧版证据作为历史保留，同一版重复确认不会新开一轮生效。
          </p>
        </div>
        <div class="detail-actions">
          <label class="field-item">
            <span>图表编号</span>
            <select v-model="evidenceChartId" @change="loadEvidence">
              <option v-for="row in rows" :key="String(row.id)" :value="row.图表编号">
                {{ row.图表编号 }}
              </option>
            </select>
          </label>
          <label class="field-item">
            <span>绑定聚合方案</span>
            <select v-model.number="bindPlanId">
              <option :value="0">选择已发布方案</option>
              <option v-for="plan in publishedPlans" :key="plan.plan_id" :value="plan.plan_id">
                {{ plan.plan_code }} · {{ plan.dataset_name }}
              </option>
            </select>
          </label>
          <button class="btn" type="button" @click="bindSelected">绑定当前生效版</button>
        </div>
      </header>
      <p v-if="evidenceMessage" class="banner notice">{{ evidenceMessage }}</p>
      <p v-if="evidenceError" class="banner error">{{ evidenceError }}</p>

      <table class="data-table compact">
        <thead>
          <tr>
            <th>方案 / 版本</th>
            <th>状态</th>
            <th>空值策略</th>
            <th>窗口条件</th>
            <th>舍入口径</th>
            <th>试算证据</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in evidenceItems" :key="item.binding_id">
            <td>
              {{ item.plan_code }} · {{ item.version_label }}
              <small>{{ item.published_at }}</small>
            </td>
            <td>
              {{ item.state === 'active' ? '生效中' : '历史证据' }}
              <small v-if="item.upgrade_available">有新版 {{ item.newer_versions.join('、') }}</small>
            </td>
            <td>
              <span v-for="(policy, metric) in item.null_policies" :key="metric" class="chip">
                {{ metricLabels[metric as MetricKey] }}：{{ policy.label }}
              </span>
            </td>
            <td>
              <span v-for="(window, metric) in item.window_conditions" :key="'w-' + metric" class="chip">
                {{ metricLabels[metric as MetricKey] }}：{{ window.mode_label }}
                {{ window.conditions.length }} 段
              </span>
            </td>
            <td>
              <small>{{ item.rounding.strategy }}</small>
              <small>{{ item.rounding.note }}</small>
              <small>冲突 {{ item.conflicts.length }} 处，以该发布版为准</small>
            </td>
            <td>
              <small>摘要 {{ item.trial_digest.slice(0, 10) }}</small>
              <small>{{ item.trial_groups.length }} 组；未归集 {{ item.unassigned.length }} 条</small>
            </td>
            <td class="row-actions">
              <button
                v-if="item.upgrade_available"
                class="link"
                type="button"
                @click="upgradeTo(item)"
              >
                升级到 {{ item.newer_versions[item.newer_versions.length - 1] }}
              </button>
              <button class="link danger" type="button" @click="unbind(item)">解除</button>
            </td>
          </tr>
          <tr v-if="!evidenceItems.length">
            <td colspan="7" class="empty-state">该图表尚未绑定聚合发布版，或所绑方案还没有发布。</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  bindChart,
  fetchChartEvidence,
  fetchPublishedPlans,
  unbindChart,
  upgradeChart,
} from '@/api/aggregate'
import type { ChartEvidence, MetricKey, PublishedPlan } from '@/api/aggregate'
import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const metricLabels: Record<MetricKey, string> = { sum: '求和', count: '计数', avg: '均值' }
const evidenceItems = ref<ChartEvidence[]>([])
const publishedPlans = ref<PublishedPlan[]>([])
const evidenceChartId = ref('CHAR-0003')
const bindPlanId = ref(0)
const evidenceMessage = ref('')
const evidenceError = ref('')

async function loadEvidence() {
  evidenceError.value = ''
  try {
    const payload = await fetchChartEvidence(evidenceChartId.value)
    evidenceItems.value = payload.items
  } catch (error) {
    evidenceItems.value = []
    evidenceError.value = error instanceof Error ? error.message : '图表证据读取失败'
  }
}

async function loadPublishedPlans() {
  try {
    const payload = await fetchPublishedPlans()
    publishedPlans.value = payload.items
  } catch {
    publishedPlans.value = []
  }
}

async function bindSelected() {
  evidenceError.value = ''
  evidenceMessage.value = ''
  if (!bindPlanId.value) {
    evidenceError.value = '请先选择一个已发布的聚合方案'
    return
  }
  try {
    const payload = await bindChart(evidenceChartId.value, bindPlanId.value)
    evidenceMessage.value = payload.message
    if (!payload.ok) {
      evidenceError.value = payload.message
      return
    }
    await loadEvidence()
  } catch (error) {
    evidenceError.value = error instanceof Error ? error.message : '绑定失败'
  }
}

async function upgradeTo(item: ChartEvidence) {
  const label = item.newer_versions[item.newer_versions.length - 1] ?? ''
  const target = Number(label.replace('v', ''))
  if (!target) return
  evidenceError.value = ''
  evidenceMessage.value = ''
  try {
    const payload = await upgradeChart(item.chart_id, item.plan_id, target)
    evidenceMessage.value = payload.message
    if (!payload.ok) {
      evidenceError.value = payload.message
      return
    }
    await loadEvidence()
  } catch (error) {
    evidenceError.value = error instanceof Error ? error.message : '升级失败'
  }
}

async function unbind(item: ChartEvidence) {
  evidenceError.value = ''
  evidenceMessage.value = ''
  try {
    const payload = await unbindChart(item.binding_id)
    evidenceMessage.value = payload.message
    if (!payload.ok) {
      evidenceError.value = payload.message
      return
    }
    await loadEvidence()
  } catch (error) {
    evidenceError.value = error instanceof Error ? error.message : '解除绑定失败'
  }
}

const ENDPOINT = '/api/chart'
const columns = ["图表编号", "图表名称", "图表类型", "数据来源", "X轴字段", "Y轴字段", "配色方案", "刷新间隔秒"]
const actions = ["提交发布", "发布图表", "下线图表"]
const statuses = ["草稿", "待发布", "已发布", "已下线"]
const stats = [{"label": "图表配置总数", "value": 0}, {"label": "已发布图表", "value": 0}, {"label": "待发布图表", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '图表配置登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('可视化图表动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '可视化图表操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('图表配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '可视化图表列表读取失败'
  }
}

onMounted(async () => {
  await reload()
  await Promise.all([loadPublishedPlans(), loadEvidence()])
})
</script>
