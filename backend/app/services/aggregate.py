"""聚合计算业务规则：草稿维护、试算、发布封存与版本留档。

关键约束：

* 草稿（definition + samples）与发布版（versions）是两份独立数据。图表消费只
  读取 versions，因此草稿怎么改都不会渗入跨模块的可视化图表。
* 发布时把当时的字段身份、字段名快照、空值策略、精度、窗口条件、样本、试算
  证据、窗口冲突与舍入口径一起封存；发布版不可再改。
* 同一份口径 + 同一份样本重复确认发布时，直接返回已有发布版，不新开一轮生效。
* 规则冲突一律以发布版为准：绑定关系记录 version，图表读取该版本的封存证据；
  后续版本只会标记“有更新”，不会自动替换消费方证据。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.fixtures import CASE_LIBRARY, DATASET_CATALOG, PLAN_DEFINITIONS, PLAN_SAMPLES
from app.services.aggregate_engine import (
    METRIC_LABELS,
    METRIC_ORDER,
    NULL_POLICY_LABELS,
    WINDOW_MODE_LABELS,
    compute,
    digest,
    normalize_definition,
    normalize_samples,
)
from app.store import store

MODULE = "aggregate"
REQUIRED_FIELDS = ["方案编号", "聚合函数", "目标字段"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {
    "提交校验": "待校验",
    "启用方案": "已启用",
    "发布方案": "已启用",
    "停用方案": "已停用",
}
NEGATIVE_ACTIONS = ["停用方案"]
PUBLISH_ACTIONS = ("启用方案", "发布方案")

_CASE_BY_ID = {case["case_id"]: case for case in CASE_LIBRARY}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AggregateService:
    def __init__(self) -> None:
        self._ready = False

    @property
    def _bindings(self) -> list[dict[str, Any]]:
        """绑定关系放在共享仓库里，图表模块与聚合模块看到同一份证据。"""
        return store.bindings

    # ------------------------------------------------------------ 初始化与草稿

    def _ensure_ready(self) -> None:
        # 幂等：重复调用、多个路由共享同一仓库时不会重置已保存的草稿与发布版。
        for row in store.rows(MODULE):
            if "definition" in row:
                continue
            code = str(row.get("方案编号") or "")
            definition, errors = normalize_definition(PLAN_DEFINITIONS.get(code))
            if errors:
                continue
            samples, sample_errors = normalize_samples(PLAN_SAMPLES.get(code, []), definition)
            if sample_errors:
                continue
            row["definition"] = definition
            row["samples"] = samples
            row["draft_revision"] = 0
            row["versions"] = []
            row["current_version"] = 0
            self._sync_columns(row)
        self._ready = True

    def _sync_columns(self, row: dict[str, Any]) -> None:
        """把结构化的口径摘要同步到列表明细字段，避免列表与详情两套说法。"""
        definition = row.get("definition") or {}
        metrics = definition.get("metrics") or {}
        enabled = [name for name in METRIC_ORDER if (metrics.get(name) or {}).get("enabled")]
        row["聚合函数"] = "、".join(METRIC_LABELS[name] for name in enabled) or row.get("聚合函数")
        group_fields = definition.get("group_fields") or []
        row["分组维度"] = "、".join(field["field_name"] for field in group_fields) or row.get("分组维度")
        time_field = definition.get("time_field")
        row["时间字段"] = time_field["field_name"] if time_field else "未绑定"
        windows = []
        for name in enabled:
            window = metrics[name]["window"]
            windows.append(f"{METRIC_LABELS[name]}：{WINDOW_MODE_LABELS.get(window['mode'], window['mode'])}")
        row["时间窗口"] = "；".join(windows) if windows else "不设窗口"
        precisions = [f"{METRIC_LABELS[name]} {metrics[name]['precision']} 位" for name in enabled]
        row["输出精度"] = "、".join(precisions)
        policies = [f"{METRIC_LABELS[name]} {NULL_POLICY_LABELS[metrics[name]['null_policy']]}" for name in enabled]
        row["空值策略"] = "、".join(policies)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        latest = (row.get("versions") or [])[-1] if row.get("versions") else None
        payload = {
            key: row.get(key)
            for key in (
                "id", "方案编号", "聚合函数", "目标字段", "分组维度", "时间窗口", "筛选条件",
                "输出精度", "缓存时间", "status", "pending", "abnormal", "时间字段", "空值策略",
            )
        }
        payload["dataset_id"] = (row.get("definition") or {}).get("dataset_id")
        payload["dataset_name"] = (row.get("definition") or {}).get("dataset_name")
        payload["draft_revision"] = row.get("draft_revision", 0)
        payload["current_version"] = row.get("current_version", 0)
        payload["published_version"] = latest["version"] if latest else None
        payload["published_at"] = latest["published_at"] if latest else None
        payload["version_count"] = len(row.get("versions") or [])
        return payload

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_ready()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._summary(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        payload = self._summary(row)
        payload["definition"] = copy.deepcopy(row.get("definition"))
        payload["samples"] = copy.deepcopy(row.get("samples") or [])
        payload["versions"] = [
            {
                "version": version["version"],
                "label": version["label"],
                "published_at": version["published_at"],
                "seal": version["seal"],
                "draft_revision": version["draft_revision"],
                "sample_digest": version["sample_digest"],
                "definition_digest": version["definition_digest"],
                "superseded": version["version"] < row.get("current_version", 0),
                "status": "生效中" if version["version"] == row.get("current_version", 0) else "已被新版取代",
                "conflict_count": len(version["conflicts"]),
                "null_policies": copy.deepcopy(version["null_policies"]),
                "window_conditions": copy.deepcopy(version["window_conditions"]),
            }
            for version in (row.get("versions") or [])
        ]
        payload["current_version"] = row.get("current_version", 0)
        return payload

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        self._ensure_ready()
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        definition_raw = values.get("definition")
        definition = None
        if definition_raw:
            definition, errors = normalize_definition(definition_raw)
            if errors:
                return None, errors
        else:
            dataset_id = str(values.get("dataset_id") or "")
            if dataset_id in DATASET_CATALOG:
                definition, errors = normalize_definition({
                    "dataset_id": dataset_id,
                    "group_fields": [],
                    "metrics": {},
                })
                if errors:
                    return None, errors
        samples: list[dict[str, Any]] = []
        if definition is not None:
            samples_raw = values.get("samples")
            samples, errors = normalize_samples(samples_raw or [], definition, require_rows=False)
            if errors:
                return None, errors
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["definition"] = definition
        entry["samples"] = samples
        entry["draft_revision"] = 0
        entry["versions"] = []
        entry["current_version"] = 0
        if definition is not None:
            self._sync_columns(entry)
        rows.append(entry)
        return entry, []

    def update_draft(
        self,
        entry_id: int,
        definition_raw: dict[str, Any] | None,
        samples_raw: list[dict[str, Any]] | None,
        *,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        """保存草稿并立即试算；返回 (条目, 错误, 试算)。草稿只影响自己的库表。"""
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, [f"聚合方案 {entry_id} 不存在或已归档"], None
        definition, errors = normalize_definition(definition_raw)
        if errors:
            return None, errors, None
        samples, sample_errors = normalize_samples(samples_raw, definition)
        if sample_errors:
            return None, sample_errors, None
        row["definition"] = definition
        row["samples"] = samples
        row["draft_revision"] = int(row.get("draft_revision", 0)) + 1
        if remark:
            row["草稿备注"] = remark
        self._sync_columns(row)
        return row, [], compute(definition, samples)

    def trial(
        self,
        entry_id: int,
        definition_raw: dict[str, Any] | None = None,
        samples_raw: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """临时试算：优先用传入口径，其次用当前草稿；不落库、不产生版本。"""
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, [f"聚合方案 {entry_id} 不存在或已归档"]
        source_definition = definition_raw if definition_raw is not None else row.get("definition")
        definition, errors = normalize_definition(source_definition)
        if errors:
            return None, errors
        source_samples = samples_raw if samples_raw is not None else row.get("samples")
        samples, sample_errors = normalize_samples(source_samples, definition)
        if sample_errors:
            return None, sample_errors
        return compute(definition, samples), []

    # ------------------------------------------------------------ 算例

    def case_samples(self, entry_id: int, case_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        """把角色化算例映射到当前方案的字段身份，返回可直接载入编辑器的样本。"""
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, [f"聚合方案 {entry_id} 不存在或已归档"]
        case = _CASE_BY_ID.get(case_id)
        if case is None:
            return None, [f"算例「{case_id}」不存在"]
        definition = row.get("definition")
        if definition is None:
            return None, ["当前方案尚未绑定数据集字段"]
        group_field = definition["group_fields"][0]["field_id"]
        sum_metric = definition["metrics"]["sum"]
        count_metric = definition["metrics"]["count"]
        value_field = (
            sum_metric["field"]["field_id"] if sum_metric["enabled"]
            else definition["metrics"]["avg"]["field"]["field_id"]
        )
        identity_field = count_metric["field"]["field_id"] if count_metric["enabled"] else value_field
        time_field = definition["time_field"]["field_id"] if definition["time_field"] else None
        use_value_as_identity = identity_field == value_field
        samples: list[dict[str, Any]] = []
        for item in case["rows"]:
            values: dict[str, Any] = {group_field: item["group"]}
            if time_field:
                values[time_field] = item["time"]
            values[value_field] = item["value"]
            # 计数指标绑定的字段复用同一空/非空形态，让“全空组”在计数下同样可读。
            if not use_value_as_identity:
                values[identity_field] = None if item["value"] is None else item["row_id"]
            samples.append({
                "row_id": item["row_id"],
                "note": item.get("note") or case["label"],
                "values": values,
            })
        trial = compute(definition, samples)
        return {
            "case_id": case_id,
            "label": case["label"],
            "description": case["description"],
            "samples": samples,
            "trial": trial,
        }, []

    def list_cases(self, entry_id: int) -> tuple[list[dict[str, Any]] | None, list[str]]:
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, [f"聚合方案 {entry_id} 不存在或已归档"]
        cases: list[dict[str, Any]] = []
        for item in CASE_LIBRARY:
            payload, errors = self.case_samples(entry_id, item["case_id"])
            if payload is None:
                return None, errors
            cases.append(payload)
        return cases, []

    # ------------------------------------------------------------ 发布与版本

    def publish(self, entry_id: int) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        """封存当前草稿；同口径同一样本重复确认时沿用已有版本。"""
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"聚合方案 {entry_id} 不存在或已归档", None
        definition = row.get("definition")
        if definition is None:
            return None, "当前方案尚未绑定数据集字段，无法发布", None
        samples = row.get("samples") or []
        normalized, errors = normalize_definition(definition)
        if errors:
            return None, "口径校验未通过：" + "；".join(errors), None
        cleaned, sample_errors = normalize_samples(samples, normalized)
        if sample_errors:
            return None, "样本校验未通过：" + "；".join(sample_errors), None
        trial = compute(normalized, cleaned)
        definition_digest = digest(normalized)
        sample_digest = digest(cleaned)
        seal = digest({"definition": normalized, "samples": cleaned})
        for version in row.get("versions") or []:
            if version["seal"] == seal:
                return row, (
                    f"重复确认：口径与样本与已发布的 {version['label']} 完全一致，"
                    "沿用该发布版，不再开启新一轮生效"
                ), self.get_version(entry_id, version["version"])
        windows = {
            name: {
                "mode": normalized["metrics"][name]["window"]["mode"],
                "mode_label": WINDOW_MODE_LABELS[normalized["metrics"][name]["window"]["mode"]],
                "conditions": copy.deepcopy(normalized["metrics"][name]["window"]["windows"]),
            }
            for name in METRIC_ORDER
            if normalized["metrics"][name]["enabled"]
        }
        next_version = max((int(item["version"]) for item in row.get("versions") or []), default=0) + 1
        version_payload = {
            "version": next_version,
            "label": f"v{next_version}",
            "published_at": _now(),
            "draft_revision": int(row.get("draft_revision", 0)),
            "seal": seal,
            "definition_digest": definition_digest,
            "sample_digest": sample_digest,
            "definition": copy.deepcopy(normalized),
            "samples": copy.deepcopy(cleaned),
            "window_conditions": windows,
            "null_policies": {
                name: {
                    "policy": normalized["metrics"][name]["null_policy"],
                    "label": NULL_POLICY_LABELS[normalized["metrics"][name]["null_policy"]],
                }
                for name in METRIC_ORDER
                if normalized["metrics"][name]["enabled"]
            },
            "rounding": copy.deepcopy(trial["checks"]["rounding"]),
            "conflicts": copy.deepcopy(trial["checks"]["window_conflicts"]),
            "boundaries": copy.deepcopy(trial["checks"]["window_boundaries"]),
            "trial": copy.deepcopy(trial),
        }
        row.setdefault("versions", []).append(version_payload)
        row["current_version"] = next_version
        row["status"] = "已启用"
        row["pending"] = False
        row["abnormal"] = False
        self._sync_columns(row)
        return row, (
            f"已发布 {version_payload['label']}：封存 {len(normalized['metrics'])} 个指标口径、"
            f"{len(windows)} 组窗口条件与 {len(cleaned)} 行样本试算证据"
        ), self.get_version(entry_id, next_version)

    def list_versions(self, entry_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"聚合方案 {entry_id} 不存在或已归档"
        versions = row.get("versions") or []
        return [
            {
                "version": item["version"],
                "label": item["label"],
                "published_at": item["published_at"],
                "seal": item["seal"],
                "definition_digest": item["definition_digest"],
                "sample_digest": item["sample_digest"],
                "draft_revision": item["draft_revision"],
                "status": "生效中" if item["version"] == row.get("current_version") else "已被新版取代",
                "conflict_count": len(item["conflicts"]),
                "null_policies": copy.deepcopy(item["null_policies"]),
                "window_conditions": copy.deepcopy(item["window_conditions"]),
            }
            for item in versions
        ], None

    def get_version(self, entry_id: int, version_number: int) -> dict[str, Any] | None:
        self._ensure_ready()
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        for item in row.get("versions") or []:
            if int(item["version"]) == version_number:
                payload = copy.deepcopy(item)
                payload["plan_id"] = entry_id
                payload["plan_code"] = row.get("方案编号")
                payload["current_version"] = row.get("current_version", 0)
                payload["superseded"] = item["version"] < row.get("current_version", 0)
                payload["draft_revision"] = row.get("draft_revision", 0)
                payload["draft_changed_since_publish"] = int(row.get("draft_revision", 0)) > int(item["draft_revision"])
                payload["conflict_precedence"] = (
                    "规则冲突以发布版为准；草稿修改不会进入本版本证据"
                    if item["conflicts"] else "本版本没有窗口重叠冲突"
                )
                return payload
        return None

    def published_catalog(self) -> list[dict[str, Any]]:
        """跨模块图表只读目录：只暴露发布版，不暴露草稿。"""
        self._ensure_ready()
        catalog: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            versions = row.get("versions") or []
            if not versions:
                continue
            catalog.append({
                "plan_id": row["id"],
                "plan_code": row.get("方案编号"),
                "dataset_id": (row.get("definition") or {}).get("dataset_id"),
                "dataset_name": (row.get("definition") or {}).get("dataset_name"),
                "current_version": row.get("current_version", 0),
                "versions": [
                    {
                        "version": item["version"],
                        "label": item["label"],
                        "published_at": item["published_at"],
                        "seal": item["seal"],
                        "definition_digest": item["definition_digest"],
                        "null_policies": copy.deepcopy(item["null_policies"]),
                        "window_conditions": copy.deepcopy(item["window_conditions"]),
                        "trial_digest": item["trial"]["digest"],
                        "group_count": len(item["trial"]["groups"]),
                        "conflict_count": len(item["conflicts"]),
                    }
                    for item in versions
                ],
            })
        return catalog

    # ------------------------------------------------------------ 图表绑定

    def bind_chart(
        self,
        chart_id: str,
        plan_id: int,
        version_number: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        self._ensure_ready()
        row = store.find(MODULE, plan_id)
        if row is None:
            return None, f"聚合方案 {plan_id} 不存在或已归档"
        versions = row.get("versions") or []
        if not versions:
            return None, "该方案还没有发布版，图表不能引用草稿口径"
        target = int(version_number) if version_number is not None else row.get("current_version", 0)
        sealed = next((item for item in versions if int(item["version"]) == target), None)
        if sealed is None:
            return None, f"方案 {row.get('方案编号')} 没有发布版 v{target}"
        for binding in self._bindings:
            if (
                binding["chart_id"] == chart_id
                and binding["plan_id"] == plan_id
                and binding["version"] == target
                and binding["state"] == "active"
            ):
                return binding, f"图表 {chart_id} 已绑定 {sealed['label']}，不重复登记"
        tail = [item for item in self._bindings if item["chart_id"] == chart_id and item["plan_id"] == plan_id]
        if tail:
            return self.upgrade_binding(chart_id, plan_id, tail[-1]["binding_id"], version_number=target)
        binding = self._new_binding(chart_id, row, sealed, state="active", supersedes=None)
        return binding, f"图表 {chart_id} 已绑定 {row.get('方案编号')} {sealed['label']}"

    def _new_binding(
        self,
        chart_id: str,
        row: dict[str, Any],
        sealed: dict[str, Any],
        *,
        state: str,
        supersedes: int | None,
    ) -> dict[str, Any]:
        binding = {
            "binding_id": max((int(item["binding_id"]) for item in self._bindings), default=0) + 1,
            "chart_id": chart_id,
            "plan_id": int(row["id"]),
            "plan_code": row.get("方案编号"),
            "version": int(sealed["version"]),
            "version_label": sealed["label"],
            "bound_at": _now(),
            "seal": sealed["seal"],
            "state": state,
            "supersedes": supersedes,
        }
        self._bindings.append(binding)
        return binding

    def upgrade_binding(
        self,
        chart_id: str,
        plan_id: int,
        binding_id: int | None = None,
        *,
        version_number: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """切换到新版：旧绑定转为历史证据保留，不覆盖、不丢失上一版试算。"""
        self._ensure_ready()
        row = store.find(MODULE, plan_id)
        if row is None:
            return None, f"聚合方案 {plan_id} 不存在或已归档"
        versions = row.get("versions") or []
        target = int(version_number) if version_number is not None else int(row.get("current_version", 0))
        sealed = next((item for item in versions if int(item["version"]) == target), None)
        if sealed is None:
            return None, f"方案 {row.get('方案编号')} 没有发布版 v{target}"
        active = [
            item for item in self._bindings
            if item["chart_id"] == chart_id and item["plan_id"] == plan_id and item["state"] == "active"
        ]
        already = next((item for item in active if item["version"] == target), None)
        if already is not None:
            return already, f"图表 {chart_id} 已在确认 {sealed['label']}，同一版不重复开启生效"
        if not active:
            binding = self._new_binding(chart_id, row, sealed, state="active", supersedes=None)
            return binding, f"图表 {chart_id} 已绑定 {row.get('方案编号')} {sealed['label']}"
        previous = active[-1]
        previous["state"] = "historical"
        previous["superseded_at"] = _now()
        binding = self._new_binding(
            chart_id, row, sealed, state="active", supersedes=int(previous["binding_id"])
        )
        return binding, (
            f"图表 {chart_id} 已切换到 {sealed['label']}；"
            f"{previous['version_label']} 的试算证据作为历史版本保留可追溯"
        )

    def list_bindings(self, chart_id: str | None = None) -> list[dict[str, Any]]:
        """图表侧只拿发布版证据；新版发布只标记升级可用，不替换旧证据。"""
        self._ensure_ready()
        payloads: list[dict[str, Any]] = []
        for binding in self._bindings:
            if chart_id and binding["chart_id"] != chart_id:
                continue
            row = store.find(MODULE, int(binding["plan_id"]))
            if row is None:
                continue
            sealed = next(
                (item for item in row.get("versions") or [] if int(item["version"]) == int(binding["version"])),
                None,
            )
            if sealed is None:
                continue
            newer = [
                item["label"] for item in row.get("versions") or []
                if int(item["version"]) > int(binding["version"])
            ]
            payloads.append({
                **copy.deepcopy(binding),
                "plan_code": row.get("方案编号"),
                "dataset_name": (sealed["definition"] or {}).get("dataset_name"),
                "null_policies": copy.deepcopy(sealed["null_policies"]),
                "window_conditions": copy.deepcopy(sealed["window_conditions"]),
                "rounding": copy.deepcopy(sealed["rounding"]),
                "conflicts": copy.deepcopy(sealed["conflicts"]),
                "trial_digest": sealed["trial"]["digest"],
                "trial_groups": copy.deepcopy(sealed["trial"]["groups"]),
                "unassigned": copy.deepcopy(sealed["trial"]["unassigned"]),
                "published_at": sealed["published_at"],
                "newer_versions": newer,
                "upgrade_available": bool(newer),
                "draft_changed_since_publish": int(row.get("draft_revision", 0)) > int(sealed["draft_revision"]),
                "precedence": "图表保留绑定版本的封存证据；规则冲突以该发布版为准",
            })
        return payloads

    def unbind_chart(self, binding_id: int) -> tuple[dict[str, Any] | None, str]:
        for index, binding in enumerate(self._bindings):
            if int(binding["binding_id"]) == binding_id:
                removed = self._bindings.pop(index)
                return removed, f"已解除图表 {removed['chart_id']} 的聚合口径绑定"
        return None, f"绑定 {binding_id} 不存在"

    # ------------------------------------------------------------ 动作

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        self._ensure_ready()
        if action not in ACTION_RULES:
            row = store.find(MODULE, entry_id)
            if row is None:
                return None, f"聚合方案 {entry_id} 不存在或已归档"
            return None, f"动作「{action}」不属于聚合计算可执行范围"
        if action in PUBLISH_ACTIONS:
            row, message, _ = self.publish(entry_id)
            return row, message
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"聚合方案 {entry_id} 不存在或已归档"
        target = ACTION_RULES[action]
        if action == "提交校验":
            definition, errors = normalize_definition(row.get("definition"))
            if errors:
                return None, "口径校验未通过：" + "；".join(errors)
            samples, sample_errors = normalize_samples(row.get("samples") or [], definition)
            if sample_errors:
                return None, "样本校验未通过：" + "；".join(sample_errors)
            row["last_trial_digest"] = compute(definition, samples)["digest"]
        row["status"] = target
        row["pending"] = target != STATUS_ORDER[-1]
        row["abnormal"] = action in NEGATIVE_ACTIONS
        return row, f"聚合方案已{action}"


# 模块级单例：路由与图表侧共享同一份发布版与绑定关系。
service = AggregateService()
