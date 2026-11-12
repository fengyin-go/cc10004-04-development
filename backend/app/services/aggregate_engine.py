"""聚合试算引擎：把方案口径翻译成逐组、逐窗口、逐行的贡献分解。

这里是唯一计算口径的实现处，纯函数、不读写全局状态。明确约定：

* 字段只按 field_id 绑定；显示名在规整时刷新为快照，展示仍然以身份为准。
* 空值策略按指标配置：参与 = 求和/均值的分子按 0 处理、均值分母仍包含该行，
  计数计 1 条；排除 = 该行不计入该指标的分子与分母。
* 舍入位置在汇总之后、只舍入一次（ROUND_HALF_UP）。逐行舍入再加总的数字
  只作对照，不参与结论。求和用精度足够的 Decimal 精确累加，输入顺序不会
  改变舍入结论。
* 窗口统一左闭右开；相邻窗口共用边界时，边界采样归起点更大的窗口；
  重叠窗口按声明顺序归第一个命中的窗口。一条采样只会归入一个窗口，
  窗口外与时间缺失的采样进入未归集清单。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from app.fixtures import DATASET_CATALOG, DATASET_FIELD_INDEX

METRIC_ORDER = ("sum", "count", "avg")
METRIC_LABELS = {"sum": "求和", "count": "计数", "avg": "均值"}
NULL_POLICY_LABELS = {"include": "参与", "exclude": "排除"}
WINDOW_MODE_LABELS = {"monthly": "按月", "custom": "自定义区间", "none": "不设窗口"}
ROUNDING_LABEL = "汇总后单次舍入（ROUND_HALF_UP）"


# ------------------------------------------------------------------ 通用工具

def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def field_ref(field_id: str) -> dict[str, Any]:
    return {"field_id": field_id}


def resolve_field(dataset_id: str, field_id: str) -> dict[str, Any] | None:
    return DATASET_FIELD_INDEX.get(dataset_id, {}).get(field_id)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    """返回 (数值, 错误)；空值返回 (None, None)，无效文本返回 (None, 原因)。"""
    if _blank(value):
        return None, None
    if isinstance(value, bool):
        return None, "布尔值不能作为度量值"
    if isinstance(value, float):
        text = repr(value)
    elif isinstance(value, Decimal):
        text = format(value, "f")
    else:
        text = str(value)
    try:
        parsed = Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None, "无法解析为数值"
    if not parsed.is_finite():
        return None, "数值必须是有限数"
    return parsed, None


def parse_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    if _blank(value):
        return None, None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None, "无法解析为时间"
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed, None


def _quantize(value: Decimal, precision: int) -> Decimal:
    exponent = Decimal(1).scaleb(-precision)
    digits = len(value.as_tuple().digits) + abs(int(value.as_tuple().exponent)) + precision + 20
    with localcontext() as ctx:
        ctx.prec = max(40, digits)
        return value.quantize(exponent, rounding=ROUND_HALF_UP)


def _divide(total: Decimal, denominator: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = max(60, len(total.as_tuple().digits) + 40)
        return total / Decimal(denominator)


def _exact_sum(values: list[Decimal]) -> Decimal:
    """精确累加；上下文精度随输入位数放大，因此与输入顺序无关。"""
    if not values:
        return Decimal(0)
    capacity = max(
        len(item.as_tuple().digits) + abs(int(item.as_tuple().exponent)) for item in values
    )
    with localcontext() as ctx:
        ctx.prec = max(60, capacity + 30 + len(str(len(values))))
        total = Decimal(0)
        for item in values:
            total += item
        return +total


def _display(value: Decimal, precision: int) -> str:
    return format(_quantize(value, precision), "f")


# ------------------------------------------------------------------ 规整与校验

def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _month_windows(anchor: str, periods: int) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        start = datetime.fromisoformat(str(anchor).strip())
    except (ValueError, TypeError):
        return [], ["窗口锚点需要形如 2026-01-01 的日期"]
    year, month = start.year, start.month
    windows: list[dict[str, Any]] = []
    for index in range(periods):
        next_year, next_month = _next_month(year, month)
        windows.append({
            "key": f"{year:04d}-{month:02d}",
            "label": f"{year:04d}-{month:02d}",
            "start": datetime(year, month, 1).isoformat(),
            "end": datetime(next_year, next_month, 1).isoformat(),
            "index": index,
        })
        year, month = next_year, next_month
    return windows, []


def _custom_windows(ranges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    windows: list[dict[str, Any]] = []
    for position, item in enumerate(ranges):
        label = str(item.get("label") or f"区间{position + 1}")
        start_dt, start_error = parse_timestamp(item.get("start"))
        end_dt, end_error = parse_timestamp(item.get("end"))
        if start_error or end_error:
            errors.append(f"窗口「{label}」起止时间无法解析")
            continue
        if start_dt is None or end_dt is None:
            errors.append(f"窗口「{label}」缺少起止时间")
            continue
        if start_dt >= end_dt:
            errors.append(f"窗口「{label}」起点必须早于终点")
            continue
        windows.append({
            "key": label,
            "label": label,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "index": position,
        })
    return windows, errors


def normalize_window(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    raw = raw or {}
    mode = str(raw.get("mode") or "monthly")
    config: dict[str, Any] = {
        "mode": mode,
        "anchor": str(raw.get("anchor") or "2026-01-01"),
        "periods": int(raw.get("periods") or 1),
        "ranges": list(raw.get("ranges") or []),
    }
    errors: list[str] = []
    if mode not in WINDOW_MODE_LABELS:
        return config, [f"未知窗口模式「{mode}」"]
    if mode == "monthly":
        if not 1 <= config["periods"] <= 60:
            errors.append("按月窗口的连续月数需要在 1 到 60 之间")
        windows, window_errors = _month_windows(config["anchor"], max(1, min(config["periods"], 60)))
        errors.extend(window_errors)
    elif mode == "custom":
        windows, window_errors = _custom_windows(config["ranges"])
        errors.extend(window_errors)
        if not windows:
            errors.append("自定义窗口至少需要一个有效区间")
    else:
        windows = [{"key": "all", "label": "全部时间", "start": None, "end": None, "index": 0}]
    config["windows"] = windows
    return config, errors


def normalize_definition(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """把提交上来的定义规整为只含 field_id 的结构，并收集所有口径错误。"""
    raw = raw or {}
    dataset_id = str(raw.get("dataset_id") or "")
    if dataset_id not in DATASET_CATALOG:
        return None, ["请选择数据集管理里存在的数据集"]
    errors: list[str] = []

    group_fields: list[dict[str, Any]] = []
    for item in raw.get("group_fields") or []:
        field_id = str((item or {}).get("field_id") or "")
        field = resolve_field(dataset_id, field_id)
        if field is None:
            errors.append(f"分组字段「{field_id or '未选择'}」不属于数据集 {dataset_id}")
            continue
        group_fields.append({"field_id": field_id, "field_name": field["name"]})
    if not group_fields:
        errors.append("至少绑定一个分组字段，才能形成分组口径")

    time_field_id = str((raw.get("time_field") or {}).get("field_id") or "")
    time_field = resolve_field(dataset_id, time_field_id) if time_field_id else None
    if time_field_id and time_field is None:
        errors.append(f"时间字段「{time_field_id}」不属于数据集 {dataset_id}")

    metrics_raw = raw.get("metrics") or {}
    metrics: dict[str, Any] = {}
    enabled_count = 0
    needs_time = False
    for name in METRIC_ORDER:
        item = metrics_raw.get(name) or {}
        enabled = bool(item.get("enabled", True))
        field_id = str((item.get("field") or {}).get("field_id") or "")
        field = resolve_field(dataset_id, field_id)
        if enabled and field is None:
            errors.append(f"{METRIC_LABELS[name]}指标未绑定数据集字段")
        policy = str(item.get("null_policy") or "exclude")
        if policy not in NULL_POLICY_LABELS:
            errors.append(f"{METRIC_LABELS[name]}的空值策略「{policy}」不受支持")
            policy = "exclude"
        try:
            precision = int(item.get("precision", 2))
        except (TypeError, ValueError):
            errors.append(f"{METRIC_LABELS[name]}的输出精度必须是整数")
            precision = 2
        if not 0 <= precision <= 6:
            errors.append(f"{METRIC_LABELS[name]}的输出精度需要在 0 到 6 之间")
            precision = max(0, min(precision, 6))
        window, window_errors = normalize_window(item.get("window"))
        errors.extend(f"{METRIC_LABELS[name]}：{message}" for message in window_errors)
        if enabled and window["mode"] != "none":
            needs_time = True
        metrics[name] = {
            "enabled": enabled,
            "field": {"field_id": field_id, "field_name": field["name"]} if field else {"field_id": field_id},
            "null_policy": policy,
            "precision": precision,
            "window": window,
        }
        if enabled:
            enabled_count += 1
    if not enabled_count:
        errors.append("至少启用一个聚合指标（求和、计数、均值）")
    if needs_time and time_field is None:
        errors.append("配置了时间窗口但未绑定时间字段")

    if errors:
        return None, errors
    return {
        "dataset_id": dataset_id,
        "dataset_name": DATASET_CATALOG[dataset_id]["dataset_name"],
        "group_fields": group_fields,
        "time_field": {"field_id": time_field["id"], "field_name": time_field["name"]} if time_field else None,
        "metrics": metrics,
    }, []


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def normalize_samples(
    raw: list[dict[str, Any]] | None,
    definition: dict[str, Any],
    *,
    require_rows: bool = True,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    dataset_id = definition["dataset_id"]
    known = DATASET_FIELD_INDEX.get(dataset_id, {})
    rows = raw or []
    errors: list[str] = []
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    if require_rows and not rows:
        errors.append("至少保留一行可编辑样本，才能形成可比较的试算")
    for position, item in enumerate(rows):
        item = item or {}
        row_id = str(item.get("row_id") or "").strip()
        if not row_id:
            errors.append(f"第 {position + 1} 行缺少样本行号")
            continue
        if row_id in seen:
            errors.append(f"样本行号「{row_id}」重复")
            continue
        seen.add(row_id)
        values = item.get("values")
        if not isinstance(values, dict):
            errors.append(f"样本行「{row_id}」的字段值必须是对象")
            continue
        unknown = [key for key in values if key not in known]
        if unknown:
            errors.append(f"样本行「{row_id}」含不属于数据集 {dataset_id} 的字段：{'、'.join(unknown)}")
            continue
        bad = [key for key, value in values.items() if not _scalar(value)]
        if bad:
            errors.append(f"样本行「{row_id}」的字段值必须是标量：{'、'.join(bad)}")
            continue
        cleaned.append({
            "row_id": row_id,
            "note": str(item.get("note") or ""),
            "values": dict(values),
        })
    if errors:
        return None, errors
    return cleaned, []


# ------------------------------------------------------------------ 窗口与分组

def _window_for(stamp: datetime, windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for window in windows:
        if window["start"] is None or window["end"] is None:
            return window
        if datetime.fromisoformat(window["start"]) <= stamp < datetime.fromisoformat(window["end"]):
            return window
    return None


def check_windows(metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (相邻边界说明, 重叠冲突说明)。窗口归属规则在这里被明确写死。"""
    boundaries: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for name in METRIC_ORDER:
        metric = metrics[name]
        if not metric["enabled"]:
            continue
        windows = [window for window in metric["window"]["windows"] if window["start"] and window["end"]]
        for left_index, left in enumerate(windows):
            for right in windows[left_index + 1:]:
                left_start, left_end = datetime.fromisoformat(left["start"]), datetime.fromisoformat(left["end"])
                right_start, right_end = datetime.fromisoformat(right["start"]), datetime.fromisoformat(right["end"])
                if left_end == right_start:
                    boundaries.append({
                        "metric": name,
                        "metric_label": METRIC_LABELS[name],
                        "left": left["label"],
                        "right": right["label"],
                        "boundary": left["end"],
                        "owner": right["label"],
                        "rule": f"左闭右开：边界 {left['end']} 的采样只归「{right['label']}」",
                    })
                elif left_start < right_end and right_start < left_end:
                    conflicts.append({
                        "metric": name,
                        "metric_label": METRIC_LABELS[name],
                        "left": left["label"],
                        "right": right["label"],
                        "owner": left["label"],
                        "rule": f"窗口重叠：按声明顺序优先「{left['label']}」，一条采样不会重复归集",
                    })
    return boundaries, conflicts


