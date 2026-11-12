"""聚合计算接口：草稿口径、试算、算例、发布封存、版本与图表绑定。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.aggregate import service

router = APIRouter(prefix="/api/aggregate", tags=["聚合计算"])

LIST_FIELDS = ["方案编号", "聚合函数", "目标字段", "分组维度", "时间窗口", "筛选条件", "输出精度", "缓存时间"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


class DraftPayload(BaseModel):
    """保存草稿：口径与可编辑样本一起提交，保存后立即试算。"""

    definition: dict[str, Any]
    samples: list[dict[str, Any]] = Field(default_factory=list)
    remark: str | None = None


class TrialPayload(BaseModel):
    """临时试算：不传 definition 时使用当前草稿，不落库。"""

    definition: dict[str, Any] | None = None
    samples: list[dict[str, Any]] | None = None


class BindPayload(BaseModel):
    """图表绑定发布版：version 缺省时取当前生效版本。"""

    chart_id: str
    plan_id: int
    version: int | None = None


class UnbindPayload(BaseModel):
    binding_id: int


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号与状态过滤聚合计算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/published", response_model=dict)
def published_catalog() -> dict[str, Any]:
    """跨模块图表可读取的已发布口径目录；草稿不会出现在这里。"""
    return {"items": service.published_catalog()}


@router.get("/bindings", response_model=dict)
def list_bindings(chart_id: str | None = Query(default=None, description="只看某张图表")) -> dict[str, Any]:
    """图表绑定的发布版证据：保留上一版试算，标记是否有新版可升级。"""
    return {"items": service.list_bindings(chart_id=chart_id)}


@router.post("/bindings", response_model=ActionResult)
def bind_chart(payload: BindPayload) -> ActionResult:
    """把图表绑定到某个已发布版本；不允许绑定草稿。"""
    binding, message = service.bind_chart(payload.chart_id, payload.plan_id, payload.version)
    if binding is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=binding)


@router.post("/bindings/upgrade", response_model=ActionResult)
def upgrade_binding(payload: BindPayload) -> ActionResult:
    """切换到新版：旧版证据转为历史保留；同一版重复确认不新开一轮生效。"""
    binding, message = service.upgrade_binding(payload.chart_id, payload.plan_id, version_number=payload.version)
    if binding is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=binding)


@router.post("/bindings/unbind", response_model=ActionResult)
def unbind_chart(payload: UnbindPayload) -> ActionResult:
    removed, message = service.unbind_chart(payload.binding_id)
    if removed is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=removed)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出聚合计算清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "aggregate", "total": total, "items": items}


@router.get("/{entry_id}/cases/{case_id}", response_model=dict)
def get_case(entry_id: int, case_id: str) -> dict[str, Any]:
    """读取一个可比较算例（全空组、正负抵消、跨月边界），按当前方案字段身份映射。"""
    payload, errors = service.case_samples(entry_id, case_id)
    if payload is None:
        raise HTTPException(status_code=400, detail="；".join(errors))
    return payload


@router.get("/{entry_id}/cases", response_model=dict)
def list_cases(entry_id: int) -> dict[str, Any]:
    """列出全部算例及各自试算结果，方便并排比较。"""
    cases, errors = service.list_cases(entry_id)
    if cases is None:
        raise HTTPException(status_code=404, detail="；".join(errors))
    return {"items": cases}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条聚合方案明细（含草稿口径、样本与版本摘要）；不存在时给出可读错误。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"聚合方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条聚合方案，缺字段时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if entry is None:
        missing = [
            field for field in REQUIRED_FIELDS
            if not str(payload.values.get(field) or "").strip()
        ]
        if missing:
            return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
        return ActionResult(ok=False, message="口径校验未通过：" + "；".join(problems))
    return ActionResult(ok=True, message="聚合方案已登记", entry=entry)


@router.put("/{entry_id}/draft", response_model=ActionResult)
def save_draft(entry_id: int, payload: DraftPayload) -> ActionResult:
    """保存草稿并试算；草稿不会写入任何发布版或图表证据。"""
    entry, errors, trial = service.update_draft(
        entry_id, payload.definition, payload.samples, remark=payload.remark
    )
    if entry is None:
        return ActionResult(ok=False, message="草稿未保存：" + "；".join(errors))
    summary = service._summary(entry)
    summary["trial"] = trial
    return ActionResult(
        ok=True,
        message=f"草稿 v{entry['draft_revision']} 已保存并完成试算，样本次数 {trial['sample_count']}",
        entry=summary,
    )


@router.post("/{entry_id}/trial", response_model=dict)
def run_trial(entry_id: int, payload: TrialPayload | None = None) -> dict[str, Any]:
    """临时试算：不落库、不产生版本，可直接比较不同口径。"""
    payload = payload or TrialPayload()
    trial, errors = service.trial(entry_id, payload.definition, payload.samples)
    if trial is None:
        return {"ok": False, "message": "；".join(errors), "trial": None}
    return {"ok": True, "message": "试算完成", "trial": trial}


@router.get("/{entry_id}/versions", response_model=dict)
def list_versions(entry_id: int) -> dict[str, Any]:
    """列出版本摘要；冲突数与封存条件可见。"""
    versions, error = service.list_versions(entry_id)
    if versions is None:
        raise HTTPException(status_code=404, detail=error)
    return {"items": versions}


@router.get("/{entry_id}/versions/{version_number}", response_model=dict)
def get_version(entry_id: int, version_number: int) -> dict[str, Any]:
    """读取发布版封存证据，包括口径、窗口条件、样本与试算。"""
    version = service.get_version(entry_id, version_number)
    if version is None:
        raise HTTPException(status_code=404, detail=f"方案 {entry_id} 没有发布版 v{version_number}")
    return version


@router.post("/{entry_id}/publish", response_model=ActionResult)
def publish(entry_id: int) -> ActionResult:
    """封存当前口径与样本；同口径同样本重复确认时沿用已有版本。"""
    entry, message, version = service.publish(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=version)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条聚合方案执行提交校验、启用/发布、停用；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=service._summary(entry))


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出聚合计算清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "aggregate", "total": total, "items": items}
