"""设计系统：半透光（glass / acrylic-lite）材质卡片。

材质配方（「薄霜 + 文字自带可读性」这条轴）：
  ① 底层：照片 + 极薄暖白染色层（只做一点点统一调性，不再靠它压亮照片）
  ② 卡片：一层**薄霜**（alpha 很低）+ backdrop-filter: blur(...) saturate(180%)
  ③ 边缘：1px 高光描边 + 双层外阴影 + 内侧顶部高光（玻璃厚度感）
  ④ 文字：可读性由文字**自身**承担 —— label/quote 带白色描边光晕，
     引用区再加一块半透明底片，字色也比旧配方更暗

**为什么不靠加厚遮罩保可读性**：遮罩一厚，用户就看不见背景（「看不清背景」）。
遮罩 alpha 与背景可见度是直接对冲的，文字可读性与遮罩 alpha 也是直接对冲的 ——
把这两件事解耦，遮罩只留一层薄霜，可读性交给描边/底片/字色。

不支持 backdrop-filter 的渲染器会退回更实的卡（`C_ACRYLIC_SOLID`，0.55）——
比旧版的 0.90 已经透得多，且文字自持（描边 + 底片），不靠这层遮罩保可读性。

两张卡（签到 / 排行）共用同一套 token 与骨架，只换 body 内容。
样式由 `build_css()` 在**调用时**从 token 重建（`BASE_CSS` 只是导入时快照，兼容名），
否则改 token 不生效 —— 模块级 f-string 会把 token 值在 import 时就固化。
所有注入文本一律 escape。
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from string import Template

# ── 材质 token（改材质只调这里；改完 build_css() 立刻生效）──
# 「背景遮罩强度」只有两个旋钮：C_ACRYLIC（卡体薄霜）与 C_PAGE_TINT（照片染色）。
C_ACRYLIC = "rgba(255, 255, 255, 0.18)"  # 卡体薄霜（背景可见度的主旋钮）
C_ACRYLIC_SOLID = "rgba(255, 255, 255, 0.55)"  # 兜底：无 backdrop-filter 时更实
C_ACRYLIC_BORDER = "rgba(255, 255, 255, 0.70)"  # 高光描边
C_PAGE_TINT = "rgba(252, 248, 245, 0.08)"  # 照片上的暖白染色层（只调调性，不压亮度）
C_PAGE_BG = "linear-gradient(135deg, #fdf6f3 0%, #f7e9e4 45%, #fdf1e7 100%)"  # 无图兜底
C_ARC = "#cfe8f7"
C_LABEL = "#2b2b2b"  # 比旧 #3c3c3c 更暗（薄霜上要靠字色自己顶）
C_TEXT_HALO = "rgba(255, 255, 255, 0.55)"  # 文字描边光晕（label/quote 共用）
C_QUOTE_PLATE = "rgba(255, 255, 255, 0.60)"  # 引用区底片（满足 WCAG 3.0 的最小值）
C_VALUE_BG = "rgba(255, 255, 255, 0.72)"  # 玻璃胶囊
C_VALUE_BORDER = "rgba(0, 0, 0, 0.06)"
C_VALUE_FG = "#3f3f3f"
C_QUOTE = "#333333"  # 旧 #8a8a8a 在任何遮罩下对黑底照片都 < 2.0，必须压暗
C_DIVIDER = "rgba(0, 0, 0, 0.08)"
BLUR_PX = 40
SATURATE = "180%"

# 图片 magic：头像的 mime 只能靠字节判断（qlogo 会返回 JPEG，后缀/响应头都不可靠）。
# 与 members._IMAGE_MIME 同源同序（本仓惯例：各模块自留所需 magic，见 assets.py）；
# 加新格式时两处一起加 —— 这里只决定 data URI 的 mime，不参与「要不要收下」的判断。
_AVATAR_MIME: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",  # JPEG：SOI(FFD8) + 首个段标记(FF)
}


#: CSS 骨架（`string.Template`，占位符 `${TOKEN}`）。
#: **为什么不是模块级 f-string**：f-string 在 import 时就把 token 值固化进字符串，
#: 之后改 `theme.C_ACRYLIC` 对已生成的 CSS 完全无效（改材质得重启进程才行，
#: 且扫参数时会得到一堆两两相同的样本）。这里保留骨架、在 `build_css()` 里代入，
#: token 一变就跟着变。
_CSS_TEMPLATE = Template(
    """
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; }
body {
  font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif;
  display: inline-block;
}
.page {
  position: relative;
  padding: 26px;
  border-radius: 44px;
  overflow: hidden;
  background-color: #f7e9e4;
  background-size: cover;
  background-position: center;
}
/* 卡片本体：一层薄霜（遮罩强度的唯一旋钮）*/
.card {
  position: relative;
  width: 560px;
  background: ${C_ACRYLIC_SOLID};
  border-radius: 40px;
  padding: 40px 44px 30px;
  border: 1px solid ${C_ACRYLIC_BORDER};
  box-shadow:
    0 12px 34px rgba(90, 68, 60, 0.16),
    0 2px 6px rgba(90, 68, 60, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.85);
  overflow: hidden;
}
/* 能模糊就上真·半透光 */
@supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {
  .card {
    background: ${C_ACRYLIC};
    -webkit-backdrop-filter: blur(${BLUR_PX}px) saturate(${SATURATE});
    backdrop-filter: blur(${BLUR_PX}px) saturate(${SATURATE});
  }
}
.card > * { position: relative; z-index: 2; }
.arc {
  position: absolute;
  top: -46px; left: -46px;
  width: 190px; height: 190px;
  border-radius: 50%;
  background: ${C_ARC};
  opacity: 0.55;
  filter: blur(2px);
  z-index: 2;
}
.avatar-wrap { text-align: center; margin: 6px 0 22px; }
.avatar {
  width: 116px; height: 116px;
  border-radius: 50%;
  border: 5px solid rgba(255, 255, 255, 0.92);
  box-shadow: 0 4px 16px rgba(90, 70, 70, 0.20);
  object-fit: cover;
  background: rgba(238, 242, 246, 0.85);
}
.avatar.placeholder { display: inline-block; }
.rows { position: relative; margin-top: 6px; }
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 0;
}
/* 文字可读性自持：白色描边光晕（在薄霜上顶住对比度，不靠加厚遮罩）*/
.label {
  font-size: 25px; font-weight: 700; color: ${C_LABEL}; letter-spacing: 1px;
  text-shadow:
    0 0 2px ${C_TEXT_HALO},
    0 1px 1px ${C_TEXT_HALO},
    0 0 6px ${C_TEXT_HALO};
}
.value {
  font-size: 22px;
  color: ${C_VALUE_FG};
  background: ${C_VALUE_BG};
  border: 1px solid ${C_VALUE_BORDER};
  border-radius: 999px;
  padding: 7px 20px;
  max-width: 62%;
  text-align: right;
  word-break: break-all;
}
.divider {
  height: 1px;
  background: ${C_DIVIDER};
  margin: 18px 6px 14px;
}
/* 引用：半透明底片 + 描边光晕，专治「深色照片上斜体灰字发脏」*/
.quote {
  font-size: 19px;
  font-style: italic;
  color: ${C_QUOTE};
  line-height: 1.65;
  text-align: center;
  padding: 6px 10px;
  margin: 0 2px 4px;
  border-radius: 14px;
  background: ${C_QUOTE_PLATE};
  text-shadow:
    0 0 2px ${C_TEXT_HALO},
    0 1px 1px ${C_TEXT_HALO};
  word-break: break-word;
}
.rank-row {
  display: flex; align-items: center; gap: 14px;
  padding: 9px 4px;
  border-bottom: 1px solid ${C_DIVIDER};
}
.rank-row:last-child { border-bottom: none; }
.rank-no {
  width: 34px; text-align: center;
  font-size: 21px; font-weight: 700; color: ${C_LABEL};
  text-shadow: 0 0 2px ${C_TEXT_HALO}, 0 1px 1px ${C_TEXT_HALO};
}
.rank-avatar {
  width: 38px; height: 38px; border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.90);
  box-shadow: 0 2px 6px rgba(90, 70, 70, 0.16);
  object-fit: cover; background: rgba(238, 242, 246, 0.85);
  display: inline-block;
}
.rank-name { flex: 1; font-size: 20px; color: ${C_LABEL}; overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap;
             text-shadow: 0 0 2px ${C_TEXT_HALO}, 0 1px 1px ${C_TEXT_HALO}; }
