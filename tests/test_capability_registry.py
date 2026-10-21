"""F-02 验收：能力注册表与实现「不能漂移」（docs/05 §3.2 / §5）。

为什么需要它：
    能力靠注册表的 target 字符串指向真实函数。万一哪天有人改了函数名、
    或删了实现却忘了删注册表，探针台就会出现「点执行 → 404 / 找不到实现」。
    这个测试就是防这种漂移：每条能力都必须真的能被调用。

判定标准：
    ① 注册表非空（至少 CAP-CORE-01）；
    ② 每条能力的 target 能动态加载并成功执行（不崩溃）；
    ③ CAP-CORE-01 的数据契约自检必须 5/5。

用法：
    python -m tests.test_capability_registry
"""

import sys

from backend.core.capability import all_capabilities, run_capability
from backend.parsing.parse_demo import FIXTURE as SAMPLE_FILE

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    caps = all_capabilities()
    assert caps, "注册表空了 —— 至少要有 CAP-CORE-01"

    passed = 0
    for cap in caps:
        # 上传类能力必须真给一个文件，否则测的只是「参数缺失」而不是实现本身
        参数 = (
            {"file_path": str(SAMPLE_FILE), "display_name": "mineru_raw_sample.json"}
            if cap.needs_file
            else {}
        )
        r = run_capability(cap.id, 参数)

        # ② 执行必须成功；失败一律视为问题（不再只盯「找不到实现」）
        if not r.ok:
            print(f"  [!!] {cap.id:13} 执行失败：{r.result.get('error')}")
            continue

        print(f"  [OK] {cap.id:13} 后端耗时={r.elapsed_ms}ms")
        passed += 1

        # ③ 对数据契约自检额外校验结果本身
        if cap.id == "CAP-CORE-01":
            assert r.result.get("符合预期") == "5/5", "数据契约自检没全过，去查 models.py"

    print(f"\n能力总数 {len(caps)}，可运行 {passed} 条")

    # ① 全部可运行才算过
    assert passed == len(caps), "有能力的 target 失效，去查 capability.py"
    print("结论：注册表与实现一致 ✓")


if __name__ == "__main__":
    main()
