"""命令层必须把群号传给背景图分配：同群去重靠它划范围，漏传就退化回「同群也撞图」。

放在单独文件里（而不是 test_handle.py）：这里关心的是**调用协议**，
不是命令的业务规则。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.onebot.v11.event import Sender
import pytest

if TYPE_CHECKING:
    from pathlib import Path

G, U = 9001, 4242


def _event(user_id: int = U, group_id: int = G) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_id=1,
        message_type="group",
        message=[],
        raw_message="",
        font=0,
        sender=Sender(user_id=user_id, nickname="测试", role="member"),
        group_id=group_id,
    )


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.send_group_msg = AsyncMock()
    bot.get_group_member_list = AsyncMock(return_value=[])
    bot.get_stranger_info = AsyncMock(return_value={})
    return bot


@pytest.fixture
def _quiet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int | None]]:
    """把命令层的外部依赖换成替身，只记录 ensure_bg 收到的 (user_id, group_id)。"""
    from nonebot_plugin_checkin import assets, handle, members, store

    seen: list[tuple[int, int | None]] = []

    async def fake_bg(
        _data_dir: Path, user_id: int, *, group_id: int | None = None, **_kw: Any
    ) -> None:
        seen.append((user_id, group_id))
        return

    async def _none(*_a: Any, **_kw: Any) -> None:
        return None

    store.save_checkin(
        group_id=G,
        user_id=U,
        date_key="2026-10-22",
        points=10,
        streak=1,
        total_points=10,
        at=1.0,
    )
    monkeypatch.setattr(assets, "ensure_bg", fake_bg)
    monkeypatch.setattr(assets, "fetch_signature", _none)
    monkeypatch.setattr(members, "fetch_avatar", _none)
    monkeypatch.setattr(handle, "_send", _none)
    return seen


@pytest.mark.asyncio
async def test_checkin_passes_group_id_to_ensure_bg(
    _quiet: list[tuple[int, int | None]],
) -> None:
    from nonebot_plugin_checkin import handle

    await handle.do_checkin(bot=_bot(), event=_event())
    assert _quiet == [(U, G)]


@pytest.mark.asyncio
async def test_rank_passes_group_id_to_ensure_bg(
    _quiet: list[tuple[int, int | None]],
) -> None:
    from nonebot_plugin_checkin import handle

    await handle.do_rank(bot=_bot(), event=_event())
    assert _quiet == [(U, G)]
