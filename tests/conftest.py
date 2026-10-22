"""pytest 全局初始化 + 每个测试独立的 sqlite 文件。

**为什么先 init**：本包的 `__init__.py` 是 NoneBot 插件入口，模块级会
`get_plugin_config(Config)`；driver 没初始化时会抛
`ValueError: NoneBot has not been initialized.`，而 conftest 最先被 pytest 导入。
"""

from __future__ import annotations

import importlib.util
import os
from typing import TYPE_CHECKING

import nonebot
from nonebot.adapters.onebot.v11 import Adapter
import pytest

if TYPE_CHECKING:
    from pathlib import Path

os.environ.setdefault("COMMAND_START", '["", "/"]')

# 用 none 驱动：单元测试不需要任何服务器/客户端。
nonebot.init(driver="~none", log_level="WARNING")
nonebot.get_driver().register_adapter(Adapter)


@pytest.fixture(autouse=True)
def _store(tmp_path: Path) -> None:
    """把插件库指向临时文件；`store` 尚未实现时（Task 0-2）自动跳过。"""
    if importlib.util.find_spec("nonebot_plugin_checkin.store") is None:
        return
    from nonebot_plugin_checkin import store

    store.init(tmp_path / "checkin.sqlite3")
