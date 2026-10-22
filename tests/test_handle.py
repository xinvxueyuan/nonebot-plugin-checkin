"""命令层：签到/重复签到/排行（图卡 + 头像）/我的签到/@ 发起人。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.onebot.v11.event import Sender

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

G, U = 9001, 4242
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _event(user_id: int = U, group_id: int | None = G) -> GroupMessageEvent:
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
        group_id=group_id or 0,
    )


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.send_group_msg = AsyncMock()
    bot.get_group_member_list = AsyncMock(return_value=[])
    return bot


def _segments(bot: MagicMock) -> Sequence[Any]:
    return bot.send_group_msg.await_args.kwargs["message"]  # type: ignore[no-any-return]


def _has_type(bot: MagicMock, seg_type: str) -> bool:
    return any(getattr(seg, "type", "") == seg_type for seg in _segments(bot))


async def test_checkin_creates_record_and_replies() -> None:
    from nonebot_plugin_checkin import handle, store

    bot = _bot()
    await handle.do_checkin(bot=bot, event=_event())
    assert bot.send_group_msg.await_count == 1
    s = store.get_state(group_id=G, user_id=U)
    assert s.points == 10 and s.streak == 1


async def test_checkin_twice_same_day_does_not_double_count() -> None:
    from nonebot_plugin_checkin import handle, store

    bot = _bot()
    await handle.do_checkin(bot=bot, event=_event())
    await handle.do_checkin(bot=bot, event=_event())
    assert bot.send_group_msg.await_count == 2
    assert store.get_state(group_id=G, user_id=U).points == 10


async def test_checkin_reply_mentions_the_user() -> None:
    from nonebot_plugin_checkin import handle

    bot = _bot()
    await handle.do_checkin(bot=bot, event=_event())
    assert _has_type(bot, "at")
    assert _segments(bot)[0].data["qq"] == str(U)


async def test_rank_empty_says_so() -> None:
    from nonebot_plugin_checkin import handle

    bot = _bot()
    await handle.do_rank(bot=bot, event=_event())
    assert bot.send_group_msg.await_count == 1
    assert _has_type(bot, "at")


async def test_rank_lists_top_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin import handle, members, store

    for uid, pts in ((11, 30), (22, 20)):
        store.save_checkin(
            group_id=G,
            user_id=uid,
            date_key="2026-10-22",
            points=pts,
            streak=1,
            total_points=pts,
            at=1.0,
        )
    bot = _bot()
    bot.get_group_member_list = AsyncMock(
        return_value=[
            {"user_id": 11, "nickname": "阿一", "card": ""},
            {"user_id": 22, "nickname": "阿二", "card": ""},
        ]
    )
    monkeypatch.setattr(members, "fetch_avatar", AsyncMock(return_value=None))
    await handle.do_rank(bot=bot, event=_event())
    assert bot.send_group_msg.await_count == 1
    assert _has_type(bot, "at")


async def test_me_reports_state() -> None:
    from nonebot_plugin_checkin import handle, store

    store.save_checkin(
        group_id=G,
        user_id=U,
        date_key="2026-10-22",
        points=10,
        streak=1,
        total_points=10,
        at=1.0,
    )
    bot = _bot()
    await handle.do_me(bot=bot, event=_event())
    assert bot.send_group_msg.await_count == 1
    assert _has_type(bot, "at")
    assert "累计 10 分" in _segments(bot)[-1].data["text"]


async def test_rank_card_uses_names_and_avatars_then_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """排行必须走图卡：top → 昵称 → 逐人头像；图卡失败则回退等价纯文本。"""
    from nonebot_plugin_checkin import handle, members, render, store

    store.save_checkin(
        group_id=G,
        user_id=11,
        date_key="2026-10-22",
        points=30,
        streak=2,
        total_points=30,
        at=1.0,
    )
    seen: dict[str, Any] = {}

    async def fake_render(rows: list[dict[str, Any]], *, title: str) -> bytes:
        seen["rows"] = rows
        seen["title"] = title
        return PNG

    async def fake_names(
        _bot: object, *, group_id: int, user_ids: list[int]
    ) -> dict[int, str]:
        return {uid: f"名字{uid}" for uid in user_ids}

    async def fake_avatar(uid: int) -> bytes:
        return f"PNG{uid}".encode()

    monkeypatch.setattr(render, "render_rank_card", fake_render)
    monkeypatch.setattr(members, "resolve_names", fake_names)
    monkeypatch.setattr(members, "fetch_avatar", fake_avatar)

    bot = _bot()
    await handle.do_rank(bot=bot, event=_event())
    rows = seen["rows"]
    assert rows == [
        {"rank": 1, "name": "名字11", "points": 30, "streak": 2, "avatar_png": b"PNG11"}
    ]
    assert _has_type(bot, "at") and _has_type(bot, "image")

    async def dead_render(_rows: list[dict[str, Any]], *, title: str) -> None:
        return None

    monkeypatch.setattr(render, "render_rank_card", dead_render)
    bot2 = _bot()
    await handle.do_rank(bot=bot2, event=_event())
    text = _segments(bot2)[-1].data["text"]
    assert "名字11" in text and "30 分" in text and "连续 2 天" in text
