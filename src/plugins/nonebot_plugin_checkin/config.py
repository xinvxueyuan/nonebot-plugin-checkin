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

    # ── 设计系统素材 ──
    # 背景图来自自建 xbm 随机图 API（本机回环 127.0.0.1:4390，不涉外网）。
    checkin_bg_url: str = "http://127.0.0.1:4390/v1/random"
    # xbm 的 x-api-key；留空则完全跳过取图、只用纯 CSS 渐变背景。
    checkin_bg_api_key: str = ""
    # 背景图按人缓存多少分钟（0 = 永不过期）。
    checkin_bg_ttl_minutes: int = Field(default=15, ge=0, le=10080)
    # 取图超时（秒）。超时即降级为渐变背景，不阻塞签到。
    checkin_bg_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    # 个性签名缓存分钟数（默认 1 天；签名是低频变化数据）。
    checkin_quote_ttl_minutes: int = Field(default=1440, ge=0, le=43200)
    # 引用区最多显示多少字符，超出截断加省略号。
    checkin_quote_max_chars: int = Field(default=60, ge=10, le=200)

    # ── 渲染环境 ──
    # Playwright 浏览器目录。写进 .env 后由启动钩子桥接进 os.environ
    # （Playwright 只认环境变量）；若 systemd 已设
    # Environment=PLAYWRIGHT_BROWSERS_PATH，则以后者为准（不覆盖）。
    playwright_browsers_path: str | None = None


plugin_config = get_plugin_config(Config)
