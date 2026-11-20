"""出图：签到结果卡片与排行图卡（htmlrender）；任何异常回退 None，由命令层发纯文本。

截图高度**不靠估算**：先量根容器 `.page` 的真实 CSS 尺寸，再按该尺寸精确裁切
（详见 `_screenshot_content`）。`device_scale_factor=2` 因此像素高 = CSS 高 × 2。
"""

from __future__ import annotations

import base64
from html import escape
import logging
import math
from typing import Any

from nonebot import require

# htmlrender 在导入时就会向 localstore 要目录（靠调用栈识别插件），
# 显式 require 既保证依赖先加载，也让非「插件加载」方式（pytest 直接 import）不报
# `Cannot detect caller plugin`。
require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import get_new_page

from . import theme

logger = logging.getLogger("nonebot_plugin_checkin")

_CARD_WIDTH = 612  # CSS 宽度（像素宽 = 612 × device_scale_factor）
_DEVICE_SCALE_FACTOR = 2  # 像素高 = CSS 高 × 该值，两者不可混用
_MEASURE_VIEWPORT_H = 900  # 仅量高用的初始视口；截图按内容裁切，不受它影响
_SCREENSHOT_TIMEOUT_MS = 30_000  # 与 html_to_pic 的 screenshot_timeout 默认值一致

#: 量根容器真实尺寸（CSS px）。取不到就是结构坏了 → 抛错让上层回退纯文本。
_MEASURE_JS = """
() => {
  const root = document.querySelector('.page');
  if (!root) throw new Error('缺少根容器 .page');
  const rect = root.getBoundingClientRect();
  return { width: rect.width, height: rect.height };
}
"""

#: 把根容器撑到「对齐后的裁切高度」：否则多出的半个设备像素落在元素外，
#: 仍会在 PNG 最后一行留下一条浏览器默认白底。
#: 只钉高度 —— 钉宽度会改变换行（`box-sizing: border-box` 下 padding 会挤压内容），
#: 宽度靠 clip 向上取整即可。
_PIN_HEIGHT_JS = """
(height) => {
  const root = document.querySelector('.page');
  root.style.height = height + 'px';
}
"""


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
            # mime 必须按字节嗅：qlogo 会返回 JPEG，写死 image/png 会让 <img> 解码失败。
            mime = theme.avatar_mime(av) or "image/png"
            img = (
                f'<img class="rank-avatar" src="data:{mime};base64,'
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


def _ceil_to_device_pixel(css_px: float) -> float:
    """把 CSS 长度向上取整到整设备像素（dsf=2 时对齐到 0.5 CSS px）。

    宁可多 0.5 CSS px 也不裁掉内容；多出来的部分由 `_PIN_HEIGHT_JS` 撑进容器内，
    不会露出页面背景。
    """
    return math.ceil(css_px * _DEVICE_SCALE_FACTOR) / _DEVICE_SCALE_FACTOR


async def _screenshot_content(html: str) -> bytes:
    """按根容器 `.page` 的真实尺寸精确截出 PNG（像素高 = CSS 高 × dsf）。

    为什么不用 `html_to_pic(full_page=True)`：它的截图高度是
    `max(视口高度, 内容高度)`，而 0.6.7 的 `html_to_pic` 又没有 viewport 参数
    （`viewport=` 会经 `**kwargs` 落到 `browser.new_page`，不控制截图高度）。
    于是「视口高度」只能靠常数 + 估算撑，估大就在底部漏出浏览器默认白底。

    这里改成三步：量 → 对齐 → 裁。
      ① `getBoundingClientRect()` 量 `.page`（与排版同口径，不含估算）；
      ② 向上对齐到整设备像素，并把容器**显式**撑到该尺寸
         （否则半个设备像素落在元素外，PNG 末行仍是白的）；
      ③ `clip` 到该尺寸截图，`full_page=True` 才能让 clip 突破视口高度。
    """
    async with get_new_page(
        device_scale_factor=_DEVICE_SCALE_FACTOR,
        viewport={"width": _CARD_WIDTH, "height": _MEASURE_VIEWPORT_H},
    ) as page:
        await page.set_content(html, wait_until="networkidle")
        measured = await page.evaluate(_MEASURE_JS)
        width = _ceil_to_device_pixel(float(measured["width"]))
        height = _ceil_to_device_pixel(float(measured["height"]))
        await page.evaluate(_PIN_HEIGHT_JS, height)
        return await page.screenshot(
            clip={"x": 0, "y": 0, "width": width, "height": height},
            full_page=True,
            type="png",
            timeout=_SCREENSHOT_TIMEOUT_MS,
        )


async def render_rank_card(
    rows: list[dict[str, Any]],
    *,
    title: str = "本群签到排行",
    quote: str | None = None,
    bg: object | None = None,
) -> bytes | None:
    """渲染排行卡片；失败返回 None（调用方回退纯文本）。"""
    try:
        return await _screenshot_content(
            _rank_html(rows, title=title, quote=quote, bg=bg)
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
        return await _screenshot_content(_card_html(**kwargs))
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
