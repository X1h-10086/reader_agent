"""F-03 验收：文档接入关卡（CAP-M1-01 / CAP-M1-02）。

判定标准：全 [OK] = 验身、称重、指纹三道关卡都按预期工作。

用法：
    python -m tests.test_ingest
"""

import sys
import tempfile
import zipfile
from pathlib import Path

from backend.parsing.ingest import MAX_SIZE_BYTES, file_hash, inspect, sniff_type

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(说明: str, 期望, 实际) -> None:
    global passed, failed
    if 期望 == 实际:
        print(f"  [OK] {说明:<34} -> {实际!r}")
        passed += 1
    else:
        print(f"  [!!] {说明:<34} -> 期望 {期望!r}，实际 {实际!r}")
        failed += 1


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # ---------------- 造样本 ----------------
        (d / "real.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (d / "fake.pdf").write_text("我其实是纯文本，只是改了后缀", encoding="utf-8")
        (d / "fake.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 60)
        (d / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 60)
        (d / "empty.pdf").write_bytes(b"")

        with zipfile.ZipFile(d / "real.docx", "w") as z:
            z.writestr("word/document.xml", "<x/>")

        # 稀疏文件：秒建 50MB+，不真占磁盘
        with (d / "big.pdf").open("wb") as f:
            f.truncate(MAX_SIZE_BYTES + 1)

        (d / "a.pdf").write_bytes(b"%PDF-1.4\nabc\n")
        (d / "b.pdf").write_bytes(b"%PDF-1.4\nabc\n")
        (d / "c.pdf").write_bytes(b"%PDF-1.4\nabd\n")

        # ---------------- 验身 ----------------
        print("=" * 68)
        print("验身 —— 只看文件头，不看后缀")
        print("=" * 68)
        check("真 PDF", "pdf", sniff_type(d / "real.pdf"))
        check("真 docx（zip 里的 word/）", "docx", sniff_type(d / "real.docx"))
        check("假 PDF（内容是文本）", "text", sniff_type(d / "fake.pdf"))
        check("伪装成 pdf 的 exe", "unknown", sniff_type(d / "fake.exe"))
        check("老式 Word(.doc)", "ole2", sniff_type(d / "old.doc"))

        # ---------------- 进门结论 ----------------
        print()
        print("=" * 68)
        print("进门结论")
        print("=" * 68)

        r = inspect(d / "real.pdf")
        check("真 PDF 放行", True, r.allowed)
        check("真 PDF 不撒谎", False, r.is_lying)
        check("真 PDF 有指纹", True, bool(r.file_hash))

        r = inspect(d / "fake.pdf")
        check("假 PDF 识别为 text", "text", r.real_type)
        check("假 PDF 被标记撒谎", True, r.is_lying)
        check("文本在白名单内，仍放行", True, r.allowed)

        r = inspect(d / "fake.exe")
        check("exe 被拒", False, r.allowed)
        check("exe 拒收时不算指纹", None, r.file_hash)

        r = inspect(d / "old.doc")
        check("老 .doc 被拒", False, r.allowed)
        check("老 .doc 提示另存为", True, "另存为" in (r.reason or ""))

        r = inspect(d / "big.pdf")
        check("超大文件被拒", False, r.allowed)
        check("超大文件不算指纹（不白花时间）", None, r.file_hash)

        r = inspect(d / "empty.pdf")
        check("空文件被拒", False, r.allowed)

        # ---------------- 指纹 ----------------
        print()
        print("=" * 68)
        print("指纹 —— 去重")
        print("=" * 68)
        h1 = file_hash(d / "a.pdf")
        h2 = file_hash(d / "b.pdf")
        check("不同文件名、内容相同 → 指纹相同", True, h1 == h2)
        check("改 1 个字节 → 指纹不同", True, file_hash(d / "c.pdf") != h1)

        # ---------------- 总结 ----------------
        print()
        print("=" * 68)
        print(f"通过 {passed} 项 [OK] ｜ 失败 {failed} 项 [!!]")
        print("=" * 68)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
