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

# 桥接必须在**导入阶段**完成，不能等到 on_startup：
# NoneBot 按注册顺序执行启动钩子，若 htmlrender 先加载，它的钩子会先启动浏览器，
# 那时 .env 里的 PLAYWRIGHT_BROWSERS_PATH 还没进 os.environ，会启动失败。
# 这里包一层 try：插件导入期 config 已就绪，但异常不该让整个插件加载失败。
try:
    envbridge.bridge_playwright_path(
        getattr(get_driver().config, "playwright_browsers_path", None)
    )
except Exception as exc:  # pragma: no cover - 极端情况下 driver 未就绪
    import logging

    logging.getLogger("nonebot_plugin_checkin").warning(
        f"导入期桥接 PLAYWRIGHT_BROWSERS_PATH 失败（不影响其它功能）: {exc!r}"
    )


async def _startup_init() -> None:
    """启动钩子：按 localstore 的数据目录建表（幂等）。

    PLAYWRIGHT_BROWSERS_PATH 的桥接已在模块导入阶段完成（见上），
    这里再调一次是无害的兜底（已有值时不覆盖）。
    """
    envbridge.bridge_playwright_path(
        getattr(get_driver().config, "playwright_browsers_path", None)
    )
    store.init(store.default_db_path())


get_driver().on_startup(_startup_init)

from . import handle  # 导入即注册三条命令

__all__ = ["__plugin_meta__", "_startup_init", "handle", "store"]
