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

logger = logging.getLogger("nonebot_plugin_checkin")

_CARD_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 520px; background: #f8fafc; }
.card { margin: 16px; padding: 24px; border-radius: 20px; background: #fff;
        border: 1px solid #e2e8f0;
        font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; }
.title { font-size: 26px; font-weight: 700; color: #0f172a; }
.name { margin-top: 6px; font-size: 15px; color: #64748b; }
.big { margin-top: 18px; font-size: 48px; font-weight: 800; color: #db2777; }
.big small { font-size: 20px; color: #94a3b8; font-weight: 600; }
.rows { margin-top: 18px; display: flex; gap: 12px; }
.row { flex: 1; padding: 12px; border-radius: 14px; background: #f1f5f9; }
.row b { display: block; font-size: 20px; color: #0f172a; }
.row span { font-size: 12px; color: #64748b; }
.done { margin-top: 16px; font-size: 14px; color: #64748b; }
.avatar { width: 40px; height: 40px; border-radius: 50%; vertical-align: middle;
          margin-right: 10px; background: #e2e8f0; }
"""

_RANK_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 560px; background: #f8fafc; }
.card { margin: 16px; padding: 20px 22px; border-radius: 20px; background: #fff;
        border: 1px solid #e2e8f0;
        font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; }
.title { font-size: 22px; font-weight: 700; color: #0f172a; margin-bottom: 14px; }
.rk { display: flex; align-items: center; gap: 10px; padding: 10px 12px;
      border-radius: 14px; background: #f8fafc; margin-top: 8px; }
.idx { width: 42px; font-size: 18px; font-weight: 800; color: #db2777; }
.nm { flex: 1; font-size: 17px; color: #0f172a; overflow: hidden;
      white-space: nowrap; text-overflow: ellipsis; }
.pt { width: 96px; text-align: right; font-size: 17px; font-weight: 700;
      color: #0f172a; }
.st { width: 96px; text-align: right; font-size: 13px; color: #64748b; }
"""


def _card_html(
    *,
    title: str,
    nickname: str,
    points_gained: int,
    total_points: int,
    streak: int,
    rank: int | None,
    already: bool,
) -> str:
    rank_row = (
        f'<div class="row"><b>#{rank}</b><span>本群排名</span></div>'
        if rank is not None
        else ""
    )
    gained = "已签过" if already else f"+{points_gained}"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CARD_CSS}</style></head><body><div class="card">
  <div class="title">{escape(title)}</div>
  <div class="name">{escape(nickname)}</div>
  <div class="big">{gained} <small>分</small></div>
  <div class="rows">
    <div class="row"><b>{total_points}</b><span>累计积分</span></div>
    <div class="row"><b>连续 {streak} 天</b><span>签到连续</span></div>
    {rank_row}
  </div>
</div></body></html>"""


def _avatar_tag(avatar_png: bytes | None) -> str:
    """头像 tag：有 PNG 就内联 data URI，没有就空串（不占位、不破图）。"""
    if not avatar_png:
        return ""
    b64 = base64.b64encode(avatar_png).decode()
    return f'<img class="avatar" src="data:image/png;base64,{b64}">'


def _rank_html(rows: list[dict[str, Any]], *, title: str) -> str:
    """排行卡：头像 + 昵称 + 积分 + 连续天数，一行一人。"""
    items = [
        f'<div class="rk"><span class="idx">#{row["rank"]}</span>'
        f"{_avatar_tag(row.get('avatar_png'))}"
        f'<span class="nm">{escape(str(row["name"]))}</span>'
        f'<span class="pt">{row["points"]} 分</span>'
        f'<span class="st">连续 {row["streak"]} 天</span></div>'
        for row in rows
    ]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_RANK_CSS}</style></head><body><div class="card">
  <div class="title">{escape(title)}</div>
  {"".join(items)}
</div></body></html>"""


async def render_rank_card(
    rows: list[dict[str, Any]], *, title: str = "本群签到排行"
) -> bytes | None:
    """渲染排行卡片；失败返回 None（调用方回退纯文本）。"""
    try:
        return await html_to_pic(
            _rank_html(rows, title=title),
            viewport={"width": 560, "height": 120 + 64 * len(rows)},
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
        return await html_to_pic(html, viewport={"width": 520, "height": 360})
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
) -> str:
    """纯文本回退：信息与图卡等价（标题/本次/累计/连续/排名）。"""
    lines = [f"{title}｜{nickname}"]
    lines.append("今天已经签过啦" if already else f"本次 +{points_gained} 分")
    lines.append(f"累计 {total_points} 分 · 连续 {streak} 天")
    if rank is not None:
        lines.append(f"本群排名 #{rank}")
    return "\n".join(lines)
