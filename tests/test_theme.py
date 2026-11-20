from nonebot_plugin_checkin import theme

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"0" * 100


def test_base_css_has_design_tokens() -> None:
    css = theme.BASE_CSS
    assert "border-radius" in css
    for token in [
        "rgba(255, 255, 255, 0.55)",
        "#cfe8f7",
        "#3c3c3c",
        "#8a8a8a",
        "italic",
    ]:
        assert token in css, f"缺少设计 token {token}"


def test_base_css_is_translucent_material() -> None:
    """半透光两要素：半透卡体 + backdrop-filter 模糊（不要噪声层）。"""
    css = theme.BASE_CSS
    assert "backdrop-filter" in css, "缺 backdrop-filter（半透光的核心）"
    assert f"blur({theme.BLUR_PX}px)" in css, "模糊值缺失"
    assert "saturate(" in css, "缺少饱和增强"
    assert "rgba(255, 255, 255, 0.55)" in css, "卡体应是半透明白"
    # 必须有不支持 backdrop-filter 时的兜底
    assert "@supports" in css, "缺 @supports 兜底分支"
    assert "rgba(255, 255, 255, 0.90)" in css, "缺不透明兜底"
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
