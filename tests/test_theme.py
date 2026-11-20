import io
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw
import pytest

from nonebot_plugin_checkin import theme

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"0" * 100


# ── 对比度模型：把 CSS 的叠层顺序在纯函数里复现一遍 ──
# 「照片 → 染色层 → 卡体」三层合成，再算 WCAG 相对亮度比。用真实 token 值算，
# 而不是抄一份常数：改 margin 上任何一个 alpha / 颜色，这组断言就会跟着红。


def _parse_color(css: str) -> tuple[tuple[float, float, float], float]:
    """解析 `#rrggbb` / `rgba(r, g, b, a)` → ((r, g, b), alpha)。"""
    css = css.strip()
    if css.startswith("#"):
        h = css[1:]
        return (
            float(int(h[0:2], 16)),
            float(int(h[2:4], 16)),
            float(int(h[4:6], 16)),
        ), 1.0
    m = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
        r"\s*(?:,\s*([\d.]+)\s*)?\)",
        css,
    )
    assert m, f"认不出的颜色写法: {css}"
    rgb = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    return rgb, alpha


def _blend(
    top_css: str, under: tuple[float, ...], *, coverage: float = 1.0
) -> tuple[float, ...]:
    """把 `top_css` 半透明层叠在 `under` 上（source-over，不含 backdrop blur）。

    `coverage` 是这层的**实际覆盖率**（1.0 = 完整矩形铺满）。底片是矩形，取 1.0；
    文字描边只铺在字形周围，覆盖率按实测校准（见 `_HALO_COVERAGE`）。
    """
    (r, g, b), a = _parse_color(top_css)
    a *= coverage
    return tuple(a * c + (1.0 - a) * u for c, u in zip((r, g, b), under, strict=True))


