from nonebot_plugin_checkin import theme


def test_base_css_has_design_tokens() -> None:
    css = theme.BASE_CSS
    assert "border-radius" in css
    for token in ["#ffffff", "#cfe8f7", "#f4f4f4", "#3c3c3c", "#8a8a8a", "italic"]:
        assert token in css, f"缺少设计 token {token}"


def test_card_shell_without_bg_uses_gradient() -> None:
    html = theme.card_shell(bg_data_uri=None, body="<div>X</div>")
    assert "linear-gradient" in html
    assert "data:image" not in html


def test_card_shell_with_bg_embeds_data_uri() -> None:
    html = theme.card_shell(bg_data_uri="data:image/webp;base64,AAAA", body="<div>X</div>")
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
