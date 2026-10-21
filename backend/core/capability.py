"""backend/core/capability.py —— 能力注册表，探针台 /console 的唯一数据来源。

出处：docs/05 §3.2「能力注册表（后端单一来源）」

核心思想一句话：
    每加一个功能，就在这里注册一行；探针台页面自动把它显示出来，
    **不需要改前端**。前端只负责照着清单渲染。

ID 命名规则（docs/05 §5 强制）：
    CAP-<模块>-<序号>，例如 CAP-CORE-01。
    同一个 ID 同时是：探针台条目 / 后端测试用例名 / 验收清单条目 —— 四处永远对得上。
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable

from pydantic import BaseModel, Field


class Capability(BaseModel):
    """一条能力的**描述信息**（不是实现本身）。"""

    id: str = Field(..., description="能力 ID，全局唯一，形如 CAP-CORE-01")
    module: str = Field(..., description="所属模块，如 CORE / M1 / M2")
    name: str
    summary: str = Field(..., description="这句话会原样显示在页面上")
    target: str = Field(..., description="实现入口，形如 包.模块.函数名")
    params: list[dict] = Field(default_factory=list, description="参数表单描述，前端据此自动生成输入框")
    observation: str = Field(default="", description="执行成功后，你能在哪里看到效果")


class RunResult(BaseModel):
    """一次执行的完整回执 —— 探针台右侧面板显示的就是它。"""

    capability_id: str
    ok: bool
    elapsed_ms: float
    result: dict


_REGISTRY: list[Capability] = [
    Capability(
        id="CAP-CORE-01",
        module="CORE",
        name="数据契约自检",
        summary="跑一遍 F-01 定下的规矩，看错误数据能不能被当场拦住",
        target="backend.core.selfcheck.run",
        params=[],
        observation="tests/test_models.py 的同一套校验；以后每加一条数据结构，就往 selfcheck 里补一条用例",
    ),
    Capability(
        id="CAP-CORE-02",
        module="CORE",
        name="severity 校验器",
        summary="输一个等级字符串，看它合不合法、是什么意思",
        target="backend.core.severity_check.run",
        params=[
            {
                "name": "severity",
                "label": "等级字符串",
                "type": "text",
                "required": True,
                "default": "blocking",
                "placeholder": "试试 bloking（少个 c）",
            },
        ],
        observation="枚举单一来源的守门实验；全系统的等级都由 backend/core/enums.py 这一份清单管着",
    ),
]


def all_capabilities() -> list[Capability]:
    """全部能力（探针台左栏的清单）。"""
    return list(_REGISTRY)


def get_capability(cap_id: str) -> Capability | None:
    for cap in _REGISTRY:
        if cap.id == cap_id:
            return cap
    return None


def run_capability(cap_id: str, params: dict | None = None) -> RunResult:
    """执行一条能力，并把结果包成统一回执。

    这是「注册表驱动」的关键：页面只传一个 ID 上来，
    具体调用哪个函数，由这里按 target 字符串动态去找。
    """
    cap = get_capability(cap_id)
    if cap is None:
        return RunResult(capability_id=cap_id, ok=False, elapsed_ms=0.0,
                         result={"error": f"没有这条能力：{cap_id}"})

    func = _load(cap.target)
    if func is None:
        return RunResult(capability_id=cap_id, ok=False, elapsed_ms=0.0,
                         result={"error": f"找不到实现：{cap.target}"})

    started = time.perf_counter()
    try:
        result = func(**(params or {}))
        ok = True
    except Exception as exc:  # noqa: BLE001 —— 探针台要的是「看见错误」，不是崩溃
        result = {"error": f"{type(exc).__name__}: {exc}"}
        ok = False
    elapsed = (time.perf_counter() - started) * 1000

    return RunResult(capability_id=cap_id, ok=ok, elapsed_ms=round(elapsed, 1),
                     result=result if isinstance(result, dict) else {"value": result})


def _load(dotted: str) -> Callable[..., Any] | None:
    """把 'backend.core.selfcheck.run' 这样的字符串，变成真的函数。"""
    module_name, _, func_name = dotted.rpartition(".")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, func_name)
    except (ImportError, AttributeError):
        return None
