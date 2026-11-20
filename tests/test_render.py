"""出图：真渲染出 PNG；渲染异常回退；文本回退信息等价。"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image
import pytest


def _payload() -> dict[str, object]:
    return {
        "title": "签到成功",
        "nickname": "测试昵称",
        "points_gained": 12,
        "total_points": 222,
        "streak": 6,
        "rank": 3,
        "already": False,
    }


def _rows() -> list[dict[str, Any]]:
    return [
        {"rank": 1, "name": "阿一", "points": 222, "streak": 6, "avatar_png": None},
        {"rank": 2, "name": "阿二", "points": 180, "streak": 3, "avatar_png": None},
    ]


async def test_rank_card_renders_png() -> None:
    from nonebot_plugin_checkin import render

    rows = [
        {"rank": 1, "name": "阿一", "points": 222, "streak": 6, "avatar_png": None},
        {"rank": 2, "name": "阿二", "points": 180, "streak": 3, "avatar_png": None},
    ]
    png = await render.render_rank_card(rows)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # 图卡必须印昵称（只印名次就认不出人）：直接钉住 HTML 里的名字，
    # 不靠 PNG 像素猜（像素级校验见 skill render-verification，这里守的是数据接线）。
    html = render._rank_html(rows, title="本群签到排行")
    assert "阿一" in html and "阿二" in html
    text = render.build_rank_fallback_text(rows)
    assert "阿一" in text and "222" in text


async def test_render_returns_png_bytes() -> None:
    from nonebot_plugin_checkin import render

    png = await render.render_checkin_card(**_payload())  # type: ignore[arg-type]
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000


async def test_render_falls_back_to_none_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_checkin import render

    class _BoomPage:
        """替身：进入 async with 时抛错（模拟浏览器起不来）。"""

        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        async def __aenter__(self) -> object:
            raise RuntimeError("browser 挂了")

        async def __aexit__(self, *_exc: object) -> None:
            return None

    # 替换渲染入口：浏览器启动失败时异常在 `async with` 处抛出，
    # 正好覆盖「渲染不可用 → None」这条真实路径。
    monkeypatch.setattr(render, "get_new_page", _BoomPage)
    assert await render.render_checkin_card(**_payload()) is None  # type: ignore[arg-type]
    assert await render.render_rank_card(_rows()) is None


# ── 高度精确性：PNG 像素高必须等于内容 CSS 高 × device_scale_factor ──
# 旧实现靠 `_CARD_VIEWPORT_H + _estimate_quote_height()` 猜视口：猜小裁字，
# 猜大就在底部漏出浏览器默认白底 —— 用户看到的「白边」。
# 这里钉死两条：① 高度差 ≤ 2px（1 个设备像素的栅格化余量）
# ② 最底一行不能整行纯白（那正是背景漏出来的样子）。

_DSF = 2
_QUOTES = [
    pytest.param(None, id="no-quote"),
    pytest.param("签名测试", id="short-quote"),
    pytest.param("签" * 120, id="long-quote"),
]


async def _content_css_height(html: str, *, width: int = 612) -> float:
    """独立量一次根容器 .page 的 CSS 高度（不经过 render 的实现）。"""
    from nonebot_plugin_htmlrender import get_new_page

    async with get_new_page(
        device_scale_factor=_DSF, viewport={"width": width, "height": 900}
    ) as page:
        await page.set_content(html, wait_until="networkidle")
        height = await page.evaluate(
            "() => document.querySelector('.page').getBoundingClientRect().height"
        )
        return float(height)


def _png_size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as im:
        return im.size


def _trailing_blank_rows(png: bytes) -> int:
    """从底部往上数「整行都是纯白」的行数 —— 就是白边的厚度。"""
    with Image.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        blank = 0
        for y in range(h - 1, -1, -1):
            # 任一通道 < 250 即视为「有内容」：不依赖 Pillow 的 getdata（已废弃）
            if min(rgb.crop((0, y, w, y + 1)).tobytes()) < 250:
                break
            blank += 1
        return blank


def _last_row_stats(png: bytes) -> tuple[int, float]:
    """末行的 (唯一色数, 纯白像素占比)。留白 → 唯一色 1、白占比 100%。"""
    with Image.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        raw = rgb.crop((0, h - 1, w, h)).tobytes()
    pixels = [tuple(raw[i : i + 3]) for i in range(0, len(raw), 3)]
    white = sum(1 for px in pixels if min(px) >= 250)
    return len(set(pixels)), white / len(pixels)


@pytest.mark.parametrize("quote", _QUOTES)
async def test_checkin_card_height_equals_content_height(quote: str | None) -> None:
    from nonebot_plugin_checkin import render

    kwargs = dict(_payload(), quote=quote)
    html = render._card_html(**kwargs)  # type: ignore[arg-type]
    content_css = await _content_css_height(html)
    png = await render.render_checkin_card(**kwargs)  # type: ignore[arg-type]
    assert png is not None
    width, height = _png_size(png)
    expected = content_css * _DSF
    assert width == 612 * _DSF  # 缩放生效：612 CSS 宽 → 1224 像素宽
    assert abs(height - expected) <= 2, (
        f"PNG 高 {height}px ≠ 内容高 {content_css:.2f}CSS × {_DSF} = {expected:.1f}px"
    )
    assert _trailing_blank_rows(png) == 0, "底部仍有整行纯白（背景漏出）"


@pytest.mark.parametrize("quote", _QUOTES)
async def test_rank_card_height_equals_content_height(quote: str | None) -> None:
    from nonebot_plugin_checkin import render

    rows = _rows()
    html = render._rank_html(rows, title="本群签到排行", quote=quote)
    content_css = await _content_css_height(html)
    png = await render.render_rank_card(rows, quote=quote)
    assert png is not None
    width, height = _png_size(png)
    expected = content_css * _DSF
    assert width == 612 * _DSF
    assert abs(height - expected) <= 2, (
        f"PNG 高 {height}px ≠ 内容高 {content_css:.2f}CSS × {_DSF} = {expected:.1f}px"
    )
    assert _trailing_blank_rows(png) == 0, "底部仍有整行纯白（背景漏出）"


@pytest.mark.parametrize("quote", _QUOTES)
async def test_card_bottom_row_is_content_not_blank(quote: str | None) -> None:
    """末行必须有内容（多色、非整行纯白）；只有圆角两侧可以是白的。"""
    from nonebot_plugin_checkin import render

    png = await render.render_checkin_card(**dict(_payload(), quote=quote))  # type: ignore[arg-type]
    assert png is not None
    colors, white_ratio = _last_row_stats(png)
    assert colors > 8, f"末行只有 {colors} 种颜色 —— 还是白条"
    assert white_ratio < 0.35, f"末行纯白像素占 {white_ratio:.1%} —— 还是白条"


async def test_long_quote_is_not_clipped() -> None:
    """超长签名（1000 字）必须整段进图：高度跟着内容涨，而不是被视口截断。

    旧实现按「每行 52 单位」估算，估小就裁字。这里用「PNG 高 ≈ 内容高 ×2」
    外加「1000 字比 120 字更高」双向钉住。
    """
    from nonebot_plugin_checkin import render

    short_q = "签" * 120
    long_q = "字" * 1000
    short_png = await render.render_checkin_card(**dict(_payload(), quote=short_q))  # type: ignore[arg-type]
    long_png = await render.render_checkin_card(**dict(_payload(), quote=long_q))  # type: ignore[arg-type]
    assert short_png is not None and long_png is not None
    short_h = _png_size(short_png)[1]
    long_h = _png_size(long_png)[1]
    expected = await _content_css_height(
        render._card_html(**dict(_payload(), quote=long_q))  # type: ignore[arg-type]
    )
    assert abs(long_h - expected * _DSF) <= 2, (
        f"超长签名 PNG 高 {long_h}px ≠ {expected * _DSF:.1f}px"
    )
    assert long_h > short_h + 1000, "1000 字签名没有把图撑高 —— 说明被裁掉了"


def test_fallback_text_contains_key_numbers() -> None:
    from nonebot_plugin_checkin import render

    text = render.build_fallback_text(**_payload())  # type: ignore[arg-type]
    assert "签到成功" in text
    assert "+12" in text
    assert "222" in text
    assert "连续 6 天" in text


def test_card_html_uses_design_system() -> None:
    from nonebot_plugin_checkin import render

    html = render._card_html(
        title="签到成功",
        nickname="新v学员",
        points_gained=12,
        total_points=222,
        streak=6,
        rank=3,
        already=False,
        quote=None,
        bg=None,
    )
    assert 'class="card"' in html and 'class="arc"' in html
    assert html.count('class="row"') == 5  # 昵称/今日/总积分/连续/排名
    assert 'class="divider"' not in html  # 无引用时不出分隔线


def test_card_html_has_divider_when_quote_present() -> None:
    from nonebot_plugin_checkin import render

    html = render._card_html(
        title="签到成功",
        nickname="A",
        points_gained=1,
        total_points=2,
        streak=1,
        rank=None,
        already=False,
        quote="人生的最后一课",
        bg=None,
    )
    assert 'class="divider"' in html
    assert "人生的最后一课" in html
    assert html.count('class="row"') == 4  # rank 为 None 时少一行


def test_card_html_hides_rank_row_when_none() -> None:
    from nonebot_plugin_checkin import render

    html = render._card_html(
        title="签到成功",
        nickname="A",
        points_gained=1,
        total_points=2,
        streak=1,
        rank=None,
        already=False,
        quote=None,
        bg=None,
    )
    assert "本群排名" not in html


def test_rank_html_uses_design_system() -> None:
    from nonebot_plugin_checkin import render

    rows = [
        {
            "rank": i,
            "name": f"用户{i}",
            "points": 100 - i,
            "streak": i,
            "avatar_png": None,
        }
        for i in range(1, 4)
    ]
    html = render._rank_html(rows, title="本群签到排行")
    assert 'class="card"' in html and 'class="arc"' in html
    assert html.count('class="rank-row"') == 3
