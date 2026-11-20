"""昵称与头像：缓存命中 / 过期 / 失败路径（全程 mock，不联网）。"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx

if TYPE_CHECKING:
    import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"0" * 100  # qlogo 也常返回这个
GIF = b"GIF89a" + b"0" * 64  # 既非 PNG 也非 JPEG
G, U1, U2, U3 = 7001, 111, 222, 333


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


async def test_avatar_downloaded_then_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin import members

    monkeypatch.setattr(members, "_download", AsyncMock(return_value=PNG))
    assert await members.fetch_avatar(U1) == PNG
    assert members.avatar_path(U1).is_file()
    monkeypatch.setattr(members, "_download", AsyncMock(return_value=b"DIFFERENT"))
    assert await members.fetch_avatar(U1) == PNG  # 走缓存
    assert members._download.await_count == 0


async def test_avatar_expired_is_redownloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin import members

    path = members.avatar_path(U1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    old = time.time() - 31 * 60
    os.utime(path, (old, old))
    monkeypatch.setattr(members, "_download", AsyncMock(return_value=PNG))
    assert await members.fetch_avatar(U1) == PNG
    assert members._download.await_count == 1


async def test_avatar_failure_does_not_write_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_checkin import members

    monkeypatch.setattr(members, "_download", AsyncMock(return_value=None))
    assert await members.fetch_avatar(U2) is None
    assert not members.avatar_path(U2).exists()


async def test_avatar_zero_ttl_never_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin import members

    path = members.avatar_path(U1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    old = time.time() - 4000 * 60
    os.utime(path, (old, old))
    monkeypatch.setattr(members, "_download", AsyncMock(return_value=b"SHOULD-NOT-RUN"))
    assert await members.fetch_avatar(U1, ttl_minutes=0) == PNG
    assert members._download.await_count == 0


# ── 头像格式：qlogo 实测既返回 PNG 也返回 JPEG ────────────────────────────────
# 这几个用例要覆盖**真实格式判断**，所以只替换 httpx 的传输层、让 _download 本体照跑。
# 若在这里桩掉 _download，测到的就只是桩自己，格式判断一行都跑不到。


def _stub_avatar_http(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    """把 httpx 请求接到固定响应体上：走真实下载代码路径，不联网。"""
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, content=body))

    def _client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", _client)


async def test_download_accepts_png(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin import members

    _stub_avatar_http(monkeypatch, PNG)
    assert await members._download(U3) == PNG


async def test_download_accepts_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qlogo 回 JPEG 时必须收下——只认 PNG 时生产头像永远是空白占位圆。"""
    from nonebot_plugin_checkin import members

    _stub_avatar_http(monkeypatch, JPEG)
    assert await members._download(U3) == JPEG


async def test_download_rejects_unknown_format(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """既非 PNG 也非 JPEG：丢弃，且日志要说清是「不可识别的图片格式」。"""
    from nonebot_plugin_checkin import members

    _stub_avatar_http(monkeypatch, GIF)
    with caplog.at_level(logging.WARNING, logger="nonebot_plugin_checkin"):
        assert await members._download(U3) is None
    assert "不可识别" in caplog.text
    assert "不是 PNG" not in caplog.text
    assert not members.avatar_path(U3).exists()


async def test_fetch_avatar_accepts_jpeg_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：JPEG 响应要真的走通「下载 → 格式判断 → 落盘 → 返回」。"""
    from nonebot_plugin_checkin import members

    _stub_avatar_http(monkeypatch, JPEG)
    assert await members.fetch_avatar(U3) == JPEG
    assert members.avatar_path(U3).read_bytes() == JPEG


async def test_fetch_avatar_unknown_format_writes_no_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_checkin import members

    _stub_avatar_http(monkeypatch, GIF)
    assert await members.fetch_avatar(U3) is None
    assert not members.avatar_path(U3).exists()
