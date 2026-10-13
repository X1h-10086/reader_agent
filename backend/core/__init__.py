"""core —— 全系统共享契约层（菜单 = 食材的定义）。

这里放两类东西：枚举（enums.py）与数据结构（models.py）。

铁律：本层可以 import 标准库和 pydantic，**禁止 import fastapi / sqlalchemy / requests
等第三方框架**。原因见 enums.py 顶部注释。
"""
