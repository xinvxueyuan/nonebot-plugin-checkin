"""出图：真渲染出 PNG；渲染异常回退；文本回退信息等价。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


async def test_rank_card_renders_png() -> None:
    from nonebot_plugin_checkin import render

    rows = [
        {"rank": 1, "name": "阿一", "points": 222, "streak": 6, "avatar_png": None},
        {"rank": 2, "name": "阿二", "points": 180, "streak": 3, "avatar_png": None},
    ]
    png = await render.render_rank_card(rows)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
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

    async def boom(*_a: object, **_kw: object) -> bytes:
        raise RuntimeError("browser 挂了")

    monkeypatch.setattr(render, "html_to_pic", boom)
    assert await render.render_checkin_card(**_payload()) is None  # type: ignore[arg-type]


def test_fallback_text_contains_key_numbers() -> None:
    from nonebot_plugin_checkin import render

    text = render.build_fallback_text(**_payload())  # type: ignore[arg-type]
    assert "签到成功" in text
    assert "+12" in text
    assert "222" in text
    assert "连续 6 天" in text
