"""命令层：签到 / 我的签到 / 签到排行（三条命令都 @ 发起人；出图失败回退纯文本）。"""

import logging
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from . import members, render, store
from .config import plugin_config
from .service import evaluate, today_in

logger = logging.getLogger("nonebot_plugin_checkin")

checkin_cmd = on_command(plugin_config.checkin_cmd, priority=30, block=True)
rank_cmd = on_command(plugin_config.checkin_rank_cmd, priority=30, block=True)
me_cmd = on_command(plugin_config.checkin_me_cmd, priority=30, block=True)


async def _send(bot: Bot, event: GroupMessageEvent, payload: dict[str, Any]) -> None:
    """先试图卡，渲染不可用就发纯文本；两条路径都 @ 到发起人。"""
    png = await render.render_checkin_card(**payload)
    message = Message(MessageSegment.at(event.user_id))
    if png is not None:
        message += MessageSegment.image(png)
    else:
        message += MessageSegment.text("\n" + render.build_fallback_text(**payload))
    await bot.send_group_msg(group_id=event.group_id, message=message)


async def do_checkin(*, bot: Bot, event: GroupMessageEvent) -> None:
    """签到：算出奖励 → 幂等落库 → 回执（含排名）。"""
    group_id, user_id = event.group_id, event.user_id
    today = today_in(plugin_config.checkin_timezone)
    state = store.get_state(group_id=group_id, user_id=user_id)
    result = evaluate(
        state,
        today=today,
        daily_points=plugin_config.checkin_daily_points,
        streak_bonus=plugin_config.checkin_streak_bonus,
        streak_bonus_cap=plugin_config.checkin_streak_bonus_cap,
    )
    if not result.already:
        store.save_checkin(
            group_id=group_id,
            user_id=user_id,
            date_key=today.isoformat(),
            points=result.points_gained,
            streak=result.streak,
            total_points=result.total_points,
        )
    rank = next(
        (
            i + 1
            for i, row in enumerate(
                store.top(group_id=group_id, limit=plugin_config.checkin_rank_size)
            )
            if row[0] == user_id
        ),
        None,
    )
    nickname = event.sender.card or event.sender.nickname or str(user_id)
    await _send(
        bot,
        event,
        {
            "title": "今天已经签过啦" if result.already else "签到成功",
            "nickname": nickname,
            "points_gained": result.points_gained,
            "total_points": result.total_points,
            "streak": result.streak,
            "rank": rank,
            "already": result.already,
        },
    )


async def do_rank(*, bot: Bot, event: GroupMessageEvent) -> None:
    """群内积分排行（Top N）：图卡显示头像 + 昵称，渲染失败回退纯文本。"""
    top_rows = store.top(group_id=event.group_id, limit=plugin_config.checkin_rank_size)
    if not top_rows:
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message([
                MessageSegment.at(event.user_id),
                MessageSegment.text("\n本群还没有人签到过，抢个第一吧"),
            ]),
        )
        return
    user_ids = [uid for uid, _points, _streak in top_rows]
    names = await members.resolve_names(bot, group_id=event.group_id, user_ids=user_ids)
    rows: list[dict[str, Any]] = []
    for i, (uid, points, streak) in enumerate(top_rows, start=1):
        rows.append({
            "rank": i,
            "name": names.get(uid, str(uid)),
            "points": points,
            "streak": streak,
            "avatar_png": await members.fetch_avatar(uid),
        })
    title = f"本群签到排行（前 {len(rows)} 名）"
    png = await render.render_rank_card(rows, title=title)
    message = Message(MessageSegment.at(event.user_id))
    if png is not None:
        message += MessageSegment.image(png)
    else:
        message += MessageSegment.text(
            "\n" + render.build_rank_fallback_text(rows, title=title)
        )
    await bot.send_group_msg(group_id=event.group_id, message=message)


async def do_me(*, bot: Bot, event: GroupMessageEvent) -> None:
    """查看自己的积分与连续天数。"""
    state = store.get_state(group_id=event.group_id, user_id=event.user_id)
    text = f"累计 {state.points} 分 · 连续 {state.streak} 天"
    if state.last_date is not None:
        text += f" · 最近签到 {state.last_date.isoformat()}"
    else:
        text += " · 还没签到过"
    await bot.send_group_msg(
        group_id=event.group_id,
        message=Message([
            MessageSegment.at(event.user_id),
            MessageSegment.text("\n" + text),
        ]),
    )


@checkin_cmd.handle()
async def _h_checkin(bot: Bot, event: GroupMessageEvent) -> None:
    await do_checkin(bot=bot, event=event)


@rank_cmd.handle()
async def _h_rank(bot: Bot, event: GroupMessageEvent) -> None:
    await do_rank(bot=bot, event=event)


@me_cmd.handle()
async def _h_me(bot: Bot, event: GroupMessageEvent) -> None:
    await do_me(bot=bot, event=event)


__all__ = ["checkin_cmd", "do_checkin", "do_me", "do_rank", "me_cmd", "rank_cmd"]
