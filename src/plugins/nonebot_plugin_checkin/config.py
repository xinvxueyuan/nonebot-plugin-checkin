"""签到插件配置（env 键 = 字段名大写）。"""

from __future__ import annotations

from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """签到插件配置；NoneBot 用 `get_plugin_config(Config)` 读取。"""


plugin_config = get_plugin_config(Config)
