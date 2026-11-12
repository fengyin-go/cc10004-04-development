<template>
  <section class="page" data-module="aggregate">
    <header class="page-head">
      <div>
        <h2>聚合计算管理</h2>
        <p class="page-desc">
          先绑定数据集管理里的字段身份，再为求和、计数、均值分别配置空值策略、精度与时间窗口；
          用可编辑样本看每一组的贡献分解，确认后封存发布版供图表消费。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="reloadAll">刷新草稿与发布版</button>
        <button class="btn" type="button" @click="exportRows">导出聚合计算清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p v-if="errorMessage" class="banner error">{{ errorMessage }}</p>
    <p v-if="noticeMessage" class="banner notice">{{ noticeMessage }}</p>

    <div class="workspace">
      <aside class="plan-list">
        <h3>聚合方案</h3>
        <button
          v-for="entry in entries"
          :key="entry.id"
          class="plan-item"
          :class="{ active: entry.id === activeId }"
          type="button"
          @click="selectEntry(entry.id)"
        >
          <span class="plan-code">{{ entry.方案编号 }}</span>
          <span class="plan-meta">{{ entry.dataset_name ?? '未绑定数据集' }} · {{ entry.status }}</span>
          <span class="plan-meta">
            草稿 r{{ entry.draft_revision }} · 发布版
            <template v-if="entry.current_version">v{{ entry.current_version }}</template>
            <template v-else>未发布</template>
          </span>
        </button>
        <p v-if="!entries.length" class="empty-state">暂无聚合方案</p>
      </aside>

      <div v-if="entry" class="plan-detail">
        <header class="detail-head">
          <div>
            <h3>{{ entry.方案编号 }} · {{ definition.dataset_name ?? definition.dataset_id }}</h3>
            <p class="page-desc">
              草稿修订 r{{ entry.draft_revision }}；当前生效
              <strong>{{ entry.current_version ? 'v' + entry.current_version : '尚未发布' }}</strong>
              。字段按身份绑定，显示名只是快照。
            </p>
          </div>
          <div class="detail-actions">
            <button class="btn" type="button" @click="saveDraft">保存草稿并试算</button>
            <button class="btn primary" type="button" @click="publishVersion">发布当前口径</button>
          </div>
        </header>

        <section class="card">
          <h4>1. 绑定字段身份（来自数据集管理）</h4>
          <div class="bind-grid">
            <label class="field-item">
              <span>数据集</span>
              <select v-model="definition.dataset_id" @change="onDatasetChange">
                <option v-for="dataset in fieldCatalog" :key="dataset.dataset_id" :value="dataset.dataset_id">
                  {{ dataset.dataset_id }} · {{ dataset.dataset_name }}
                </option>
              </select>
            </label>
            <label class="field-item">
              <span>分组字段</span>
              <select :value="groupFieldId" @change="setGroupField(($event.target as HTMLSelectElement).value)">
                <option v-for="field in groupFieldOptions" :key="field.id" :value="field.id">
                  {{ field.name }}（{{ field.id }}）
                </option>
              </select>
            </label>
            <label class="field-item">
              <span>时间字段</span>
              <select :value="timeFieldId" @change="setTimeField(($event.target as HTMLSelectElement).value)">
                <option value="">不绑定</option>
                <option v-for="field in timeFieldOptions" :key="field.id" :value="field.id">
                  {{ field.name }}（{{ field.id }}）
                </option>
              </select>
            </label>
          </div>
        </section>

        <section class="card">
          <h4>2. 逐指标配置空值策略、精度与时间窗口</h4>
          <div class="metric-grid">
            <div v-for="name in metricOrder" :key="name" class="metric-card">
              <header>
                <label class="inline">
                  <input v-model="definition.metrics[name].enabled" type="checkbox" />
                  <strong>{{ metricLabels[name] }}</strong>
                </label>
                <select
                  :value="definition.metrics[name].field.field_id"
                  @change="setMetricField(name, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="field in fieldOptions" :key="field.id" :value="field.id">
                    {{ field.name }}（{{ field.id }}）
                  </option>
                </select>
              </header>
              <div class="metric-row">
                <label class="field-item">
                  <span>空值策略</span>
                  <select v-model="definition.metrics[name].null_policy">
                    <option value="exclude">排除（不参与分子分母）</option>
                    <option value="include">参与（空值按 0，均值仍占分母）</option>
                  </select>
                </label>
                <label class="field-item narrow">
                  <span>精度</span>
                  <select v-model.number="definition.metrics[name].precision">
                    <option v-for="digit in [0, 1, 2, 3, 4]" :key="digit" :value="digit">{{ digit }} 位</option>
                  </select>
                </label>
              </div>
              <div class="metric-row">
                <label class="field-item narrow">
                  <span>窗口</span>
                  <select v-model="definition.metrics[name].window.mode">
                    <option value="monthly">按月</option>
                    <option value="custom">自定义区间</option>
                    <option value="none">不设窗口</option>
                  </select>
                </label>
                <template v-if="definition.metrics[name].window.mode === 'monthly'">
                  <label class="field-item narrow">
                    <span>锚点</span>
                    <input v-model="definition.metrics[name].window.anchor" placeholder="2026-01-01" />
                  </label>
                  <label class="field-item narrow">
                    <span>连续月数</span>
                    <input v-model.number="definition.metrics[name].window.periods" type="number" min="1" max="60" />
                  </label>
                </template>
              </div>
              <div v-if="definition.metrics[name].window.mode === 'custom'" class="range-editor">
                <div
                  v-for="(range, index) in definition.metrics[name].window.ranges"
                  :key="index"
                  class="range-row"
                >
                  <input v-model="range.label" placeholder="区间名称" />
                  <input v-model="range.start" placeholder="2026-01-01T00:00:00" />
                  <input v-model="range.end" placeholder="2026-02-01T00:00:00" />
                  <button class="link danger" type="button" @click="removeRange(name, index)">删除</button>
                </div>
                <button class="link" type="button" @click="addRange(name)">+ 添加区间</button>
              </div>
              <p class="policy-hint">{{ policyHint(name) }}</p>
            </div>
          </div>
        </section>

        <section class="card">
          <h4>3. 可编辑样本（{{ samples.length }} 行）</h4>
          <div class="sample-tools">
            <button class="btn" type="button" @click="addSampleRow">新增样本行</button>
            <button class="btn ghost" type="button" @click="runTrialPreview">仅试算（不保存）</button>
            <span class="muted">改动样本或口径后保存草稿，会把试算结果一起算出来。</span>
          </div>
          <div class="table-scroll">
            <table class="data-table compact">
              <thead>
                <tr>
                  <th>行号</th>
                  <th v-for="field in fieldOptions" :key="field.id" :title="field.id">{{ field.name }}</th>
                  <th>备注</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, rowIndex) in samples" :key="row.row_id">
                  <td><input v-model="row.row_id" class="cell-input narrow" /></td>
                  <td v-for="field in fieldOptions" :key="field.id">
                    <input
                      :value="cellText(row, field.id)"
                      class="cell-input"
                      :placeholder="field.type === 'datetime' ? '2026-01-31T23:59:59' : '空值请留空'"
                      @input="setCell(row, field.id, ($event.target as HTMLInputElement).value)"
                    />
                  </td>
                  <td><input v-model="row.note" class="cell-input" /></td>
                  <td><button class="link danger" type="button" @click="removeSampleRow(rowIndex)">删除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="card">
          <h4>4. 发布版与图表消费方式</h4>
          <div class="version-grid">
            <div class="version-panel">
              <h5>本方案版本</h5>
              <table class="data-table compact">
                <thead>
                  <tr><th>版本</th><th>封存条件</th><th>状态</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="version in entry.versions ?? []" :key="version.version">
                    <td>{{ version.label }}<br /><small>{{ version.published_at }}</small></td>
                    <td>
                      <small>
                        指标 {{ Object.keys(version.null_policies).length }} 项 ·
                        窗口 {{ Object.keys(version.window_conditions).length }} 组 ·
                        冲突 {{ version.conflict_count }} 处
                      </small>
                    </td>
                    <td>{{ version.status }}</td>
                    <td class="row-actions">
                      <button class="link" type="button" @click="openVersion(version.version)">查看封存证据</button>
                    </td>
                  </tr>
                  <tr v-if="!(entry.versions ?? []).length">
                    <td colspan="4" class="empty-state">
                      尚未发布。发布后会封存本次试算采用的口径、窗口与样本。
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="version-panel">
              <h5>图表绑定与试算证据</h5>
              <div class="bind-controls">
                <label class="field-item">
                  <span>图表编号</span>
                  <input v-model="chartId" placeholder="CHAR-0003" @change="loadChartEvidence" />
                </label>
                <label class="field-item">
                  <span>绑定版本</span>
                  <select v-model.number="bindVersion">
                    <option :value="0">当前生效版</option>
                    <option v-for="version in entry.versions ?? []" :key="version.version" :value="version.version">
                      {{ version.label }}
                    </option>
                  </select>
                </label>
                <button class="btn" type="button" @click="bindSelectedChart">绑定</button>
                <button class="btn ghost" type="button" @click="loadChartEvidence">读取图表证据</button>
              </div>
              <table class="data-table compact">
                <thead>
                  <tr><th>图表</th><th>版本</th><th>状态</th><th>试算摘要</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="evidence in chartEvidence" :key="evidence.binding_id">
                    <td>{{ evidence.chart_id }}</td>
                    <td>{{ evidence.version_label }}</td>
                    <td>
                      {{ evidence.state === 'active' ? '生效中' : '历史证据' }}
                      <small v-if="evidence.upgrade_available">（有新版 {{ evidence.newer_versions.join('、') }}）</small>
                    </td>
                    <td>
                      <small>
                        摘要 {{ evidence.trial_digest.slice(0, 10) }} ·
                        冲突 {{ evidence.conflicts.length }} ·
                        草稿{{ evidence.draft_changed_since_publish ? '已' : '未' }}改动
                      </small>
                    </td>
                    <td class="row-actions">
                      <button
                        v-if="evidence.upgrade_available"
                        class="link"
                        type="button"
                        @click="upgradeSelectedChart(evidence)"
                      >
                        升级到新版
                      </button>
                      <button class="link danger" type="button" @click="unbindSelectedChart(evidence)">解除</button>
                    </td>
                  </tr>
                  <tr v-if="!chartEvidence.length">
                    <td colspan="5" class="empty-state">
                      该图表还没有绑定发布版；草稿不会被图表读取。
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="card">
          <h4>5. 可比较算例</h4>
          <p class="page-desc">
            三个算例按当前方案的字段身份重新映射；观察全空组、正负抵消与跨月边界在一组里的差异。
          </p>
          <div class="case-grid">
            <article v-for="item in cases" :key="item.case_id" class="case-card">
              <header>
                <strong>{{ item.label }}</strong>
                <button class="link" type="button" @click="loadCase(item)">载入样本</button>
              </header>
              <p class="case-desc">{{ item.description }}</p>
              <div class="case-metrics">
                <span>摘要 {{ item.trial.digest.slice(0, 10) }}</span>
                <span>顺序稳定 {{ item.trial.checks.order.stable ? '是' : '否' }}</span>
                <span>冲突 {{ item.trial.checks.window_conflicts.length }}</span>
              </div>
              <table class="data-table compact">
                <thead>
                  <tr><th>组</th><th>指标</th><th>窗口</th><th>状态</th><th>值</th></tr>
                </thead>
                <tbody>
                  <tr v-for="line in caseLines(item)" :key="line.key">
                    <td>{{ line.group }}</td>
                    <td>{{ line.metric }}</td>
                    <td>{{ line.window }}</td>
                    <td>{{ line.status }}</td>
                    <td>{{ line.value }}</td>
                  </tr>
                </tbody>
              </table>
            </article>
          </div>
        </section>

        <section class="card">
          <h4>6. 本次试算的贡献分解与口径检查</h4>
          <div v-if="trial" class="trial-head">
            <span>摘要 {{ trial.digest.slice(0, 12) }}</span>
            <span>样本 {{ trial.sample_count }} 行</span>
            <span :class="trial.checks.order.stable ? 'ok-text' : 'error-text'">
              输入顺序稳定：{{ trial.checks.order.stable ? '是（正序与反序摘要一致）' : '否' }}
            </span>
            <span>舍入：{{ trial.checks.rounding.position }}</span>
          </div>
          <div v-if="trial" class="legend-row">
            <span class="legend null-included">空值参与</span>
            <span class="legend null-excluded">空值排除</span>
            <span class="legend measured">数值</span>
            <span class="legend invalid">无效值</span>
          </div>

          <div v-if="trial && trial.checks.window_conflicts.length" class="conflict-box">
            <strong>窗口冲突：</strong>
            <ul>
              <li v-for="(conflict, index) in trial.checks.window_conflicts" :key="index">
                {{ conflict.metric_label }}：{{ conflict.left }} 与 {{ conflict.right }} 重叠，{{ conflict.rule }}
              </li>
            </ul>
          </div>
          <div v-if="trial" class="boundary-box">
            <strong>窗口归属：</strong>
            <ul>
              <li v-for="(boundary, index) in trial.checks.window_boundaries" :key="index">
                {{ boundary.metric_label }}：{{ boundary.rule }}
              </li>
              <li v-if="!trial.checks.window_boundaries.length">当前没有相邻窗口共用的边界。</li>
            </ul>
          </div>

          <div v-if="trial" class="group-grid">
            <article v-for="group in trial.groups" :key="group.group_key" class="group-card">
              <header>
                <strong>{{ group.group_display }}</strong>
                <small>键 {{ group.group_key || '(空)' }}</small>
              </header>
              <table class="data-table compact">
                <thead>
                  <tr>
                    <th>指标 / 窗口</th>
                    <th>状态</th>
                    <th>值</th>
                    <th>舍入</th>
                    <th>贡献</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="cell in group.cells" :key="cell.metric + cell.window_key">
                    <td>
                      {{ cell.metric_label }} · {{ cell.window_label }}
                      <small>({{ cell.included_rows }} 行)</small>
                    </td>
                    <td :title="cell.status_reason">{{ cell.status }}</td>
                    <td>
                      {{ cell.value ?? '—' }}
                      <small v-if="cell.raw_value">（原值 {{ cell.raw_value }}）</small>
                    </td>
                    <td>
                      <span :class="cell.rounding.same ? 'ok-text' : 'warn-text'">
                        {{ cell.rounding.same ? '一致' : '有差异' }}
                      </span>
                      <small>
                        汇总后 {{ cell.rounding.aggregate_then_round ?? '—' }} /
                        逐行 {{ cell.rounding.row_round_then_sum ?? '—' }}
                      </small>
                    </td>
                    <td>
                      <div class="contribution-list">
                        <span
                          v-for="item in cell.contributions"
                          :key="cell.metric + cell.window_key + item.row_id"
                          class="chip"
                          :class="item.role"
                          :title="`${item.row_id}：${item.reason}`"
                        >
                          {{ item.row_id }} {{ item.effective_value ?? '—' }}
                          <em v-if="item.share_percent">{{ item.share_percent }}%</em>
                        </span>
                        <span v-if="!cell.contributions.length" class="muted">无贡献行</span>
                      </div>
                      <small class="null-trace">
                        空值：参与 {{ cell.null_trace.included_blank_rows }} 行 / 排除
                        {{ cell.null_trace.excluded_blank_rows }} 行；{{ cell.null_trace.reasons.join('；') }}
                      </small>
                    </td>
                  </tr>
                </tbody>
              </table>
            </article>
          </div>

          <div v-if="trial" class="unassigned-box">
            <strong>未归集采样（窗口外或时间缺失）：</strong>
            <table class="data-table compact">
              <thead><tr><th>行号</th><th>指标</th><th>原因</th></tr></thead>
              <tbody>
                <tr v-for="(item, index) in trial.unassigned" :key="index">
                  <td>{{ item.row_id }}</td>
                  <td>{{ item.metric_label }}</td>
                  <td>{{ item.reason }}</td>
                </tr>
                <tr v-if="!trial.unassigned.length">
                  <td colspan="3" class="empty-state">所有采样都已归入窗口。</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="selectedVersion" class="card version-detail">
          <header class="detail-head">
            <h4>{{ selectedVersion.plan_code }} {{ selectedVersion.label }} 封存证据</h4>
            <button class="btn ghost" type="button" @click="selectedVersion = null">收起</button>
          </header>
          <p class="page-desc">
            {{ selectedVersion.conflict_precedence }}；封存时间 {{ selectedVersion.published_at }}；
            草稿{{ selectedVersion.draft_changed_since_publish ? '已' : '未' }}在封存后改动。
          </p>
          <div class="seal-grid">
            <div>
              <span class="stat-label">口径摘要</span>
              <small>{{ selectedVersion.definition_digest.slice(0, 24) }}</small>
            </div>
            <div>
              <span class="stat-label">样本摘要</span>
              <small>{{ selectedVersion.sample_digest.slice(0, 24) }}</small>
            </div>
            <div>
              <span class="stat-label">试算摘要</span>
              <small>{{ selectedVersion.trial.digest.slice(0, 24) }}</small>
            </div>
          </div>
          <div class="seal-grid">
            <div v-for="(policy, metric) in selectedVersion.null_policies" :key="metric">
              <span class="stat-label">{{ metricLabels[metric as MetricKey] }}空值</span>
              <strong>{{ policy.label }}</strong>
            </div>
            <div v-for="(window, metric) in selectedVersion.window_conditions" :key="'w-' + metric">
              <span class="stat-label">{{ metricLabels[metric as MetricKey] }}窗口</span>
              <strong>{{ window.mode_label }}（{{ window.conditions.length }} 段）</strong>
            </div>
          </div>
          <table class="data-table compact">
            <thead><tr><th>组</th><th>指标 / 窗口</th><th>状态</th><th>值</th><th>空值参与/排除</th></tr></thead>
            <tbody>
              <tr v-for="line in sealedLines(selectedVersion)" :key="line.key">
                <td>{{ line.group }}</td>
                <td>{{ line.metric }} · {{ line.window }}</td>
                <td>{{ line.status }}</td>
                <td>{{ line.value }}</td>
                <td>{{ line.nullRows }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
      <div v-else class="plan-detail empty-state">请选择一个聚合方案</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  bindChart,
  fetchCases,
  fetchChartEvidence,
  fetchEntry,
  fetchFieldCatalog,
  fetchVersion,
  listEntries,
  publishDraft,
  runTrial,
  saveDraft as persistDraft,
  unbindChart,
  upgradeChart,
} from '@/api/aggregate'
import type {
  AggregateDefinition,
  AggregateEntry,
  CaseTrial,
  ChartEvidence,
  DatasetCatalog,
  DatasetField,
  MetricKey,
  SampleRow,
  SealedVersion,
  TrialCell,
  TrialGroup,
  TrialResult,
  WindowMode,
} from '@/api/aggregate'

