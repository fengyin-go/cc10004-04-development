"""聚合试算器使用的结构化示例资料。

数据集管理里的字段在这里补上稳定身份（field_id）。聚合方案只绑定 field_id，
显示名变化不会影响已经绑定的方案；展示时再通过字段身份解析出当前名称。

这里同时给出三份可比较算例（全空组、正负抵消、跨月边界）以及默认聚合方案，
让服务启动后就能直接试算、封存发布版、被可视化图表消费。
"""
from __future__ import annotations

from typing import Any

DATASET_CATALOG: dict[str, dict[str, Any]] = {
    "DATA-0001": {
        "dataset_name": "销售订单明细",
        "source_table": "dwd_sales_order",
        "fields": [
            {"id": "DATA-0001.order_no", "name": "订单号", "type": "string", "role": "id"},
            {"id": "DATA-0001.amount", "name": "订单金额", "type": "decimal", "role": "measure"},
            {"id": "DATA-0001.region", "name": "区域", "type": "string", "role": "group"},
            {"id": "DATA-0001.channel", "name": "渠道", "type": "string", "role": "group"},
            {"id": "DATA-0001.paid_at", "name": "支付时间", "type": "datetime", "role": "time"},
        ],
    },
    "DATA-0002": {
        "dataset_name": "门店客流明细",
        "source_table": "dwd_store_traffic",
        "fields": [
            {"id": "DATA-0002.store", "name": "门店", "type": "string", "role": "group"},
            {"id": "DATA-0002.city", "name": "城市", "type": "string", "role": "group"},
            {"id": "DATA-0002.traffic", "name": "客流量", "type": "integer", "role": "measure"},
            {"id": "DATA-0002.visit_at", "name": "到访时间", "type": "datetime", "role": "time"},
        ],
    },
    "DATA-0003": {
        "dataset_name": "通用指标样例",
        "source_table": "dwd_metric_sample",
        "fields": [
            {"id": "DATA-0003.group", "name": "分组", "type": "string", "role": "group"},
            {"id": "DATA-0003.value", "name": "指标值", "type": "decimal", "role": "measure"},
            {"id": "DATA-0003.ts", "name": "发生时间", "type": "datetime", "role": "time"},
        ],
    },
}

DATASET_FIELD_INDEX: dict[str, dict[str, dict[str, Any]]] = {
    dataset_id: {field["id"]: field for field in meta["fields"]}
    for dataset_id, meta in DATASET_CATALOG.items()
}


def _metric(field_id: str, null_policy: str, precision: int, *,
            mode: str = "monthly", anchor: str = "2026-01-01", periods: int = 2,
            ranges: list[dict[str, str]] | None = None, enabled: bool = True) -> dict[str, Any]:
    """构造一个指标口径。字段只保存身份引用，名称在提交时会刷新为快照。"""
    return {
        "enabled": enabled,
        "field": {"field_id": field_id},
        "null_policy": null_policy,
        "precision": precision,
        "window": {
            "mode": mode,
            "anchor": anchor,
            "periods": periods,
            "ranges": ranges or [],
        },
    }


def _definition(dataset_id: str, group_ids: list[str], time_id: str | None,
                metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "group_fields": [{"field_id": field_id} for field_id in group_ids],
        "time_field": {"field_id": time_id} if time_id else None,
        "metrics": metrics,
    }


PLAN_DEFINITIONS: dict[str, dict[str, Any]] = {
    "AGGR-0001": _definition(
        "DATA-0001",
        ["DATA-0001.region"],
        "DATA-0001.paid_at",
        {
            # 求和与均值排除空值；计数把空值也当成一条记录，三种口径各留一种决策。
            "sum": _metric("DATA-0001.amount", "exclude", 2),
            "count": _metric("DATA-0001.order_no", "include", 0),
            "avg": _metric("DATA-0001.amount", "exclude", 2),
        },
    ),
    "AGGR-0002": _definition(
        "DATA-0002",
        ["DATA-0002.city"],
        "DATA-0002.visit_at",
        {
            "sum": _metric("DATA-0002.traffic", "include", 0),
            "count": _metric("DATA-0002.store", "exclude", 0),
            "avg": _metric("DATA-0002.traffic", "exclude", 1),
        },
    ),
    "AGGR-0003": _definition(
        "DATA-0001",
        ["DATA-0001.channel"],
        "DATA-0001.paid_at",
        {
            "sum": _metric("DATA-0001.amount", "exclude", 2),
            "count": _metric("DATA-0001.order_no", "exclude", 0),
            "avg": _metric("DATA-0001.amount", "exclude", 2),
        },
    ),
}

