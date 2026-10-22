"""昵称与头像：缓存命中 / 过期 / 失败路径（全程 mock，不联网）。"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
G, U1, U2 = 7001, 111, 222


def _bot(names: dict[int, str]) -> MagicMock:
    bot = MagicMock()
    bot.get_group_member_list = AsyncMock(
        return_value=[
            {"user_id": uid, "nickname": name, "card": ""}
            for uid, name in names.items()
        ]
    )
    return bot


async def test_names_fetched_once_then_cached() -> None:
    from nonebot_plugin_checkin import members

    bot = _bot({U1: "阿一", U2: "阿二"})
    got = await members.resolve_names(bot, group_id=G, user_ids=[U1, U2])
    assert got == {U1: "阿一", U2: "阿二"}
    assert bot.get_group_member_list.await_count == 1
    got2 = await members.resolve_names(bot, group_id=G, user_ids=[U1])
    assert got2 == {U1: "阿一"}
    assert bot.get_group_member_list.await_count == 1  # 缓存命中，不再调 API


async def test_names_cache_expires() -> None:
    from nonebot_plugin_checkin import members, store

    store.save_member_names(group_id=G, names={U1: "旧名"}, at=time.time() - 31 * 60)
    bot = _bot({U1: "新名"})
    assert await members.resolve_names(bot, group_id=G, user_ids=[U1]) == {U1: "新名"}
    assert bot.get_group_member_list.await_count == 1


async def test_names_fallback_to_uid_when_api_fails() -> None:
    from nonebot_plugin_checkin import members, store

    bot = MagicMock()
    bot.get_group_member_list = AsyncMock(side_effect=RuntimeError("协议端挂了"))
    assert await members.resolve_names(bot, group_id=G, user_ids=[U1]) == {U1: str(U1)}
    assert store.get_member_names(group_id=G) == {}  # 失败不写缓存


async def test_names_zero_ttl_never_expires() -> None:
    from nonebot_plugin_checkin import members, store

    store.save_member_names(group_id=G, names={U1: "老名"}, at=time.time() - 4000 * 60)
    bot = _bot({U1: "新名"})
    got = await members.resolve_names(bot, group_id=G, user_ids=[U1], ttl_minutes=0)
    assert got == {U1: "老名"}
    assert bot.get_group_member_list.await_count == 0


async def test_avatar_downloaded_then_cached() -> None:
    from nonebot_plugin_checkin import members

    members._download = AsyncMock(return_value=PNG)  # type: ignore[assignment]
    assert await members.fetch_avatar(U1) == PNG
    assert members.avatar_path(U1).is_file()
    members._download = AsyncMock(return_value=b"DIFFERENT")  # type: ignore[assignment]
    assert await members.fetch_avatar(U1) == PNG  # 走缓存
    assert members._download.await_count == 0


async def test_avatar_expired_is_redownloaded() -> None:
    from nonebot_plugin_checkin import members

    path = members.avatar_path(U1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    old = time.time() - 31 * 60
    os.utime(path, (old, old))
    members._download = AsyncMock(return_value=PNG)  # type: ignore[assignment]
    assert await members.fetch_avatar(U1) == PNG
    assert members._download.await_count == 1


async def test_avatar_failure_does_not_write_cache() -> None:
    from nonebot_plugin_checkin import members

    members._download = AsyncMock(return_value=None)  # type: ignore[assignment]
    assert await members.fetch_avatar(U2) is None
    assert not members.avatar_path(U2).exists()


async def test_avatar_zero_ttl_never_expires() -> None:
    from nonebot_plugin_checkin import members

    path = members.avatar_path(U1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    old = time.time() - 4000 * 60
    os.utime(path, (old, old))
    members._download = AsyncMock(return_value=b"SHOULD-NOT-RUN")  # type: ignore[assignment]
    assert await members.fetch_avatar(U1, ttl_minutes=0) == PNG
    assert members._download.await_count == 0
