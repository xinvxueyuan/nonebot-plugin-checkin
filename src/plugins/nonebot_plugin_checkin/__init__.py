"""签到插件：每日签到 + 连续天数 + 积分 + 群内排行。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="签到",
    description="每日签到攒积分，连续签到有加成，群内积分排行",
    usage=(
        "签到            今天签到（每天一次）\n"
        "我的签到        查看自己的积分与连续天数\n"
        "签到排行        查看本群积分前 10"
    ),
    type="application",
    homepage="https://github.com/xinvxueyuan/nonebot-plugin-checkin",
    supported_adapters={"nonebot.adapters.onebot.v11"},
    config=Config,
    extra={
        "menu_type": "娱乐",
        "order": 20,
        "introduction": "每日签到攒积分，连续签到有加成，群内积分排行",
        "commands": [
            {"command": "签到", "desc": "今天签到（每天一次）"},
            {"command": "我的签到", "desc": "查看自己的积分与连续天数"},
            {"command": "签到排行", "desc": "本群积分前 10"},
        ],
    },
)

from nonebot import get_driver

from . import envbridge, store


async def _startup_init() -> None:
    """启动时：① 桥接 PLAYWRIGHT_BROWSERS_PATH ② 按 localstore 数据目录建表（幂等）。"""
    # 让 .env 里配置的浏览器路径真正进 os.environ（Playwright 只认环境变量）。
    # systemd 已设 Environment= 时本调用不会覆盖。
    envbridge.bridge_playwright_path(
        getattr(get_driver().config, "playwright_browsers_path", None)
    )
    store.init(store.default_db_path())


get_driver().on_startup(_startup_init)

from . import handle  # 导入即注册三条命令

__all__ = ["__plugin_meta__", "_startup_init", "handle", "store"]
