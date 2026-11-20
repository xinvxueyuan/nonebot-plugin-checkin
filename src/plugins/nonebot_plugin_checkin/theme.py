"""设计系统：半透光（glass / acrylic-lite）材质卡片。

材质配方（去掉噪声颗粒，只保半透光）：
  ① 底层：照片 + 暖白染色层（压亮照片，保证半透卡上的深色文字可读）
  ② 卡片：半透明白 + backdrop-filter: blur(40px) saturate(180%)（磨砂透光）
  ③ 边缘：1px 高光描边 + 双层外阴影 + 内侧顶部高光（玻璃厚度感）

不支持 backdrop-filter 的渲染器会退回 90% 不透明的近白卡，保证可读性。

两张卡（签到 / 排行）共用同一套 token 与骨架，只换 body 内容。
所有注入文本一律 escape，样式集中在 BASE_CSS，避免各卡重复。
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

# ── 半透光材质 token（改材质只调这里）──
C_ACRYLIC = "rgba(255, 255, 255, 0.55)"  # 半透明卡体（支持 backdrop-filter 时）
C_ACRYLIC_SOLID = "rgba(255, 255, 255, 0.90)"  # 兜底：不支持模糊时更实
C_ACRYLIC_BORDER = "rgba(255, 255, 255, 0.72)"  # 高光描边
C_PAGE_TINT = "rgba(252, 248, 245, 0.42)"  # 照片上的暖白染色层
C_PAGE_BG = "linear-gradient(135deg, #fdf6f3 0%, #f7e9e4 45%, #fdf1e7 100%)"  # 无图兜底
C_ARC = "#cfe8f7"
C_LABEL = "#3c3c3c"
C_VALUE_BG = "rgba(255, 255, 255, 0.62)"  # 玻璃胶囊
C_VALUE_BORDER = "rgba(0, 0, 0, 0.05)"
C_VALUE_FG = "#4a4a4a"
C_QUOTE = "#8a8a8a"
C_DIVIDER = "rgba(0, 0, 0, 0.07)"
BLUR_PX = 40
SATURATE = "180%"

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
  border-radius: 44px;
  overflow: hidden;
  background-color: #f7e9e4;
  background-size: cover;
  background-position: center;
}}
/* 亚克力卡片本体 */
.card {{
  position: relative;
  width: 560px;
  background: {C_ACRYLIC_SOLID};
  border-radius: 40px;
  padding: 40px 44px 30px;
  border: 1px solid {C_ACRYLIC_BORDER};
  box-shadow:
    0 12px 34px rgba(90, 68, 60, 0.16),
    0 2px 6px rgba(90, 68, 60, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.85);
  overflow: hidden;
}}
/* 能模糊就上真·半透光 */
@supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {{
  .card {{
    background: {C_ACRYLIC};
    -webkit-backdrop-filter: blur({BLUR_PX}px) saturate({SATURATE});
    backdrop-filter: blur({BLUR_PX}px) saturate({SATURATE});
  }}
}}
.card > * {{ position: relative; z-index: 2; }}
.arc {{
  position: absolute;
  top: -46px; left: -46px;
  width: 190px; height: 190px;
  border-radius: 50%;
  background: {C_ARC};
  opacity: 0.55;
  filter: blur(2px);
  z-index: 2;
}}
.avatar-wrap {{ text-align: center; margin: 6px 0 22px; }}
.avatar {{
  width: 116px; height: 116px;
  border-radius: 50%;
  border: 5px solid rgba(255, 255, 255, 0.92);
  box-shadow: 0 4px 16px rgba(90, 70, 70, 0.20);
  object-fit: cover;
  background: rgba(238, 242, 246, 0.85);
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
  border: 1px solid {C_VALUE_BORDER};
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
  border-bottom: 1px solid {C_DIVIDER};
}}
.rank-row:last-child {{ border-bottom: none; }}
.rank-no {{
  width: 34px; text-align: center;
  font-size: 21px; font-weight: 700; color: {C_LABEL};
}}
.rank-avatar {{
  width: 38px; height: 38px; border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.90);
  box-shadow: 0 2px 6px rgba(90, 70, 70, 0.16);
  object-fit: cover; background: rgba(238, 242, 246, 0.85);
  display: inline-block;
}}
.rank-name {{ flex: 1; font-size: 20px; color: {C_LABEL}; overflow: hidden;
              text-overflow: ellipsis; white-space: nowrap; }}
.rank-pill {{
  font-size: 18px; color: {C_VALUE_FG};
  background: {C_VALUE_BG};
  border: 1px solid {C_VALUE_BORDER};
  border-radius: 999px; padding: 5px 15px;
}}
.card-title {{ position: relative; font-size: 21px; font-weight: 700; color: {C_LABEL};
               text-align: center; margin-bottom: 14px;
               text-shadow: 0 1px 0 rgba(255, 255, 255, 0.6); }}
"""


def page_background_css(bg_data_uri: str | None) -> str:
    """底层：照片 + 暖白染色层；无图时用渐变兜底。"""
    if bg_data_uri:
        return (
            f"background-image: linear-gradient({C_PAGE_TINT}, {C_PAGE_TINT}), "
            f"url('{bg_data_uri}');"
        )
    return f"background-image: {C_PAGE_BG};"


def card_shell(*, bg_data_uri: str | None, body: str) -> str:
    """整卡外壳。无背景图时用 CSS 渐变兜底。"""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{BASE_CSS}</style></head><body>"
        f'<div class="page" style="{page_background_css(bg_data_uri)}">'
        '<div class="card"><div class="arc"></div>'
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
