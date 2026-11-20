"""出图：签到结果卡片与排行图卡（htmlrender）；任何异常回退 None，由命令层发纯文本。"""

from __future__ import annotations

import base64
from html import escape
import logging
from typing import Any

from nonebot import require

# htmlrender 在导入时就会向 localstore 要目录（靠调用栈识别插件），
# 显式 require 既保证依赖先加载，也让非「插件加载」方式（pytest 直接 import）不报
# `Cannot detect caller plugin`。
require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import html_to_pic

from . import theme

logger = logging.getLogger("nonebot_plugin_checkin")

_CARD_WIDTH = 612
_CARD_VIEWPORT_H = 700  # 签到卡基础高度（不含长引用额外需要的高度）
_RANK_VIEWPORT_H = 230  # 排行的固定头部高度（不含每行）


def _fmt_gained(points_gained: int, already: bool) -> str:
    return "已签过" if already else f"+{points_gained}"


def _card_html(
    *,
    title: str,
    nickname: str,
    points_gained: int,
    total_points: int,
    streak: int,
    rank: int | None,
    already: bool,
    quote: str | None = None,
    bg: object | None = None,
    avatar: bytes | None = None,
) -> str:
    """签到卡 HTML：标题 → 头像 → 5 行标签值 → 分隔线 + 引用。"""
    rows = [
        theme.row("昵称", nickname),
        theme.row("今日积分", _fmt_gained(points_gained, already)),
        theme.row("总积分", str(total_points)),
        theme.row("连续天数", f"{streak} 天"),
    ]
    if rank is not None:
        rows.append(theme.row("本群排名", f"#{rank}"))
    tail = _quote_tail(quote)
    body = (
        theme.avatar_block(avatar)
        + f'<div class="card-title">{escape(title)}</div>'
        + f'<div class="rows">{"".join(rows)}</div>'
        + tail
    )
    return theme.card_shell(bg_data_uri=theme.bg_data_uri(bg), body=body)  # type: ignore[arg-type]


def _quote_tail(quote: str | None) -> str:
    """引用区的「分隔线 + 引用」；空/纯空白引用整块省略（连分隔线一起去掉）。

    不能用 `if quote` 判断：`"   "` 是真值，会渲染出一条只有分隔线、没有内容的尾巴。
    """
    if not quote or not quote.strip():
        return ""
    return theme.divider() + theme.quote_block(quote)


def _rank_html(
    rows: list[dict[str, Any]],
    *,
    title: str,
    quote: str | None = None,
    bg: object | None = None,
) -> str:
    """排行卡 HTML：标题 → 每行（名次/头像/昵称/积分）→ 分隔线 + 引用。"""
    items = []
    for r in rows:
        av = r.get("avatar_png")
        if av:
            img = (
                f'<img class="rank-avatar" src="data:image/png;base64,'
                f'{base64.b64encode(av).decode()}"/>'
            )
        else:
            img = '<span class="rank-avatar"></span>'
        items.append(
            '<div class="rank-row">'
            f'<span class="rank-no">{escape(str(r["rank"]))}</span>{img}'
            f'<span class="rank-name">{escape(str(r["name"]))}</span>'
            f'<span class="rank-pill">{escape(str(r["points"]))} 分</span>'
            "</div>"
        )
    tail = _quote_tail(quote)
    body = f'<div class="card-title">{escape(title)}</div>' + "".join(items) + tail
    return theme.card_shell(bg_data_uri=theme.bg_data_uri(bg), body=body)  # type: ignore[arg-type]


def _estimate_quote_height(quote: str | None) -> int:
    """估算引用区占用的像素高度（用于把视口撑够，避免长签名被裁掉）。

    卡片内容宽度约 472px、字号 19px、行高 1.65；按每行约 26 个全角字符估算。
    """
    if not quote or not quote.strip():
        return 0
    text = quote.strip()
    import unicodedata

    # 全角算 2 单位、半角 1 单位；每行约 52 单位
    units = sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1 for ch in text
    )
    lines = max(1, -(-units // 52))  # ceil
    return int(lines * 19 * 1.65) + 34  # 行高 + 分隔线/内边距


async def render_rank_card(
    rows: list[dict[str, Any]],
    *,
    title: str = "本群签到排行",
    quote: str | None = None,
    bg: object | None = None,
) -> bytes | None:
    """渲染排行卡片；失败返回 None（调用方回退纯文本）。

    视口高度 = 头部 + 每行 + **引用区实际所需高度**：固定值会让长签名被裁掉。
    """
    try:
        height = _RANK_VIEWPORT_H + 57 * len(rows) + _estimate_quote_height(quote)
        return await html_to_pic(
            _rank_html(rows, title=title, quote=quote, bg=bg),
            viewport={"width": 612, "height": height},
        )
    except Exception as exc:  # 渲染不可用不该让命令失败
        logger.warning(f"签到排行卡片渲染失败，回退纯文本: {exc!r}")
        return None


def build_rank_fallback_text(
    rows: list[dict[str, Any]], *, title: str = "本群签到排行"
) -> str:
    """排行纯文本回退：昵称 + 积分 + 连续天数（无头像）。"""
    lines = [title]
    lines += [
        f"{row['rank']}. {row['name']} · {row['points']} 分 · 连续 {row['streak']} 天"
        for row in rows
    ]
    return "\n".join(lines)


async def render_checkin_card(**kwargs: Any) -> bytes | None:
    """渲染签到卡片；失败返回 None（调用方回退纯文本）。"""
    try:
        html = _card_html(**kwargs)
        quote = kwargs.get("quote")
        height = _CARD_VIEWPORT_H + _estimate_quote_height(quote)
        return await html_to_pic(
            html, viewport={"width": _CARD_WIDTH, "height": height}
        )
    except Exception as exc:  # 渲染不可用不该让命令失败
        logger.warning(f"签到卡片渲染失败，回退纯文本: {exc!r}")
        return None


def build_fallback_text(
    *,
    title: str,
    nickname: str,
    points_gained: int,
    total_points: int,
    streak: int,
    rank: int | None,
    already: bool,
    **_ignored: object,
) -> str:
    """纯文本回退：信息与图卡等价（标题/本次/累计/连续/排名）。

    `**_ignored` 是必需的：调用方 `handle._send` 用 `**payload` 透传，
    而设计系统的 payload 还带 `quote` / `bg` / `avatar` 三个图卡专用键。
    不接受它们会让「渲染失败 → 回退纯文本」这条路径直接抛 TypeError。
    """
    lines = [f"{title}｜{nickname}"]
    lines.append("今天已经签过啦" if already else f"本次 +{points_gained} 分")
    lines.append(f"累计 {total_points} 分 · 连续 {streak} 天")
    if rank is not None:
        lines.append(f"本群排名 #{rank}")
    return "\n".join(lines)