PLAN_SAMPLES: dict[str, list[dict[str, Any]]] = {
    "AGGR-0001": [
        {"row_id": "S-001", "note": "月末最后一秒", "values": {
            "DATA-0001.order_no": "SO-1001", "DATA-0001.amount": "120.50",
            "DATA-0001.region": "华东", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-01-31T23:59:59"}},
        {"row_id": "S-002", "note": "下月第一秒，跨月边界", "values": {
            "DATA-0001.order_no": "SO-1002", "DATA-0001.amount": "-120.50",
            "DATA-0001.region": "华东", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-02-01T00:00:00"}},
        {"row_id": "S-003", "note": "半分位舍入样例", "values": {
            "DATA-0001.order_no": "SO-1003", "DATA-0001.amount": "0.005",
            "DATA-0001.region": "华北", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": "2026-01-15T10:00:00"}},
        {"row_id": "S-004", "note": "半分位舍入样例", "values": {
            "DATA-0001.order_no": "SO-1004", "DATA-0001.amount": "0.005",
            "DATA-0001.region": "华北", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-01-20T10:00:00"}},
        {"row_id": "S-005", "note": "全空组，金额与订单号都为空", "values": {
            "DATA-0001.order_no": None, "DATA-0001.amount": None,
            "DATA-0001.region": "西北", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-01-10T09:00:00"}},
        {"row_id": "S-006", "note": "全空组", "values": {
            "DATA-0001.order_no": None, "DATA-0001.amount": None,
            "DATA-0001.region": "西北", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": "2026-01-18T09:00:00"}},
        {"row_id": "S-007", "note": "窗口内正常值", "values": {
            "DATA-0001.order_no": "SO-1007", "DATA-0001.amount": "100.00",
            "DATA-0001.region": "华南", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": "2026-01-05T08:00:00"}},
        {"row_id": "S-008", "note": "窗口外", "values": {
            "DATA-0001.order_no": "SO-1008", "DATA-0001.amount": "50.00",
            "DATA-0001.region": "华南", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-03-01T08:00:00"}},
        {"row_id": "S-009", "note": "时间缺失", "values": {
            "DATA-0001.order_no": "SO-1009", "DATA-0001.amount": "80.00",
            "DATA-0001.region": "华南", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": ""}},
    ],
    "AGGR-0002": [
        {"row_id": "T-001", "values": {
            "DATA-0002.store": "一店", "DATA-0002.city": "上海",
            "DATA-0002.traffic": 1200, "DATA-0002.visit_at": "2026-01-08T10:00:00"}},
        {"row_id": "T-002", "values": {
            "DATA-0002.store": "", "DATA-0002.city": "上海",
            "DATA-0002.traffic": None, "DATA-0002.visit_at": "2026-01-09T10:00:00"}},
        {"row_id": "T-003", "values": {
            "DATA-0002.store": "二店", "DATA-0002.city": "杭州",
            "DATA-0002.traffic": 800, "DATA-0002.visit_at": "2026-02-02T10:00:00"}},
    ],
    "AGGR-0003": [
        {"row_id": "C-001", "values": {
            "DATA-0001.order_no": "SO-2001", "DATA-0001.amount": "88.60",
            "DATA-0001.region": "华东", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-01-12T12:00:00"}},
        {"row_id": "C-002", "values": {
            "DATA-0001.order_no": "SO-2002", "DATA-0001.amount": "45.00",
            "DATA-0001.region": "华北", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": "2026-01-13T12:00:00"}},
        {"row_id": "C-003", "values": {
            "DATA-0001.order_no": "SO-2003", "DATA-0001.amount": None,
            "DATA-0001.region": "华东", "DATA-0001.channel": "线下",
            "DATA-0001.paid_at": "2026-01-14T12:00:00"}},
        {"row_id": "C-004", "values": {
            "DATA-0001.order_no": "SO-2004", "DATA-0001.amount": "77.40",
            "DATA-0001.region": "华南", "DATA-0001.channel": "线上",
            "DATA-0001.paid_at": "2026-02-01T00:00:00"}},
    ],
}

# 算例按语义角色组织，不绑定某个数据集，执行时再映射到当前方案的字段身份。
CASE_LIBRARY: list[dict[str, Any]] = [
    {
        "case_id": "all-null",
        "label": "全空组",
        "description": "同一组所有度量值都为空：参与策略下计为 0/计入 1 条，排除策略下求和与均值没有有效贡献。",
        "rows": [
            {"row_id": "AN-1", "group": "西北", "value": None,
             "time": "2026-01-10T09:00:00", "note": "空值记录 A"},
            {"row_id": "AN-2", "group": "西北", "value": None,
             "time": "2026-01-18T09:00:00", "note": "空值记录 B"},
            {"row_id": "AN-3", "group": "西南", "value": "12.30",
             "time": "2026-01-22T09:00:00", "note": "非空对照记录"},
        ],
    },
    {
        "case_id": "offset",
        "label": "正负抵消",
        "description": "同一窗口内 +100.00 与 -100.00 抵消为 0，再叠加两个 0.005 观察汇总后舍入与逐行舍入的差异。",
        "rows": [
            {"row_id": "OF-1", "group": "华东", "value": "100.00",
             "time": "2026-01-05T09:00:00", "note": "正向金额"},
            {"row_id": "OF-2", "group": "华东", "value": "-100.00",
             "time": "2026-01-06T09:00:00", "note": "反向金额"},
            {"row_id": "OF-3", "group": "华东", "value": "0.005",
             "time": "2026-01-07T09:00:00", "note": "半分位 A"},
            {"row_id": "OF-4", "group": "华东", "value": "0.005",
             "time": "2026-01-08T09:00:00", "note": "半分位 B"},
        ],
    },
    {
        "case_id": "month-edge",
        "label": "跨月边界",
        "description": "窗口采用左闭右开区间：1 月最后一秒归 1 月，2 月第一秒归 2 月，窗口外的 3 月记录单独归集。",
        "rows": [
            {"row_id": "ME-1", "group": "华东", "value": "10.00",
             "time": "2026-01-01T00:00:00", "note": "窗口起点"},
            {"row_id": "ME-2", "group": "华东", "value": "20.00",
             "time": "2026-01-31T23:59:59", "note": "1 月最后一秒"},
            {"row_id": "ME-3", "group": "华东", "value": "30.00",
             "time": "2026-02-01T00:00:00", "note": "2 月第一秒"},
            {"row_id": "ME-4", "group": "华东", "value": "40.00",
             "time": "2026-02-28T23:59:59", "note": "2 月最后一秒"},
            {"row_id": "ME-5", "group": "华东", "value": "50.00",
             "time": "2026-03-01T00:00:00", "note": "窗口外"},
        ],
    },
]
