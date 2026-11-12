/** 聚合试算的类型与 HTTP 封装。
 *
 * 类型与后端 services/aggregate_engine.py 的输出保持一致；页面只关心业务对象，
 * 不直接拼 query string。
 */
import { request } from '@/api/client'

export type NullPolicy = 'include' | 'exclude'
export type MetricKey = 'sum' | 'count' | 'avg'
export type WindowMode = 'monthly' | 'custom' | 'none'

export interface FieldIdentity {
  field_id: string
  field_name?: string
}

export interface WindowRange {
  label: string
  start: string
  end: string
}

export interface WindowCondition {
  key: string
  label: string
  start: string | null
  end: string | null
  index: number
}

export interface WindowConfig {
  mode: WindowMode
  anchor: string
  periods: number
  ranges: WindowRange[]
  windows?: WindowCondition[]
}

export interface MetricConfig {
  enabled: boolean
  field: FieldIdentity
  null_policy: NullPolicy
  precision: number
  window: WindowConfig
}

export interface AggregateDefinition {
  dataset_id: string
  dataset_name?: string
  group_fields: FieldIdentity[]
  time_field: FieldIdentity | null
  metrics: Record<MetricKey, MetricConfig>
}

export interface SampleRow {
  row_id: string
  note: string
  values: Record<string, string | number | boolean | null>
}

export interface Contribution {
  row_id: string
  raw_value: unknown
  effective_value: string | null
  participates: boolean
  role: 'measured' | 'counted' | 'null_included' | 'null_excluded' | 'invalid'
  reason: string
  share_percent?: string
}

export interface NullTrace {
  policy: NullPolicy
  policy_label: string
  blank_rows: number
  included_blank_rows: number
  excluded_blank_rows: number
  invalid_rows: number
  reasons: string[]
}

export interface RoundingTrace {
  strategy: string
  aggregate_then_round: string | null
  row_round_then_sum: string | null
  same: boolean
  note: string
}

export type CellStatus = '正常' | '含空值' | '全空组' | '含无效值' | '无记录'

export interface TrialCell {
  metric: MetricKey
  metric_label: string
  field_id: string
  window_key: string
  window_label: string
  window_start: string | null
  window_end: string | null
  status: CellStatus
  status_reason: string
  precision: number
  included_rows: number
  blank_rows: number
  invalid_rows: number
  value: string | null
  raw_value: string | null
  denominator?: number
  contributions: Contribution[]
  null_trace: NullTrace
  rounding: RoundingTrace
}

export interface TrialGroup {
  group_key: string
  group_display: string
  group_values: Record<string, { field_name: string; value: unknown; display: string }>
  cells: TrialCell[]
}

export interface UnassignedRow {
  row_id: string
  group: string
  metric: MetricKey
  metric_label: string
  reason: string
}

export interface WindowBoundary {
  metric: MetricKey
  metric_label: string
  left: string
  right: string
  boundary: string
  owner: string
  rule: string
}

export interface WindowConflict {
  metric: MetricKey
  metric_label: string
  left: string
  right: string
  owner: string
  rule: string
}

export interface TrialResult {
  dataset_id: string
  dataset_name: string
  definition: AggregateDefinition
  groups: TrialGroup[]
  windows_by_metric: Record<string, WindowCondition[]>
  unassigned: UnassignedRow[]
  checks: {
    window_boundaries: WindowBoundary[]
    window_conflicts: WindowConflict[]
    rounding: {
      strategy: string
      position: string
      row_level_rounding: string
      order_independent: boolean
    }
    order: {
      stable: boolean
      digest: string
      reversed_digest: string
      note: string
    }
  }
  digest: string
  sample_count: number
}

export interface VersionSummary {
  version: number
  label: string
  published_at: string
  seal: string
  definition_digest: string
  sample_digest: string
  draft_revision: number
  status: string
  conflict_count: number
  null_policies: Record<string, { policy: NullPolicy; label: string }>
  window_conditions: Record<string, { mode: string; mode_label: string; conditions: WindowCondition[] }>
}

export interface SealedVersion extends VersionSummary {
  plan_id: number
  plan_code: string
  current_version: number
  superseded: boolean
  draft_changed_since_publish: boolean
  conflict_precedence: string
  definition: AggregateDefinition
  samples: SampleRow[]
  rounding: TrialResult['checks']['rounding']
  conflicts: WindowConflict[]
  boundaries: WindowBoundary[]
  trial: TrialResult
}

export interface AggregateEntry {
  id: number
  方案编号?: string
  status: string
  dataset_name?: string
  definition: AggregateDefinition | null
  samples: SampleRow[]
  versions: VersionSummary[]
  draft_revision: number
  current_version: number
}

