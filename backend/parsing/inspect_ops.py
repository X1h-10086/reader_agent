"""探针台用的两个能力实现（CAP-M1-01 / CAP-M1-02）。

真正的逻辑在 ingest.py；这里只做两件事：
    ① 接住探针台传来的参数，交给 ingest 的三道关卡；
    ② 维护一张「见过的指纹表」，用来演示去重（CAP-M1-02）。

⚠️ 这张表目前只在内存里，服务一重启就清空。
   持久化到数据库是 M8 的事 —— 这里先证明「去重逻辑成立」。
"""

from __future__ import annotations

from backend.parsing.ingest import inspect

# file_hash -> 首次上传时的文件名
_SEEN: dict[str, str] = {}


def sniff(file_path: str, display_name: str | None = None) -> dict:
    """CAP-M1-01：只验身，不登记指纹表。"""
    r = inspect(file_path, display_name)
    return {
        "结论": "放行" if r.allowed else "拒收",
        **r.model_dump(),
        "已登记的指纹数": len(_SEEN),
    }


def dedup(file_path: str, display_name: str | None = None) -> dict:
    """CAP-M1-02：验身后查指纹表，命中就复用。"""
    r = inspect(file_path, display_name)

    if not r.allowed:
        return {"结论": "拒收，不登记指纹", **r.model_dump()}

    first = _SEEN.get(r.file_hash or "")
    if first is not None:
        return {
            "结论": "命中已有版本 → 直接复用，不再解析",
            "命中": True,
            "本次文件": r.file_name,
            "首次上传的文件": first,
            "指纹": r.file_hash,
            "省下的成本": "一次完整解析（MinerU 额度 + 几分钟等待）",
            "已登记的指纹数": len(_SEEN),
        }

    _SEEN[r.file_hash or ""] = r.file_name
    return {
        "结论": "首次上传 → 登记指纹",
        "命中": False,
        "本次文件": r.file_name,
        "指纹": r.file_hash,
        "已登记的指纹数": len(_SEEN),
        **r.model_dump(),
    }


def reset() -> dict:
    """清空指纹表，方便反复做实验。"""
    n = len(_SEEN)
    _SEEN.clear()
    return {"已清空": n}