def _group_key(definition: dict[str, Any], values: dict[str, Any]) -> tuple[str, str]:
    keys: list[str] = []
    labels: list[str] = []
    for field in definition["group_fields"]:
        raw = values.get(field["field_id"])
        text = "" if raw is None else str(raw).strip()
        keys.append(text)
        labels.append(text if text else "(空)")
    return "\x1f".join(keys), " / ".join(labels)


def _null_reason(name: str, policy: str) -> str:
    if name == "count":
        return "空值按「参与」策略计为 1 条" if policy == "include" else "空值按「排除」策略不计入条数"
    if policy == "include":
        return "空值按「参与」策略计为 0，仍进入均值分母" if name == "avg" else "空值按「参与」策略计为 0 参与求和"
    return "空值按「排除」策略不计入分子与分母"


def _cell(
    name: str,
    metric: dict[str, Any],
    window: dict[str, Any],
    assigned: list[dict[str, Any]],
) -> dict[str, Any]:
    field_id = metric["field"]["field_id"]
    policy = metric["null_policy"]
    precision = metric["precision"]
    numeric: list[Decimal] = []
    contributions: list[dict[str, Any]] = []
    blank_rows = 0
    invalid_rows = 0
    reasons: set[str] = set()

    for row in assigned:
        raw = row["values"].get(field_id)
        if name == "count":
            if _blank(raw):
                blank_rows += 1
                participates = policy == "include"
                if participates:
                    numeric.append(Decimal(1))
                reason = _null_reason(name, policy)
                reasons.add(reason)
                contributions.append({
                    "row_id": row["row_id"],
                    "raw_value": None,
                    "effective_value": "1" if participates else "0",
                    "participates": participates,
                    "role": "null_included" if participates else "null_excluded",
                    "reason": reason,
                })
            else:
                numeric.append(Decimal(1))
                contributions.append({
                    "row_id": row["row_id"],
                    "raw_value": raw,
                    "effective_value": "1",
                    "participates": True,
                    "role": "counted",
                    "reason": "非空值按 1 条计入",
                })
            continue
        if _blank(raw):
            blank_rows += 1
            participates = policy == "include"
            if participates:
                numeric.append(Decimal(0))
            reason = _null_reason(name, policy)
            reasons.add(reason)
            contributions.append({
                "row_id": row["row_id"],
                "raw_value": None,
                "effective_value": "0" if participates else None,
                "participates": participates,
                "role": "null_included" if participates else "null_excluded",
                "reason": reason,
            })
            continue
        value, error = parse_decimal(raw)
        if error or value is None:
            invalid_rows += 1
            reason = error or "值无法参与数值计算"
            reasons.add(reason)
            contributions.append({
                "row_id": row["row_id"],
                "raw_value": raw,
                "effective_value": None,
                "participates": False,
                "role": "invalid",
                "reason": reason,
            })
            continue
        numeric.append(value)
        contributions.append({
            "row_id": row["row_id"],
            "raw_value": raw,
            "effective_value": format(value, "f"),
            "participates": True,
            "role": "measured",
            "reason": "数值参与计算",
        })

    contributions.sort(key=lambda item: item["row_id"])

    if not assigned:
        status = "无记录"
        status_reason = "该组在本窗口没有采样"
    elif blank_rows == len(assigned):
        status = "全空组"
        status_reason = (
            f"{len(assigned)} 行在本指标绑定字段上均为空；"
            + ("按「参与」策略仍有贡献" if policy == "include" else "按「排除」策略没有数值贡献")
        )
    elif blank_rows:
        status = "含空值"
        status_reason = f"{blank_rows} 行为空值，已按「{NULL_POLICY_LABELS[policy]}」策略处理"
    elif invalid_rows:
        status = "含无效值"
        status_reason = f"{invalid_rows} 行无法解析为数值，未计入"
    else:
        status = "正常"
        status_reason = "全部采样都参与了计算"

    cell: dict[str, Any] = {
        "metric": name,
        "metric_label": METRIC_LABELS[name],
        "field_id": field_id,
        "window_key": window["key"],
        "window_label": window["label"],
        "window_start": window["start"],
        "window_end": window["end"],
        "status": status,
        "status_reason": status_reason,
        "precision": precision,
        "included_rows": len(assigned),
        "blank_rows": blank_rows,
        "invalid_rows": invalid_rows,
        "value": None,
        "raw_value": None,
        "contributions": contributions,
        "null_trace": {
            "policy": policy,
            "policy_label": NULL_POLICY_LABELS[policy],
            "blank_rows": blank_rows,
            "included_blank_rows": sum(1 for item in contributions if item["role"] == "null_included"),
            "excluded_blank_rows": sum(1 for item in contributions if item["role"] == "null_excluded"),
            "invalid_rows": invalid_rows,
            "reasons": sorted(reasons) if reasons else ["本组本窗口没有空值记录"],
        },
        "rounding": {
            "strategy": ROUNDING_LABEL,
            "aggregate_then_round": None,
            "row_round_then_sum": None,
            "same": True,
            "note": "",
        },
    }

    if name == "count":
        count = Decimal(len(numeric))
        cell["value"] = _display(count, precision)
        cell["raw_value"] = format(count, "f")
        cell["rounding"].update({
            "aggregate_then_round": cell["value"],
            "row_round_then_sum": cell["value"],
            "same": True,
            "note": "计数为整数，舍入不改变结论",
        })
        return cell

    if not numeric:
        cell["rounding"]["note"] = "没有有效数值，无法形成求和/均值"
        return cell

    total = _exact_sum(numeric)
    if name == "sum":
        cell["raw_value"] = format(total, "f")
        cell["value"] = _display(total, precision)
        aggregate_once = _quantize(total, precision)
        row_rounded_total = _exact_sum([_quantize(item, precision) for item in numeric])
        rowwise = _quantize(row_rounded_total, precision)
        cell["rounding"].update({
            "aggregate_then_round": format(aggregate_once, "f"),
            "row_round_then_sum": format(rowwise, "f"),
            "same": aggregate_once == rowwise,
            "note": "先精确累加再单次舍入；逐行舍入合计仅作对照",
        })
        if aggregate_once != Decimal(0):
            for item in contributions:
                if item["role"] == "measured":
                    value, _ = parse_decimal(item["raw_value"])
                    if value is not None:
                        with localcontext() as ctx:
                            ctx.prec = 60
                            share = _quantize(value / total * Decimal(100), 1)
                        item["share_percent"] = format(share, "f")
        return cell

    denominator = len(numeric)
    average = _divide(total, denominator)
    cell["raw_value"] = f"{format(total, 'f')} / {denominator}"
    cell["value"] = _display(average, precision)
    aggregate_once = _quantize(average, precision)
    rowwise_numerator = _exact_sum([_quantize(item, precision) for item in numeric])
    rowwise = _quantize(_divide(rowwise_numerator, denominator), precision)
    cell["rounding"].update({
        "aggregate_then_round": format(aggregate_once, "f"),
        "row_round_then_sum": format(rowwise, "f"),
        "same": aggregate_once == rowwise,
        "note": f"均值分母 {denominator}（参与行数），逐行舍入均值仅作对照",
    })
    cell["denominator"] = denominator
    return cell


