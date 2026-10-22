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