const metricOrder: MetricKey[] = ['sum', 'count', 'avg']
const metricLabels: Record<MetricKey, string> = { sum: '求和', count: '计数', avg: '均值' }

const entries = ref<AggregateEntry[]>([])
const activeId = ref<number | null>(null)
const entry = ref<(AggregateEntry & { definition: AggregateDefinition }) | null>(null)
const fieldCatalog = ref<DatasetCatalog[]>([])
const trial = ref<TrialResult | null>(null)
const cases = ref<CaseTrial[]>([])
const selectedVersion = ref<SealedVersion | null>(null)
const chartId = ref('CHAR-0003')
const chartEvidence = ref<ChartEvidence[]>([])
const bindVersion = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')

const definition = computed<AggregateDefinition>(() => {
  if (!entry.value) {
    return blankDefinition()
  }
  return entry.value.definition as AggregateDefinition
})

const samples = computed<SampleRow[]>(() => entry.value?.samples ?? [])

const activeDataset = computed<DatasetCatalog | null>(
  () => fieldCatalog.value.find((item) => item.dataset_id === definition.value.dataset_id) ?? null,
)

const fieldOptions = computed<DatasetField[]>(() => activeDataset.value?.fields ?? [])
const groupFieldOptions = computed(() =>
  fieldOptions.value.filter((field) => field.role === 'group' || field.role === 'id'),
)
const timeFieldOptions = computed(() => fieldOptions.value.filter((field) => field.role === 'time'))

