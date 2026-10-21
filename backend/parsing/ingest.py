"""backend/parsing/ingest.py —— 文档接入的第一道关卡（M1 流程第 ① 步）。

对应文档：
    docs/modules/M1-文档接入与解析.md §2 ①（校验：类型白名单 / 大小上限 / sha256 去重）
    docs/05 CAP-M1-01（多格式识别） / CAP-M1-02（文件去重）

三条原则：
1. **不信后缀，只信文件头**（magic bytes）—— 后缀是用户随手写的，文件头是内容决定的。
2. **不信客户端自报的 Content-Type** —— 那是浏览器自己填的，可以随便写。
3. **分块算指纹** —— 多大的文件都不会把内存撑爆。

本文件不 import fastapi：它只认「一个文件路径」。
把浏览器上传的东西变成路径，是 api 层（服务员）的活。
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from pydantic import BaseModel

# ------------------------------------------------------------------ 策略常量

# 白名单：没列出来的格式一律拒绝。
# 用白名单而不是黑名单——黑名单永远漏（新的危险格式你根本想不到）。
ALLOWED_TYPES: dict[str, str] = {
    "pdf": "PDF 文档",
    "docx": "Word 文档",
    "pptx": "PowerPoint 演示",
    "xlsx": "Excel 表格",
    "png": "PNG 图片",
    "jpeg": "JPEG 图片",
    "text": "纯文本文档",
}

# 单个文件上限 50MB。超过直接拒，别让一个大文件把整个服务拖死。
MAX_SIZE_BYTES = 50 * 1024 * 1024

# 每种格式固定不变的开头签名（magic bytes）
_SIGNATURES: list[tuple[str, bytes]] = [
    ("pdf", b"%PDF"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpeg", b"\xff\xd8\xff"),
    ("zip", b"PK\x03\x04"),          # docx / xlsx / pptx 都是 zip
    ("ole2", b"\xd0\xcf\x11\xe0"),   # 老式 Office：.doc / .xls / .ppt
]

# 同一种东西的不同叫法（避免把 .txt 误判成「后缀撒谎」）
_ALIASES = {"txt": "text", "md": "text", "text": "text", "jpg": "jpeg", "jpeg": "jpeg"}


# ------------------------------------------------------------------ 回执结构

class IngestResult(BaseModel):
    """进门回执：这一份文件能不能放行、它到底是什么、指纹是多少。

    注意：这是**进门那一刻**的结论，不含任何解析结果。
    解析（MinerU）在 F-04 才接上，那时会再产出一份 DocumentVersion。
    """

    file_name: str
    declared_type: str            # 后缀声称的类型
    real_type: str                # 文件头证实的类型
    is_lying: bool                # 后缀是否撒谎
    size_bytes: int
    allowed: bool
    reason: str | None = None     # 不放行时，给人看的原因
    file_hash: str | None = None  # 指纹；被拒的文件不算，省时间


# ------------------------------------------------------------------ 验身

def _zip_flavor(path: Path) -> str:
    """zip 有好几种，靠里面装了什么目录来区分 docx / pptx / xlsx。"""
    try:
        names = zipfile.ZipFile(path).namelist()
    except Exception:
        return "zip"

    for prefix, name in (("word/", "docx"), ("ppt/", "pptx"), ("xl/", "xlsx")):
        if any(n.startswith(prefix) for n in names):
            return name
    return "zip"


def sniff_type(path: str | Path) -> str:
    """读文件开头的字节，判断它到底是什么格式。只看内容，不看名字。"""
    path = Path(path)
    with path.open("rb") as f:
        head = f.read(8)

    for 类型, 签名 in _SIGNATURES:
        if head.startswith(签名):
            return _zip_flavor(path) if 类型 == "zip" else 类型

    # 不是任何已知二进制格式 → 试着当 UTF-8 文本读
    try:
        path.read_text(encoding="utf-8")
        return "text"
    except UnicodeDecodeError:
        return "unknown"


# ------------------------------------------------------------------ 指纹

def file_hash(path: str | Path, chunk: int = 8192) -> str:
    """算 sha256 指纹。分块读，内存只占 8KB。

    同一份文件无论改什么名字、放在哪个目录，指纹都一样 ——
    这就是 CAP-M1-02「文件去重」的全部秘密。
    """
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        for 块 in iter(lambda: f.read(chunk), b""):
            h.update(块)
    return h.hexdigest()


# ------------------------------------------------------------------ 总入口

def inspect(path: str | Path, display_name: str | None = None) -> IngestResult:
    """一份文件进门：验身 → 称重 → 算指纹 → 给出放行与否的结论。

    顺序是刻意的：**先称重再算指纹**。一个 2GB 文件如果先算指纹，
    等于白花几秒钟读满整个磁盘，然后才告诉用户"太大了"。

    display_name 用于保留用户看到的原始文件名 ——
    上传时文件会先落到临时目录，临时名（tmp8f3a.pdf）对人没有意义。
    """
    path = Path(path)
    name = display_name or path.name
    size = path.stat().st_size
    declared = Path(name).suffix.lstrip(".").lower() or "unknown"

    # ① 称重（最便宜的检查放最前面）
    if size > MAX_SIZE_BYTES:
        return IngestResult(
            file_name=name, declared_type=declared, real_type="unknown",
            is_lying=False, size_bytes=size, allowed=False,
            reason=f"文件 {size / 1024 / 1024:.1f}MB，超过上限 {MAX_SIZE_BYTES // 1024 // 1024}MB",
        )

    if size == 0:
        return IngestResult(
            file_name=name, declared_type=declared, real_type="unknown",
            is_lying=False, size_bytes=0, allowed=False, reason="空文件",
        )

    # ② 验身
    real = sniff_type(path)
    规范 = lambda t: _ALIASES.get(t, t)  # noqa: E731
    lying = 规范(declared) != 规范(real)

    # ③ 白名单
    if real not in ALLOWED_TYPES:
        if real == "ole2":
            reason = "这是老式 Office 格式（.doc/.xls/.ppt），请另存为 .docx/.xlsx/.pptx 后重传"
        elif real == "zip":
            reason = "这是一个普通 zip 压缩包，不是 Word/PPT/Excel 文档"
        else:
            reason = f"不支持的格式：{real}（只收 {' / '.join(sorted(ALLOWED_TYPES))}）"
        return IngestResult(
            file_name=name, declared_type=declared, real_type=real,
            is_lying=lying, size_bytes=size, allowed=False, reason=reason,
        )

    # ④ 算指纹（放行的才值得算）
    return IngestResult(
        file_name=name, declared_type=declared, real_type=real,
        is_lying=lying, size_bytes=size, allowed=True,
        reason="后缀与实际格式不符，已按实际格式接收" if lying else None,
        file_hash=file_hash(path),
    )
