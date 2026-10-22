"""签到插件配置（env 键 = 字段名大写，NoneBot 约定，大小写不敏感）。"""

from __future__ import annotations

from nonebot import get_plugin_config
from nonebot.config import BaseSettings
from pydantic import Field


class Config(BaseSettings):
    """签到插件配置。

    字段名即 env 键：`checkin_daily_points` ↔ `CHECKIN_DAILY_POINTS`，大小写不敏感。
    """

    checkin_daily_points: int = Field(default=10, ge=1, le=1000)
    checkin_streak_bonus: int = Field(default=2, ge=0, le=100)
    checkin_streak_bonus_cap: int = Field(default=20, ge=0, le=1000)
    checkin_rank_size: int = Field(default=10, ge=3, le=50)
    checkin_cmd: str = "签到"
    checkin_rank_cmd: str = "签到排行"
    checkin_me_cmd: str = "我的签到"
    checkin_timezone: str = "Asia/Shanghai"
    # 单位分钟；0 = 永不过期；10080 = 7 天
    checkin_nickname_ttl_minutes: int = Field(default=30, ge=0, le=10080)
    checkin_avatar_ttl_minutes: int = Field(default=30, ge=0, le=10080)


plugin_config = get_plugin_config(Config)