const groupFieldId = computed(() => definition.value.group_fields[0]?.field_id ?? '')
const timeFieldId = computed(() => definition.value.time_field?.field_id ?? '')

const stats = computed(() => [
  { label: '聚合方案总数', value: entries.value.length },
  { label: '已发布版本', value: entries.value.filter((item) => item.current_version > 0).length },
  { label: '草稿待发布', value: entries.value.filter((item) => item.current_version === 0).length },
])

function blankDefinition(): AggregateDefinition {
  return {
    dataset_id: '',
    group_fields: [],
    time_field: null,
    metrics: {
      sum: { enabled: true, field: { field_id: '' }, null_policy: 'exclude', precision: 2, window: { mode: 'monthly', anchor: '2026-01-01', periods: 2, ranges: [] } },
      count: { enabled: true, field: { field_id: '' }, null_policy: 'exclude', precision: 0, window: { mode: 'monthly', anchor: '2026-01-01', periods: 2, ranges: [] } },
      avg: { enabled: true, field: { field_id: '' }, null_policy: 'exclude', precision: 2, window: { mode: 'monthly', anchor: '2026-01-01', periods: 2, ranges: [] } },
    },
  }
}

function cellText(row: SampleRow, fieldId: string): string {
  const value = row.values[fieldId]
  return value === null || value === undefined ? '' : String(value)
}

