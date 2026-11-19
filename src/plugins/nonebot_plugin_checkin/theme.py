"""设计系统：插画背景 + 白色大圆角卡片 + 左粗体标签/右浅灰胶囊值 + 分隔线 + 斜体引用。

两张卡（签到 / 排行）共用同一套 token 与骨架，只换 body 内容。
所有注入文本一律 escape，样式集中在 BASE_CSS，避免各卡重复。
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

# ── 设计 token（改造外观只调这里）──
C_PAGE_BG = "linear-gradient(135deg, #fdf6f3 0%, #f7e9e4 45%, #fdf1e7 100%)"
C_CARD = "#ffffff"
C_ARC = "#cfe8f7"
C_LABEL = "#3c3c3c"
C_VALUE_BG = "#f4f4f4"
C_VALUE_FG = "#4a4a4a"
C_QUOTE = "#8a8a8a"
C_DIVIDER = "#e8e8e8"

BASE_CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ background: transparent; }}
body {{
  font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif;
  display: inline-block;
}}
.page {{
  position: relative;
  padding: 26px;
  background: {C_PAGE_BG};
  background-size: cover;
  background-position: center;
  border-radius: 44px;
  overflow: hidden;
}}
.card {{
  position: relative;
  width: 560px;
  background: {C_CARD};
  border-radius: 40px;
  padding: 40px 44px 30px;
  box-shadow: 0 10px 30px rgba(120, 90, 80, 0.10);
  overflow: hidden;
}}
.arc {{
  position: absolute;
  top: -46px; left: -46px;
  width: 190px; height: 190px;
  border-radius: 50%;
  background: {C_ARC};
  opacity: 0.75;
}}
.avatar-wrap {{ position: relative; text-align: center; margin: 6px 0 22px; }}
.avatar {{
  width: 116px; height: 116px;
  border-radius: 50%;
  border: 5px solid #ffffff;
  box-shadow: 0 4px 14px rgba(90, 70, 70, 0.18);
  object-fit: cover;
  background: #eef2f6;
}}
.avatar.placeholder {{ display: inline-block; }}
.rows {{ position: relative; margin-top: 6px; }}
.row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 0;
}}
.label {{ font-size: 25px; font-weight: 700; color: {C_LABEL}; letter-spacing: 1px; }}
.value {{
  font-size: 22px;
  color: {C_VALUE_FG};
  background: {C_VALUE_BG};
  border-radius: 999px;
  padding: 7px 20px;
  max-width: 62%;
  text-align: right;
  word-break: break-all;
}}
.divider {{
  height: 1px;
  background: {C_DIVIDER};
  margin: 18px 6px 14px;
}}
.quote {{
  font-size: 19px;
  font-style: italic;
  color: {C_QUOTE};
  line-height: 1.65;
  text-align: center;
  padding: 0 8px 4px;
  word-break: break-word;
}}
.rank-row {{
  display: flex; align-items: center; gap: 14px;
  padding: 9px 4px;
  border-bottom: 1px solid #f1f1f1;
}}
.rank-row:last-child {{ border-bottom: none; }}
.rank-no {{
  width: 34px; text-align: center;
  font-size: 21px; font-weight: 700; color: {C_LABEL};
}}
.rank-avatar {{
  width: 38px; height: 38px; border-radius: 50%;
  border: 2px solid #ffffff;
  box-shadow: 0 2px 6px rgba(90, 70, 70, 0.14);
  object-fit: cover; background: #eef2f6;
}}
.rank-name {{ flex: 1; font-size: 20px; color: {C_LABEL}; overflow: hidden;
              text-overflow: ellipsis; white-space: nowrap; }}
.rank-pill {{
  font-size: 18px; color: {C_VALUE_FG};
  background: {C_VALUE_BG}; border-radius: 999px; padding: 5px 15px;
}}
.card-title {{ position: relative; font-size: 21px; font-weight: 700; color: {C_LABEL};
               text-align: center; margin-bottom: 14px; }}
"""


def card_shell(*, bg_data_uri: str | None, body: str) -> str:
    """整卡外壳。无背景图时用 CSS 渐变兜底。"""
    page_style = (
        f" style=\"background-image:url('{bg_data_uri}');\"" if bg_data_uri else ""
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{BASE_CSS}</style></head><body>"
        f'<div class="page"{page_style}><div class="card"><div class="arc"></div>'
        f"{body}"
        "</div></div></body></html>"
    )


def avatar_block(png: bytes | None) -> str:
    """圆形头像；无头像时渲染同尺寸占位。"""
    if not png:
        return (
            '<div class="avatar-wrap">'
            '<span class="avatar placeholder" title="avatar placeholder"></span>'
            "</div>"
        )
    b64 = base64.b64encode(png).decode()
    return (
        f'<div class="avatar-wrap"><img class="avatar" '
        f'src="data:image/png;base64,{b64}"/></div>'
    )


def row(label: str, value: str) -> str:
    """一行「左粗体标签 / 右浅灰胶囊值」。"""
    return (
        f'<div class="row"><span class="label">{escape(label)}</span>'
        f'<span class="value">{escape(value)}</span></div>'
    )


def divider() -> str:
    """细横分隔线。"""
    return '<div class="divider"></div>'


def quote_block(text: str | None) -> str:
    """底部斜体引用；空文本整块省略。"""
    if not text or not text.strip():
        return ""
    return f'<div class="quote">{escape(text.strip())}</div>'


def bg_data_uri(path_or_bytes: bytes | Path | str | None) -> str | None:
    """把背景图（bytes 或路径）转成 data URI；拿不到返回 None。"""
    if path_or_bytes is None:
        return None
    try:
        if isinstance(path_or_bytes, bytes):
            data = path_or_bytes
        else:
            data = Path(path_or_bytes).read_bytes()
    except OSError:
        return None
    if not data:
        return None
    if data.startswith(b"\x89PNG"):
        mime = "image/png"
    elif data.startswith(b"RIFF"):
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
