"""聚合试算器的接口级自检：约束全部通过真实 HTTP 调用验证。

运行：backend/.venv/bin/python tests/aggregate_check.py（服务需已在 8000 端口运行）
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
FAILURES: list[str] = []


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:  # noqa: PERF203
        return error.code, json.loads(error.read().decode())


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def cells(trial: dict, group: str, metric: str, window: str) -> dict:
    for entry in trial["groups"]:
        if entry["group_display"] == group:
            for cell in entry["cells"]:
                if cell["metric"] == metric and cell["window_key"] == window:
                    return cell
    return {}


def build_definition(entry: dict, *, overlaps: bool = False) -> dict:
    definition = json.loads(json.dumps(entry["definition"]))
    if overlaps:
        definition["metrics"]["sum"]["window"] = {
            "mode": "custom",
            "anchor": "2026-01-01",
            "periods": 1,
            "ranges": [
                {"label": "A", "start": "2026-01-01T00:00:00", "end": "2026-02-15T00:00:00"},
                {"label": "B", "start": "2026-02-01T00:00:00", "end": "2026-03-01T00:00:00"},
            ],
        }
    return definition


def main() -> int:
    status, entry = call("GET", "/api/aggregate/1")
    check("读取方案明细", status == 200 and "definition" in entry)

    samples = entry["samples"]
    definition = build_definition(entry)

    # 1. 全空组、正负抵消、跨月边界算例
    status, case_list = call("GET", "/api/aggregate/1/cases")
    check("算例目录", status == 200 and len(case_list.get("items", [])) == 3)
    cases = {item["case_id"]: item for item in case_list.get("items", [])}
    null_case = cells(cases["all-null"]["trial"], "西北", "sum", "2026-01")
    check("全空组求和无有效贡献", null_case.get("status") == "全空组" and null_case.get("value") is None)
    check(
        "全空组计数逐行可追溯",
        cells(cases["all-null"]["trial"], "西北", "count", "2026-01").get("value") == "2",
    )
    offset = cells(cases["offset"]["trial"], "华东", "sum", "2026-01")
    check("正负抵消汇总后舍入 0.01", offset.get("value") == "0.01", offset.get("value"))
    check(
        "逐行舍入对照可见差异",
        offset.get("rounding", {}).get("same") is False
        and offset.get("rounding", {}).get("row_round_then_sum") == "0.02",
        json.dumps(offset.get("rounding")),
    )
    edge = cells(cases["month-edge"]["trial"], "华东", "sum", "2026-01")
    check("跨月边界 1 月最后一秒归 1 月", edge.get("value") == "30.00", edge.get("value"))
    check(
        "跨月边界 2 月第一秒归 2 月",
        cells(cases["month-edge"]["trial"], "华东", "sum", "2026-02").get("value") == "70.00",
    )
    check(
        "窗口外采样进入未归集",
        any(item["row_id"] == "ME-5" for item in cases["month-edge"]["trial"]["unassigned"]),
    )

    # 2. 空值溯源
    trace = null_case.get("null_trace", {})
    check(
        "空值为什么被排除可追溯",
        trace.get("policy") == "exclude" and trace.get("excluded_blank_rows") == 2
        and any("排除" in reason for reason in trace.get("reasons", [])),
    )

    # 3. 顺序稳定性
    status, forward = call("POST", "/api/aggregate/1/trial", {"definition": definition, "samples": samples})
    reversed_samples = list(reversed(samples))
    status2, backward = call("POST", "/api/aggregate/1/trial", {"definition": definition, "samples": reversed_samples})
    check("试算成功", status == 200 and forward.get("ok"))
    check(
        "输入顺序改变金额舍入结论不变",
        forward["trial"]["checks"]["order"]["stable"]
        and forward["trial"]["digest"] == backward["trial"]["digest"],
    )

    # 4. 窗口重叠：一条采样只归一组
    overlap_definition = build_definition(entry, overlaps=True)
    status, overlap = call("POST", "/api/aggregate/1/trial", {"definition": overlap_definition, "samples": samples})
    check("重叠窗口被标记为冲突", bool(overlap["trial"]["checks"]["window_conflicts"]))
    east = [g for g in overlap["trial"]["groups"] if g["group_display"] == "华东"][0]
    rows_per_window = [
        [item["row_id"] for item in cell["contributions"]]
        for cell in east["cells"]
        if cell["metric"] == "sum"
    ]
    all_rows = [row for group in rows_per_window for row in group]
    check("一条采样只归入一个窗口", len(all_rows) == len(set(all_rows)), json.dumps(rows_per_window))
    check("相邻窗口不重复归集边界采样", all_rows.count("S-002") == 1)

    # 5. 草稿隔离：发布后改草稿，图表证据不变
    status, _ = call("POST", "/api/aggregate/1/publish")
    status, published = call("GET", "/api/aggregate/1/versions")
    check("发布产生版本", bool(published.get("items")))
    version = published["items"][-1]
    status, chart_catalog = call("GET", "/api/chart/aggregate/catalog")
    check("跨模块目录只含发布版", bool(chart_catalog.get("items")))

    status, again = call("POST", "/api/aggregate/1/publish")
    check("重复确认同版不再开一轮生效", "重复确认" in again.get("message", ""))
    status, versions_after = call("GET", "/api/aggregate/1/versions")
    check("版本数未因重复确认增加", len(versions_after["items"]) == len(published["items"]))

    modified_samples = [
        row for row in samples if row["row_id"] not in {"S-099", "S-100"}
    ] + [{
        "row_id": "S-099",
        "note": "草稿后加行",
        "values": {**samples[0]["values"], "DATA-0001.amount": "9.99"},
    }]
    status, draft = call("PUT", "/api/aggregate/1/draft", {"definition": definition, "samples": modified_samples})
    check("草稿保存成功", draft.get("ok") is True)

    status, evidence = call("GET", "/api/chart/aggregate/evidence?chart_id=CHAR-0003")
    if not evidence.get("items"):
        status, binding = call("POST", "/api/chart/aggregate/bind", {"chart_id": "CHAR-0003", "plan_id": 1})
        status, evidence = call("GET", "/api/chart/aggregate/evidence?chart_id=CHAR-0003")
    active = [item for item in evidence["items"] if item["state"] == "active"][0]
    check(
        "图表证据不渗入草稿修改",
        active["draft_changed_since_publish"] is True
        and active["seal"] == version["seal"],
    )
    check("图表证据保留上一版样本摘要", len(active["trial_groups"]) >= 1)

    # 6. 切换到新版：旧证据保留
    status, first_bind = call("POST", "/api/chart/aggregate/bind", {"chart_id": "CHAR-0003", "plan_id": 1})
    status, new_version = call("POST", "/api/aggregate/1/publish")
    if new_version.get("ok"):
        status, upgraded = call("POST", "/api/chart/aggregate/upgrade", {"chart_id": "CHAR-0003", "plan_id": 1})
        check("切换新版成功", upgraded.get("ok") is True)
        status, evidence2 = call("GET", "/api/chart/aggregate/evidence?chart_id=CHAR-0003")
        states = [item["state"] for item in evidence2["items"]]
        check("旧版证据转为历史且仍保留", "historical" in states)
        status, repeat = call("POST", "/api/chart/aggregate/upgrade", {"chart_id": "CHAR-0003", "plan_id": 1})
        check("同版重复确认不再生效", "已在确认" in repeat.get("message", ""))
        status, evidence3 = call("GET", "/api/chart/aggregate/evidence?chart_id=CHAR-0003")
        active_count = len([item for item in evidence3["items"] if item["state"] == "active"])
        check("同一版只保留一个生效证据", active_count == 1, str(active_count))

    print()
    if FAILURES:
        print("失败项：" + "、".join(FAILURES))
        return 1
    print("全部约束通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
