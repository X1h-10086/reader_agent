"""backend/main.py —— 整个后端的入口。

跑法（在项目根目录、venv 激活状态下）：
    python -m backend.main
然后浏览器打开 http://127.0.0.1:8000/console

⚠️ 这个文件是整个项目里**第一个** import fastapi 的地方。
    在它下面的 backend/core/ 里，一行 fastapi 都不许出现 ——
    那是你亲口答对过的规矩：厨师不认识菜单。

四条接口，正好对应 docs/05 §3.1 探针台需要的全部数据：
    GET  /health                  环境/服务是否正常
    GET  /capabilities            能力注册表（左栏清单）
    POST /capabilities/{id}/run   执行某条能力（中间的执行按钮）
    GET  /console                 探针台页面本身（右边那一大片）
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse

from backend.core.capability import all_capabilities, get_capability, run_capability

# 页面模板放在 backend/templates/ 下，用绝对路径读，免得换台机器就跑偏
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="文档审核智能体 · 能力探针台", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """服务还活着吗？已注册几条能力？探针台一打开就会问这句。"""
    return {"status": "ok", "service": "reader-agent", "capabilities": len(all_capabilities())}


@app.get("/capabilities")
def capabilities(module: str | None = None) -> dict:
    """能力清单。module 可传 CORE / M1 / M2 ... 做筛选。

    注意这里故意不用 FastAPI 的 Query()：写成普通默认参数，
    走 HTTP 时 FastAPI 照样当成网址参数接收，而你在 Python 里
    直接调用 capabilities() 也能得到正确结果 —— 否则默认值会变成
    一个 Query 对象，把筛选逻辑悄悄带偏。
    """
    caps = all_capabilities()
    if module:
        caps = [c for c in caps if c.module == module]
    return {"total": len(caps), "items": [c.model_dump() for c in caps]}


@app.post("/capabilities/{cap_id}/run")
def capability_run(cap_id: str, params: dict | None = None) -> dict:
    """执行一条能力，返回统一回执（含耗时）。"""
    return run_capability(cap_id, params).model_dump()


@app.post("/capabilities/{cap_id}/run-upload")
def capability_run_upload(cap_id: str, file: UploadFile = File(...)) -> dict:
    """上传文件后执行能力（CAP-M1-01/02 走这条）。

    这就是「服务员」的标准动作：
        接住上传 → 落到临时文件 → 把路径递给厨师 → 端走结果 → 擦干净桌子
    """
    cap = get_capability(cap_id)
    if cap is None:
        return run_capability(cap_id).model_dump()      # 复用统一的「没有这条能力」
    if not cap.needs_file:
        return {
            "capability_id": cap_id, "ok": False, "elapsed_ms": 0.0,
            "result": {"error": f"{cap_id} 不需要文件，请走 /run 接口"},
        }

    # 后缀只是给临时文件用；真正的格式判断在 ingest 里靠文件头
    后缀 = Path(file.filename or "").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=后缀) as tmp:
        shutil.copyfileobj(file.file, tmp)
        临时路径 = tmp.name

    try:
        return run_capability(
            cap_id, {"file_path": 临时路径, "display_name": file.filename}
        ).model_dump()
    finally:
        os.unlink(临时路径)      # 无论成败都清理，别在盘上留垃圾


@app.get("/console", response_class=HTMLResponse)
def console() -> str:
    """探针台页面。目前是单个 HTML 文件，不需要 npm/vite 那一整套前端工程。"""
    return (TEMPLATE_DIR / "console.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    # uvicorn = 那个守在门口等客人的店员；--reload 改代码自动重启（现在先不用）
    uvicorn.run(app, host="127.0.0.1", port=8000)