.rank-pill {
  font-size: 18px; color: ${C_VALUE_FG};
  background: ${C_VALUE_BG};
  border: 1px solid ${C_VALUE_BORDER};
  border-radius: 999px; padding: 5px 15px;
}
.card-title { position: relative; font-size: 21px; font-weight: 700;
              color: ${C_LABEL}; text-align: center; margin-bottom: 14px;
              text-shadow: 0 0 3px ${C_TEXT_HALO}, 0 1px 1px ${C_TEXT_HALO}; }
"""
)


def build_css() -> str:
    """按**当前** token 值重建整张 CSS。

    调用点必须用它（或在每次出图前重建），否则改 token 不生效 —— 这是旧版把 CSS
    写成模块级 f-string 的直接后果：import 那一刻的 token 值被永久固化。
    """
    return _CSS_TEMPLATE.substitute(
        C_ACRYLIC=C_ACRYLIC,
        C_ACRYLIC_SOLID=C_ACRYLIC_SOLID,
        C_ACRYLIC_BORDER=C_ACRYLIC_BORDER,
        C_ARC=C_ARC,
        C_LABEL=C_LABEL,
        C_TEXT_HALO=C_TEXT_HALO,
        C_VALUE_BG=C_VALUE_BG,
        C_VALUE_BORDER=C_VALUE_BORDER,
        C_VALUE_FG=C_VALUE_FG,
        C_QUOTE=C_QUOTE,
        C_QUOTE_PLATE=C_QUOTE_PLATE,
        C_DIVIDER=C_DIVIDER,
        BLUR_PX=BLUR_PX,
        SATURATE=SATURATE,
    )


#: 兼容名：导入时的 CSS 快照（老调用点/老测试仍可直接读它）。
#: 需要「改 token 立刻生效」的路径请调 `build_css()`。
BASE_CSS = build_css()


def page_background_css(bg_data_uri: str | None) -> str:
    """底层：照片 + 暖白染色层；无图时用渐变兜底。"""
    if bg_data_uri:
        return (
            f"background-image: linear-gradient({C_PAGE_TINT}, {C_PAGE_TINT}), "
            f"url('{bg_data_uri}');"
        )
    return f"background-image: {C_PAGE_BG};"


def card_shell(*, bg_data_uri: str | None, body: str) -> str:
    """整卡外壳。无背景图时用 CSS 渐变兜底。

    CSS 在这里**重建**（`build_css()`），不是读导入时的 `BASE_CSS` 快照：
    token 改了要立刻反映到出图，否则「调材质」得靠重启进程。
    """
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{build_css()}</style></head><body>"
        f'<div class="page" style="{page_background_css(bg_data_uri)}">'
        '<div class="card"><div class="arc"></div>'
        f"{body}"
        "</div></div></body></html>"
    )


def avatar_mime(data: bytes) -> str | None:
    """按 magic 认头像的图片类型（PNG / JPEG）；认不出返回 None。

    **为什么在 theme 里自己嗅、而不是让调用方传 mime 进来**：
    `avatar_block()` 的调用点有签到卡与排行卡两处（render._card_html / _rank_html），
    让函数自己认字节，调用方一行都不用改，也不会出现「有人传了 bytes 忘了传 mime」
    的半修状态。代价只是一次 8 字节前缀比较，可忽略。
    """
    for magic, mime in _AVATAR_MIME.items():
        if data.startswith(magic):
            return mime
    return None


def avatar_block(avatar: bytes | None) -> str:
    """圆形头像；无头像（或格式认不出）时渲染同尺寸占位。

    mime 由 `avatar_mime()` 现场嗅出，而不是由调用方传进来：`avatar_block()` 有
    签到卡 / 排行卡两个调用点，让函数自己认字节，调用方一行都不用改，也不会出现
    「传了 bytes 忘了传 mime」的半修状态。代价只是一次 8 字节前缀比较。

    为什么必须标对：data URI 里的 mime 是解码器的权威依据。Chromium 对图片会做
    内容嗅探，标错也能画出来（已实测），但严格解码器/其它渲染后端不会 —— 标错就是
    「有的环境能看、有的环境是空白」，这种不确定性没有必要留着。
    """
    if not avatar:
        return (
            '<div class="avatar-wrap">'
            '<span class="avatar placeholder" title="avatar placeholder"></span>'
            "</div>"
        )
    mime = avatar_mime(avatar) or "image/png"
    b64 = base64.b64encode(avatar).decode()
    return (
        f'<div class="avatar-wrap"><img class="avatar" '
        f'src="data:{mime};base64,{b64}"/></div>'
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
