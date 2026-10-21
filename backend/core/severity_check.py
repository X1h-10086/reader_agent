"""backend/core/severity_check.py —— CAP-CORE-02「severity 校验器」的实现。

这是探针台上第一条**带参数**的能力 —— 用来验证 docs/05 §3.2 的核心承诺：

    前端表单由注册表里的 params 描述自动生成，
    **加能力不需要改前端一个字。**

它干的活很小：你给它一个字符串，它告诉你这个等级合不合法、是什么意思。
但它的意义不小：全系统所有意见的等级都由 backend/core/enums.py 这一份清单管着，
谁想塞私货，当场被拦 —— 正是你在动作 2 亲眼见过的那个报错，现在搬到了网页上。
"""

from __future__ import annotations

from backend.core.enums import Severity

# 每个等级的一句话解释 —— 页面上显示用
含义 = {
    "blocking": "阻断：不改不能往下走",
    "major": "严重：明显违规，需人工确认",
    "minor": "一般：规范性问题",
    "advice": "建议：可有可无的优化点",
}


def run(severity: str = "") -> dict:
    """试一个 severity 值，报告它合法/非法与含义。

    探针台输入框里输什么，这里就收什么 —— 输 bloking 也能跑，
    但你会看到枚举把它当场拦下。
    """
    全部合法 = Severity.values()

    if not severity.strip():
        return {"error": "请在参数里给一个等级，例如 blocking", "合法取值": 全部合法}

    try:
        s = Severity(severity.strip())
        return {
            "输入": severity,
            "判定": "合法",
            "含义": 含义.get(s.value, ""),
            "全部合法取值": 全部合法,
        }
    except ValueError:
        # 拼错/瞎编 → 不是程序崩溃，而是一份「为什么不行」的报告
        猜测 = [v for v in 全部合法 if severity.strip().lower()[:2] == v[:2]]
        return {
            "输入": severity,
            "判定": "非法",
            "原因": f"'{severity}' 不在清单里，清单一共只有 {len(全部合法)} 个取值",
            "你可能想输入": 猜测 or "（没有相似的合法值）",
            "全部合法取值": 全部合法,
        }