def contrast_ratio(fg_rgb: tuple[float, ...], bg_rgb: tuple[float, ...]) -> float:
    """WCAG 2.x 对比度：(L_亮 + 0.05) / (L_暗 + 0.05)，范围 1..21。"""

    def _lin(channel: float) -> float:
        c = channel / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def _lum(rgb: tuple[float, ...]) -> float:
        r, g, b = (_lin(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((_lum(fg_rgb), _lum(bg_rgb)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


#: 两种最坏情况背景：纯黑照片（卡体最暗 → 深色字最难读）与中亮照片。
_WORST_PHOTOS = {"纯黑照片": (20.0, 20.0, 20.0), "中亮照片": (130.0, 110.0, 120.0)}


def _card_bg(photo: tuple[float, ...]) -> tuple[float, ...]:
    """卡片内部的实际底色：照片 → 染色层 → 卡体（与 CSS 叠层顺序一致）。"""
    return _blend(theme.C_ACRYLIC, _blend(theme.C_PAGE_TINT, photo))


#: 描边光晕的**实际覆盖率**：`text-shadow` 只铺在字形外圈，不是整块矩形。
#: 0.74 由真渲染反推得出（黑底照片上 label 纸面 150 / 卡体 78，halo alpha 0.55 →
#: 0.55·c·(255−78) = 150−78 ⇒ c ≈ 0.74）。写死在模型里是为了让纯函数模型**不虚高**：
#: 拿它算出的对比度与真渲染实测值相差 < 2%。
_HALO_COVERAGE = 0.74


def _label_bg(photo: tuple[float, ...]) -> tuple[float, ...]:
    """Label 周围的实际底色：卡体 + 文字自身的描边光晕。"""
    return _blend(theme.C_TEXT_HALO, _card_bg(photo), coverage=_HALO_COVERAGE)


def _quote_bg(photo: tuple[float, ...]) -> tuple[float, ...]:
    """Quote 周围的实际底色：卡体 + 引用底片。

    只算底片、**不给描边记功** —— 描边只会更亮，漏算它是保守方向。
    """
    return _blend(theme.C_QUOTE_PLATE, _card_bg(photo))


def test_contrast_ratio_matches_wcag_reference() -> None:
    """公式自检：黑白 21:1、同色 1:1（先证明量尺本身是对的）。"""
    white, black = (255.0, 255.0, 255.0), (0.0, 0.0, 0.0)
    assert contrast_ratio(black, white) == pytest.approx(21.0)
    assert contrast_ratio(black, black) == pytest.approx(1.0)
    assert contrast_ratio(white, white) == pytest.approx(1.0)


@pytest.mark.parametrize("photo_name", list(_WORST_PHOTOS))
def test_text_readable_without_strong_veil(photo_name: str) -> None:
    """换轴后的硬指标：两种最坏照片上 label / quote 都要 >= 3.0（25px 粗体按大字 AA）。

    这条是「可读性由文字自身承担」的账：底色只剩薄薄一层霜，靠 label 的描边光晕、
    quote 的底片 + 更暗的引用色顶住对比度。
    """
    photo = _WORST_PHOTOS[photo_name]
    label = contrast_ratio(_parse_color(theme.C_LABEL)[0], _label_bg(photo))
    quote = contrast_ratio(_parse_color(theme.C_QUOTE)[0], _quote_bg(photo))
    assert label >= 3.0, f"{photo_name}: label 对比 {label:.2f} < 3.0"
    assert quote >= 3.0, f"{photo_name}: quote 对比 {quote:.2f} < 3.0"


def test_readability_comes_from_text_not_from_veil() -> None:
    """反向锁：只看卡体遮罩（不记文字自身的账）时，最坏照片必须**不达标**。

    否则「把卡体调回厚白纱」也能让上一条绿 —— 那是老路，用户已经否掉了。
    与 `test_background_visibility_at_least_double_baseline` 一起把两个方向都钉死：
    遮罩必须薄（可见度），可读性必须由文字自己扛（这条）。
    """
    raw = _card_bg(_WORST_PHOTOS["纯黑照片"])
    assert contrast_ratio(_parse_color(theme.C_LABEL)[0], raw) < 3.0
    assert contrast_ratio(_parse_color(theme.C_QUOTE)[0], raw) < 3.0


def test_card_veil_is_a_thin_single_knob() -> None:
    """卡体只留一层薄霜：alpha 必须显著低于旧值 0.55（「遮罩强度」是唯一变量）。"""
    assert _parse_color(theme.C_ACRYLIC)[1] <= 0.25, "卡体遮罩仍然过厚"
    assert _parse_color(theme.C_PAGE_TINT)[1] <= 0.15, "染色层仍然过厚"


def test_base_css_rebuilds_from_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """BASE_CSS 不能是 import 时固化的死常量：改 token 后重建必须生效。"""
    before = theme.build_css()
    assert theme.C_ACRYLIC in before
    monkeypatch.setattr(theme, "C_ACRYLIC", "rgba(1, 2, 3, 0.44)")
    after = theme.build_css()
    assert "rgba(1, 2, 3, 0.44)" in after, "改 token 后 CSS 没变 —— 又是模块级固化了"
    assert before != after
    # 兼容名 BASE_CSS 必须与当前 token 一致（模块导入时的快照）
    assert before == theme.BASE_CSS


def _rule(css: str, selector: str) -> str:
    """取出 `selector { ... }` 的声明块（测试用，够用就行）。"""
    start = css.index(selector + " {")
    end = css.index("}", start)
    return css[start:end]


def test_css_uses_tokens_not_hardcoded_alpha() -> None:
    """Label / quote 各自必须带描边，且引用色比旧的 #8a8a8a 更暗。"""
    css = theme.BASE_CSS
    for selector in (".label", ".quote"):
        rule = _rule(css, selector)
        assert rule, f"{selector} 规则没找到"
        assert "text-shadow" in rule, f"{selector} 缺文字描边"
        assert theme.C_TEXT_HALO in rule, f"{selector} 的描边没用 C_TEXT_HALO token"
    assert theme.C_QUOTE_PLATE in _rule(css, ".quote"), "引用区没有半透明底片"
    quote_rgb = _parse_color(theme.C_QUOTE)[0]
    assert sum(quote_rgb) / 3 < 0x8A, "引用色没有变暗"


def test_base_css_has_design_tokens() -> None:
    css = theme.BASE_CSS
    assert "border-radius" in css
    for token in [
        theme.C_ACRYLIC,
        theme.C_ARC,
        theme.C_LABEL,
        theme.C_QUOTE,
        theme.C_QUOTE_PLATE,
        "italic",
    ]:
        assert token in css, f"缺少设计 token {token}"


def test_base_css_is_translucent_material() -> None:
    """半透光两要素：半透卡体 + backdrop-filter 模糊（不要噪声层）。"""
    css = theme.BASE_CSS
    assert "backdrop-filter" in css, "缺 backdrop-filter（半透光的核心）"
    assert f"blur({theme.BLUR_PX}px)" in css, "模糊值缺失"
    assert "saturate(" in css, "缺少饱和增强"
    assert theme.C_ACRYLIC in css, "卡体应是半透明白"
    # 必须有不支持 backdrop-filter 时的兜底
    assert "@supports" in css, "缺 @supports 兜底分支"
    assert theme.C_ACRYLIC_SOLID in css, "缺不透明兜底"
    # 噪声层已按用户要求撤销
    assert "feTurbulence" not in css, "噪声层应已移除"


def test_card_shell_without_bg_uses_gradient() -> None:
    html = theme.card_shell(bg_data_uri=None, body="<div>X</div>")
    assert "linear-gradient" in html
    assert "url('data:" not in html


def test_page_background_tints_photo() -> None:
    """有图时必须叠一层暖白染色，否则半透亚克力上的深色文字会糊。"""
    css = theme.page_background_css("data:image/webp;base64,AAAA")
    assert "linear-gradient(" in css, "缺染色层"
    assert theme.C_PAGE_TINT in css
    assert "url('data:image/webp;base64,AAAA')" in css


def test_card_shell_with_bg_embeds_data_uri() -> None:
    html = theme.card_shell(
        bg_data_uri="data:image/webp;base64,AAAA", body="<div>X</div>"
    )
    assert "data:image/webp;base64,AAAA" in html


def test_row_renders_label_and_value() -> None:
    html = theme.row("昵称", "新v学员")
    assert "昵称" in html and "新v学员" in html
    assert 'class="value"' in html


def test_row_escapes_html() -> None:
    html = theme.row("昵称", "<script>x</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_quote_hidden_when_empty() -> None:
    assert theme.quote_block("") == ""
    assert theme.quote_block("   ") == ""
    assert theme.quote_block(None) == ""


def test_quote_renders_with_escape() -> None:
    html = theme.quote_block('人生的最后一课"学会离别"')
    assert "人生的最后一课" in html
    assert "&quot;" in html


def test_avatar_block_embeds_base64() -> None:
    html = theme.avatar_block(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    assert "data:image/png;base64," in html


def test_avatar_block_falls_back_to_placeholder() -> None:
    html = theme.avatar_block(None)
    assert "placeholder" in html


def test_avatar_block_jpeg_uses_jpeg_mime() -> None:
    """Qlogo 回 JPEG 时 data URI 必须是 image/jpeg（写死 png 就画不出）。"""
    html = theme.avatar_block(JPEG)
    assert "data:image/jpeg;base64," in html
    assert "image/png" not in html


def test_avatar_block_png_uses_png_mime() -> None:
    html = theme.avatar_block(PNG)
    assert "data:image/png;base64," in html
    assert "image/jpeg" not in html


def test_avatar_mime_sniffs_bytes() -> None:
    """Mime 只看字节：PNG/JPEG 认得出，其它一律 None（由调用方决定怎么兜底）。"""
    assert theme.avatar_mime(PNG) == "image/png"
    assert theme.avatar_mime(JPEG) == "image/jpeg"
    assert theme.avatar_mime(b"GIF89a" + b"0" * 8) is None
    assert theme.avatar_mime(b"") is None


def test_rank_card_rows_use_real_avatar_mime() -> None:
    """排行卡的头像也是 data URI：那里写死 image/png 同样画不出 JPEG。

    断言放在本文件（而不是 test_render.py）是为了让「头像 mime」这一条缺陷的
    回归测试集中在一处：凡是「头像字节 → data URI」的路径都在这里守。
    """
    from nonebot_plugin_checkin import render

    rows = [
        {"rank": 1, "name": "甲", "points": 3, "streak": 1, "avatar_png": JPEG},
        {"rank": 2, "name": "乙", "points": 2, "streak": 1, "avatar_png": PNG},
        {"rank": 3, "name": "丙", "points": 1, "streak": 1, "avatar_png": None},
    ]
    html = render._rank_html(rows, title="排行")
    assert "data:image/jpeg;base64," in html
    assert "data:image/png;base64," in html
    assert html.count('class="rank-avatar"') == 3


def test_bg_data_uri_from_bytes() -> None:
    uri = theme.bg_data_uri(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 100)
    assert uri is not None
    assert uri.startswith("data:image/webp;base64,")


def test_bg_data_uri_from_path(tmp_path) -> None:
    p = tmp_path / "x.webp"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 100)
    uri = theme.bg_data_uri(p)
    assert uri is not None and "webp" in uri


def test_bg_data_uri_missing_returns_none(tmp_path) -> None:
    assert theme.bg_data_uri(None) is None
    assert theme.bg_data_uri(tmp_path / "nope.webp") is None
    assert theme.bg_data_uri(b"") is None


# ── 真渲染：背景可见度必须相对旧配方翻倍 ──
# 用户的原话是「看不清背景」。这个指标只能靠**真出图**量，纯函数推定不算：
# 在高对比色块背景上出图，量卡片左内边距区（x=58..104）的 RGB 标准差均值 ——
# 遮罩越薄，背景的色块边界越能透出来，标准差越大。
# 同一把尺子（真 `_card_html` + 2x3 色块）：旧配方 23.5 → 新配方 68.8。

_BASELINE_VISIBILITY = 23.5  # 同量法旧配方实测；父代理另一量法测得 19.4
_VISIBILITY_TARGET = 39.0  # 相对 19.4 翻倍 ≈ 39


def _block_bg_png(tmp_path: Path) -> Path:
    """六块高对比色块背景：白/黑/红/绿/蓝/黄各一块，卡内每个采样区都能跨到边界。"""
    img = Image.new("RGB", (1224, 1600))
    draw = ImageDraw.Draw(img)
    colors = [
        (250, 250, 250),
        (20, 20, 20),
        (220, 40, 40),
        (40, 180, 60),
        (40, 80, 220),
        (240, 210, 50),
    ]
    bw, bh = img.width // 2, img.height // 3
    for i, color in enumerate(colors):
        r, c = divmod(i, 2)
        draw.rectangle([c * bw, r * bh, (c + 1) * bw, (r + 1) * bh], fill=color)
    path = tmp_path / "blocks.png"
    img.save(path, "PNG")
    return path


def _rgb_stddev(png: bytes) -> float:
    """卡片左内边距区（x=58..104, y=220..h-220）三通道标准差的均值。"""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    samples: list[tuple[int, int, int]] = []
    for y in range(220, max(221, img.height - 220), 18):
        samples.extend(
            img.getpixel((x, y))  # type: ignore[arg-type]
            for x in range(58, 105, 3)
        )
    assert samples
    n = len(samples)
    means = [sum(s[i] for s in samples) / n for i in range(3)]
    stds = [
        math.sqrt(sum((s[i] - means[i]) ** 2 for s in samples) / n) for i in range(3)
    ]
    return sum(stds) / 3


async def test_background_visibility_at_least_double_baseline(tmp_path: Path) -> None:
    """真渲染量背景可见度：新配方必须 >= 39（旧配方同量法 14.3~19.4）。

    用**真实签到卡**（`render._card_html`，五行 + 引用）出图，不是拼一个缩水 body：
    卡片高度会改变采样带覆盖的色块数量，缩水 body 会把可见度算低。
    """
    from nonebot_plugin_checkin import render

    # 注意传**原始 PNG 路径**：`_card_html` 内部会调 `theme.bg_data_uri(bg)`
    # 转 data URI；传已转好的 data URI 字符串会被当成文件路径 → 静默回退渐变色。
    bg_path = _block_bg_png(tmp_path)
    html = render._card_html(
        title="签到成功",
        nickname="测试昵称",
        points_gained=12,
        total_points=222,
        streak=6,
        rank=3,
        already=False,
        quote="人生的最后一课，是学会离别。",
        bg=bg_path,
        avatar=None,
    )
    assert "data:image/png;base64," in html, "背景图没进 HTML（量尺会量到渐变兜底）"
    png = await render._screenshot_content(html)
    got = _rgb_stddev(png)
    assert got >= _VISIBILITY_TARGET, (
        f"背景可见度 {got:.1f} < {_VISIBILITY_TARGET}（旧配方 {_BASELINE_VISIBILITY}）"
    )