export interface CaseTrial {
  case_id: string
  label: string
  description: string
  samples: SampleRow[]
  trial: TrialResult
}

export interface DatasetField {
  id: string
  name: string
  type: string
  role: string
}

export interface DatasetCatalog {
  dataset_id: string
  dataset_name: string
  source_table: string
  fields: DatasetField[]
}

export interface ChartEvidence {
  binding_id: number
  chart_id: string
  plan_id: number
  plan_code: string
  version: number
  version_label: string
  state: 'active' | 'historical'
  supersedes: number | null
  bound_at: string
  seal: string
  dataset_name: string
  null_policies: Record<string, { policy: NullPolicy; label: string }>
  window_conditions: Record<string, { mode: string; mode_label: string; conditions: WindowCondition[] }>
  rounding: RoundingTrace
  conflicts: WindowConflict[]
  trial_digest: string
  trial_groups: TrialGroup[]
  unassigned: UnassignedRow[]
  published_at: string
  newer_versions: string[]
  upgrade_available: boolean
  draft_changed_since_publish: boolean
  precedence: string
}

export interface PublishedPlan {
  plan_id: number
  plan_code: string
  dataset_id: string
  dataset_name: string
  current_version: number
  versions: {
    version: number
    label: string
    published_at: string
    seal: string
    definition_digest: string
    null_policies: Record<string, { policy: NullPolicy; label: string }>
    window_conditions: Record<string, { mode: string; mode_label: string; conditions: WindowCondition[] }>
    trial_digest: string
    group_count: number
    conflict_count: number
  }[]
}

// ---------------------------------------------------------------- HTTP 封装

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : `接口返回 ${response.status}，数据未更新`)
  }
  return payload as T
}

export function listEntries(): Promise<{ items: AggregateEntry[]; total: number }> {
  return read('/api/aggregate?size=100')
}

export function fetchEntry(entryId: number): Promise<AggregateEntry & { definition: AggregateDefinition }> {
  return read(`/api/aggregate/${entryId}`)
}

export function fetchFieldCatalog(): Promise<{ items: DatasetCatalog[] }> {
  return read('/api/datastore/catalog/fields')
}

export function saveDraft(
  entryId: number,
  definition: AggregateDefinition,
  samples: SampleRow[],
): Promise<{ ok: boolean; message: string; entry?: AggregateEntry & { trial: TrialResult } }> {
  return read(`/api/aggregate/${entryId}/draft`, {
    method: 'PUT',
    body: JSON.stringify({ definition, samples, remark: '试算器保存' }),
  })
}

export function runTrial(
  entryId: number,
  payload: { definition?: AggregateDefinition; samples?: SampleRow[] } = {},
): Promise<{ ok: boolean; message: string; trial: TrialResult | null }> {
  return read(`/api/aggregate/${entryId}/trial`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchCases(entryId: number): Promise<{ items: CaseTrial[] }> {
  return read(`/api/aggregate/${entryId}/cases`)
}

export function fetchVersions(entryId: number): Promise<{ items: VersionSummary[] }> {
  return read(`/api/aggregate/${entryId}/versions`)
}

export function fetchVersion(entryId: number, version: number): Promise<SealedVersion> {
  return read(`/api/aggregate/${entryId}/versions/${version}`)
}

export function publishDraft(
  entryId: number,
): Promise<{ ok: boolean; message: string; entry?: SealedVersion }> {
  return read(`/api/aggregate/${entryId}/publish`, { method: 'POST', body: JSON.stringify({}) })
}

export function fetchPublishedPlans(): Promise<{ items: PublishedPlan[] }> {
  return read('/api/aggregate/published')
}

export function fetchChartEvidence(chartId: string): Promise<{ items: ChartEvidence[] }> {
  return read(`/api/chart/aggregate/evidence?chart_id=${encodeURIComponent(chartId)}`)
}

export function bindChart(
  chartId: string,
  planId: number,
  version?: number,
): Promise<{ ok: boolean; message: string }> {
  return read('/api/chart/aggregate/bind', {
    method: 'POST',
    body: JSON.stringify({ chart_id: chartId, plan_id: planId, version: version ?? null }),
  })
}

export function upgradeChart(
  chartId: string,
  planId: number,
  version: number,
): Promise<{ ok: boolean; message: string }> {
  return read('/api/chart/aggregate/upgrade', {
    method: 'POST',
    body: JSON.stringify({ chart_id: chartId, plan_id: planId, version }),
  })
}

export function unbindChart(bindingId: number): Promise<{ ok: boolean; message: string }> {
  return read('/api/chart/aggregate/unbind', {
    method: 'POST',
    body: JSON.stringify({ binding_id: bindingId }),
  })
}