function setCell(row: SampleRow, fieldId: string, value: string) {
  row.values[fieldId] = value.trim() === '' ? null : value
}

function policyHint(name: MetricKey): string {
  const metric = definition.value.metrics[name]
  const policy = metric.null_policy === 'include' ? '参与' : '排除'
  if (name === 'count') {
    return policy === '参与' ? '空值计为 1 条；每一行都进入条数。' : '空值不计条；只统计非空行的条数。'
  }
  if (name === 'avg') {
    return policy === '参与' ? '空值按 0 计入分子且仍占分母，均值会被拉低。' : '空值整行剔除，不进入分子与分母。'
  }
  return policy === '参与' ? '空值按 0 参与求和，不改变总额。' : '空值不计入求和，总额只由有效数值构成。'
}

function exportRows() {
  window.open('/api/aggregate/export', '_blank')
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    const [catalog, list] = await Promise.all([fetchFieldCatalog(), listEntries()])
    fieldCatalog.value = catalog.items
    entries.value = list.items
    if (!activeId.value && entries.value.length) {
      activeId.value = entries.value[0].id
    }
    if (activeId.value) {
      await selectEntry(activeId.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '聚合方案读取失败'
  }
}

async function selectEntry(entryId: number) {
  activeId.value = entryId
  errorMessage.value = ''
  try {
    const payload = await fetchEntry(entryId)
    if (!payload.definition) {
      // 新登记、尚未绑定数据集的方案：给一份空口径，编辑后再保存。
      payload.definition = blankDefinition()
    }
    entry.value = payload
    selectedVersion.value = null
    await loadTrialAndCases()
    await loadChartEvidence()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '聚合方案明细读取失败'
  }
}

async function loadTrialAndCases() {
  if (!activeId.value) return
  const [trialPayload, casePayload] = await Promise.all([
    runTrial(activeId.value).catch(() => null),
    fetchCases(activeId.value).catch(() => null),
  ])
  trial.value = trialPayload?.trial ?? null
  cases.value = casePayload?.items ?? []
}

async function saveDraft() {
  if (!activeId.value || !entry.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload = await persistDraft(activeId.value, definition.value, samples.value)
    noticeMessage.value = payload.message
    if (payload.ok) {
      await selectEntry(activeId.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '草稿保存失败'
  }
}

async function runTrialPreview() {
  if (!activeId.value) return
  errorMessage.value = ''
  try {
    const payload = await runTrial(activeId.value)
    if (!payload.ok || !payload.trial) {
      errorMessage.value = payload.message
      return
    }
    trial.value = payload.trial
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试算失败'
  }
}

async function publishVersion() {
  if (!activeId.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload = await publishDraft(activeId.value)
    noticeMessage.value = payload.message
    if (!payload.ok) {
      return
    }
    await selectEntry(activeId.value)
    if (payload.entry) {
      selectedVersion.value = payload.entry
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布失败'
  }
}

async function openVersion(version: number) {
  if (!activeId.value) return
  errorMessage.value = ''
  try {
    selectedVersion.value = await fetchVersion(activeId.value, version)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布版读取失败'
  }
}

function onDatasetChange() {
  if (!entry.value) return
  const dataset = activeDataset.value
  if (!dataset) return
  const group = dataset.fields.find((field) => field.role === 'group')
  const time = dataset.fields.find((field) => field.role === 'time')
  definition.value.group_fields = group ? [{ field_id: group.id }] : []
  definition.value.time_field = time ? { field_id: time.id } : null
  const identity = dataset.fields.find((field) => field.role === 'id')
  const measure = dataset.fields.find((field) => field.role === 'measure')
  for (const name of metricOrder) {
    // 计数默认绑身份字段（空/非空形态好读），求和与均值默认绑度量字段。
    const target = name === 'count' ? identity ?? measure : measure ?? identity
    definition.value.metrics[name].field = { field_id: target?.id ?? '' }
  }
  entry.value.samples = []
}

function setGroupField(fieldId: string) {
  definition.value.group_fields = [{ field_id: fieldId }]
}

function setTimeField(fieldId: string) {
  definition.value.time_field = fieldId ? { field_id: fieldId } : null
}

function setMetricField(name: MetricKey, fieldId: string) {
  definition.value.metrics[name].field = { field_id: fieldId }
}

function addRange(name: MetricKey) {
  definition.value.metrics[name].window.ranges.push({ label: `区间${definition.value.metrics[name].window.ranges.length + 1}`, start: '2026-01-01T00:00:00', end: '2026-02-01T00:00:00' })
}

function removeRange(name: MetricKey, index: number) {
  definition.value.metrics[name].window.ranges.splice(index, 1)
}

function addSampleRow() {
  if (!entry.value) return
  const row: SampleRow = {
    row_id: `R-${String(entry.value.samples.length + 1).padStart(3, '0')}`,
    note: '',
    values: {},
  }
  for (const field of fieldOptions.value) {
    row.values[field.id] = null
  }
  entry.value.samples = [...entry.value.samples, row]
}

function removeSampleRow(index: number) {
  if (!entry.value) return
  entry.value.samples = entry.value.samples.filter((_, position) => position !== index)
}

function loadCase(item: CaseTrial) {
  if (!entry.value) return
  entry.value.samples = item.samples.map((row) => ({ ...row, values: { ...row.values } }))
  trial.value = item.trial
  noticeMessage.value = `已载入算例「${item.label}」，保存草稿前不会改动发布版`
}

function caseLines(item: CaseTrial) {
  return flattenGroups(item.trial.groups)
}

function sealedLines(version: SealedVersion) {
  return flattenGroups(version.trial.groups)
}

function flattenGroups(groups: TrialGroup[]) {
  const lines: {
    key: string
    group: string
    metric: string
    window: string
    status: string
    value: string
    nullRows: string
  }[] = []
  for (const group of groups) {
    for (const cell of group.cells) {
      lines.push({
        key: `${group.group_key}-${cell.metric}-${cell.window_key}`,
        group: group.group_display,
        metric: cell.metric_label,
        window: cell.window_label,
        status: cell.status,
        value: cellDisplay(cell),
        nullRows: `参与 ${cell.null_trace.included_blank_rows} / 排除 ${cell.null_trace.excluded_blank_rows}`,
      })
    }
  }
  return lines
}

function cellDisplay(cell: TrialCell): string {
  return cell.value === null ? '—' : cell.value
}

async function loadChartEvidence() {
  try {
    const payload = await fetchChartEvidence(chartId.value)
    chartEvidence.value = payload.items
  } catch (error) {
    chartEvidence.value = []
    errorMessage.value = error instanceof Error ? error.message : '图表证据读取失败'
  }
}

async function bindSelectedChart() {
  if (!activeId.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload = await bindChart(chartId.value, activeId.value, bindVersion.value || undefined)
    noticeMessage.value = payload.message
    await loadChartEvidence()
    await selectEntry(activeId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '绑定失败'
  }
}

async function upgradeSelectedChart(evidence: ChartEvidence) {
  const next = evidence.newer_versions[evidence.newer_versions.length - 1]?.replace('v', '')
  if (!next) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload = await upgradeChart(evidence.chart_id, evidence.plan_id, Number(next))
    noticeMessage.value = payload.message
    await loadChartEvidence()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升级失败'
  }
}

async function unbindSelectedChart(evidence: ChartEvidence) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload = await unbindChart(evidence.binding_id)
    noticeMessage.value = payload.message
    await loadChartEvidence()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解除绑定失败'
  }
}

onMounted(reloadAll)
</script>
