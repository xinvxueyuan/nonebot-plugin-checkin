"""最小冒烟：插件能被导入、元数据齐全。"""

from __future__ import annotations


def test_plugin_metadata_is_complete() -> None:
    from nonebot_plugin_checkin import __plugin_meta__ as meta

    assert meta.name == "签到"
    assert meta.extra is not None
    assert meta.extra["menu_type"] == "娱乐"
    assert [c["command"] for c in meta.extra["commands"]] == [
        "签到",
        "我的签到",
        "签到排行",
    ]


def test_store_init_is_wired_for_startup() -> None:
    """插件模块里必须把 store.init(default_db_path()) 挂到启动钩子上。"""
    # 注意：`from nonebot_plugin_checkin import __init__` 拿到的是模块对象的
    # `__init__` 方法包装器，不是包本身；这里直接 import 包。
    import nonebot_plugin_checkin as plugin_init

    assert callable(plugin_init._startup_init)


def test_commands_are_registered() -> None:
    from nonebot_plugin_checkin import handle

    for matcher in (handle.checkin_cmd, handle.rank_cmd, handle.me_cmd):
        assert matcher is not None
