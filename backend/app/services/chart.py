"""可视化图表业务规则：状态流转、字段校验与筛选口径都收在这里。

图表消费聚合口径时只读发布版证据：这里不复制草稿、也不在发布新版时静默替换
旧证据，升级必须显式确认；同一版本重复确认不会新开一轮生效。
"""
from __future__ import annotations

from typing import Any

from app.services.aggregate import service as AGGREGATE
from app.store import store

MODULE = "chart"
REQUIRED_FIELDS = ["图表编号", "图表名称", "图表类型"]
STATUS_ORDER = ["草稿", "待发布", "已发布", "已下线"]
ACTION_RULES = {"提交发布": "待发布", "发布图表": "已发布", "下线图表": "已下线"}
NEGATIVE_ACTIONS = ["下线图表"]


class ChartService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("图表编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"图表配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于可视化图表可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"图表配置已{action}"

    # ------------------------------------------------------------ 聚合口径消费

    def aggregate_evidence(self, chart_id: str) -> list[dict[str, Any]]:
        """图表侧只展示绑定版本的封存试算证据；有新版也只提示可升级。"""
        return AGGREGATE.list_bindings(chart_id=chart_id)

    def bind_aggregate(
        self, chart_id: str, plan_id: int, version: int | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        return AGGREGATE.bind_chart(chart_id, plan_id, version)

    def upgrade_aggregate(
        self, chart_id: str, plan_id: int, version: int | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        return AGGREGATE.upgrade_binding(chart_id, plan_id, version_number=version)

    def unbind_aggregate(self, binding_id: int) -> tuple[dict[str, Any] | None, str]:
        return AGGREGATE.unbind_chart(binding_id)