def _group_values(definition: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in definition["group_fields"]:
        raw = values.get(field["field_id"])
        payload[field["field_id"]] = {
            "field_name": field["field_name"],
            "value": raw,
            "display": "(空)" if _blank(raw) else str(raw),
        }
    return payload


def compute_core(
    definition: dict[str, Any],
    samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """逐组逐指标逐窗口执行；返回 (分组结果, 未归集清单)。"""
    grouped: dict[str, dict[str, Any]] = {}
    for row in samples:
        key, display = _group_key(definition, row["values"])
        group = grouped.setdefault(key, {"key": key, "display": display, "rows": []})
        group["rows"].append(row)

    unassigned: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = grouped[key]
        cells: list[dict[str, Any]] = []
        for name in METRIC_ORDER:
            metric = definition["metrics"][name]
            if not metric["enabled"]:
                continue
            windows = metric["window"]["windows"]
            buckets: dict[str, list[dict[str, Any]]] = {window["key"]: [] for window in windows}
            for row in group["rows"]:
                if metric["window"]["mode"] == "none":
                    buckets[windows[0]["key"]].append(row)
                    continue
                stamp_raw = row["values"].get(definition["time_field"]["field_id"]) if definition["time_field"] else None
                stamp, error = parse_timestamp(stamp_raw)
                if error:
                    unassigned.append({
                        "row_id": row["row_id"],
                        "group": group["display"],
                        "metric": name,
                        "metric_label": METRIC_LABELS[name],
                        "reason": f"时间无法解析：{error}",
                    })
                    continue
                if stamp is None:
                    unassigned.append({
                        "row_id": row["row_id"],
                        "group": group["display"],
                        "metric": name,
                        "metric_label": METRIC_LABELS[name],
                        "reason": "时间缺失，未归入任何窗口",
                    })
                    continue
                owner = _window_for(stamp, windows)
                if owner is None:
                    unassigned.append({
                        "row_id": row["row_id"],
                        "group": group["display"],
                        "metric": name,
                        "metric_label": METRIC_LABELS[name],
                        "reason": f"时间 {stamp.isoformat()} 不在任何窗口内",
                    })
                    continue
                buckets[owner["key"]].append(row)
            for window in windows:
                cells.append(_cell(name, metric, window, buckets[window["key"]]))
        groups.append({
            "group_key": key,
            "group_display": group["display"],
            "group_values": _group_values(definition, group["rows"][0]["values"]),
            "cells": cells,
        })
    unassigned.sort(key=lambda item: (item["metric"], item["row_id"], item["reason"]))
    return groups, unassigned


def projection(
    definition: dict[str, Any],
    groups: list[dict[str, Any]],
    unassigned: list[dict[str, Any]],
) -> dict[str, Any]:
    """只保留与输入顺序无关的结果字段，用于顺序稳定性摘要。"""
    return {
        "groups": [
            {
                "group": group["group_display"],
                "cells": [
                    {
                        "metric": cell["metric"],
                        "window": cell["window_key"],
                        "value": cell["value"],
                        "raw_value": cell["raw_value"],
                        "status": cell["status"],
                        "included_rows": cell["included_rows"],
                        "blank_rows": cell["blank_rows"],
                        "invalid_rows": cell["invalid_rows"],
                        "null_included": cell["null_trace"]["included_blank_rows"],
                        "null_excluded": cell["null_trace"]["excluded_blank_rows"],
                        "rounding": [
                            cell["rounding"]["aggregate_then_round"],
                            cell["rounding"]["row_round_then_sum"],
                        ],
                    }
                    for cell in group["cells"]
                ],
            }
            for group in groups
        ],
        "windows": {
            name: [window["key"] for window in definition["metrics"][name]["window"]["windows"]]
            for name in METRIC_ORDER
            if definition["metrics"][name]["enabled"]
        },
        "unassigned": [
            {"row_id": item["row_id"], "metric": item["metric"], "reason": item["reason"]}
            for item in unassigned
        ],
    }


def compute(definition: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """执行完整试算，并用反序输入复核金额舍入结论。"""
    groups, unassigned = compute_core(definition, samples)
    forward = digest(projection(definition, groups, unassigned))
    reverse_groups, reverse_unassigned = compute_core(definition, list(reversed(samples)))
    reverse = digest(projection(definition, reverse_groups, reverse_unassigned))
    boundaries, conflicts = check_windows(definition["metrics"])
    return {
        "dataset_id": definition["dataset_id"],
        "dataset_name": definition["dataset_name"],
        "definition": definition,
        "groups": groups,
        "windows_by_metric": {
            name: metric["window"]["windows"]
            for name, metric in definition["metrics"].items()
            if metric["enabled"]
        },
        "unassigned": unassigned,
        "checks": {
            "window_boundaries": boundaries,
            "window_conflicts": conflicts,
            "rounding": {
                "strategy": ROUNDING_LABEL,
                "position": "汇总之后、输出之前，只舍入一次",
                "row_level_rounding": "逐行舍入合计只作对照，不参与结论",
                "order_independent": True,
            },
            "order": {
                "stable": forward == reverse,
                "digest": forward,
                "reversed_digest": reverse,
                "note": "正序与反序输入得到同一结论摘要",
            },
        },
        "digest": forward,
        "sample_count": len(samples),
    }
