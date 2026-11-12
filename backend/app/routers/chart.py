"""可视化图表接口：维护图表配置，覆盖提交发布、发布图表、下线图表等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.aggregate import service as aggregate_service
from app.services.chart import ChartService

router = APIRouter(prefix="/api/chart", tags=["可视化图表"])

service = ChartService()

LIST_FIELDS = ["图表编号", "图表名称", "图表类型", "数据来源", "X轴字段", "Y轴字段", "配色方案", "刷新间隔秒"]
STATUSES = ["草稿", "待发布", "已发布", "已下线"]


class AggregateBindingPayload(BaseModel):
    """图表引用聚合发布版：version 缺省取该方案当前生效版。"""

    chart_id: str
    plan_id: int
    version: int | None = None


class AggregateBindingRef(BaseModel):
    binding_id: int


@router.get("/aggregate/catalog", response_model=dict)
def aggregate_catalog() -> dict[str, Any]:
    """可选聚合口径：只返回发布版，草稿不可被图表引用。"""
    return {"items": aggregate_service.published_catalog()}


@router.get("/aggregate/evidence", response_model=dict)
def aggregate_evidence(
    chart_id: str = Query(description="图表编号，例如 CHAR-0003"),
) -> dict[str, Any]:
    """图表引用的聚合试算证据：绑定版本、空值与窗口条件、分组贡献与冲突数。"""
    items = service.aggregate_evidence(chart_id)
    return {"chart_id": chart_id, "items": items, "total": len(items)}


@router.post("/aggregate/bind", response_model=ActionResult)
def bind_aggregate(payload: AggregateBindingPayload) -> ActionResult:
    """把图表绑定到聚合发布版；重复绑定同一版不新开一轮生效。"""
    entry, message = service.bind_aggregate(payload.chart_id, payload.plan_id, payload.version)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/aggregate/upgrade", response_model=ActionResult)
def upgrade_aggregate(payload: AggregateBindingPayload) -> ActionResult:
    """显式确认升级到新版；上一版证据转为历史保留，可继续追溯。"""
    entry, message = service.upgrade_aggregate(payload.chart_id, payload.plan_id, payload.version)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/aggregate/unbind", response_model=ActionResult)
def unbind_aggregate(payload: AggregateBindingRef) -> ActionResult:
    entry, message = service.unbind_aggregate(payload.binding_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按图表编号检索"),
    status: str | None = Query(default=None, description="草稿、待发布、已发布、已下线"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按图表编号与状态过滤可视化图表列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条图表配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"图表配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条图表配置，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="图表配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条图表配置执行提交发布、发布图表、下线图表；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出可视化图表清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "chart", "total": total, "items": items}
