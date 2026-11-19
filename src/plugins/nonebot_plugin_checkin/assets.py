"""设计系统素材：背景图（xbm 随机图 API，按人缓存）+ 个性签名（get_stranger_info）。

背景图统一转 **WebP** 后落盘：原图 ~184KB → WebP q=80 + 长边 800 → ~58KB，
base64 后 ~77KB。Chromium 渲染 WebP data URI 已实测通过（渲染结果有十余万种颜色）。

两者都遵循同一条铁律：**失败只返回 None，绝不写负缓存、绝不让命令失败**。
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import TYPE_CHECKING
import uuid

import httpx

from . import store
from .config import plugin_config

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot.adapters.onebot.v11 import Bot

logger = logging.getLogger("nonebot_plugin_checkin")

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_RIFF_MAGIC = b"RIFF"  # WebP 容器头："RIFF" + size + "WEBP"

# WebP 转换参数（调整体积/质量只改这里）
_WEBP_QUALITY = 80
_WEBP_METHOD = 4  # 4 = 速度与压缩率的平衡点
_WEBP_MAX_EDGE = 800  # 长边上限（卡片宽 ~560px，800 已足够）
_MIN_BG_BYTES = 2048  # 小于此值视为坏文件
_SIGNATURE_TIMEOUT_SECONDS = 5.0  # get_stranger_info 的等待上限，防止吊死回执


# ── 背景图 ──


def bg_path(data_dir: Path, user_id: int) -> Path:
    """某人的背景图缓存文件（WebP）。"""
    return data_dir / "backgrounds" / f"{user_id}.webp"


def bg_is_fresh(
    data_dir: Path, user_id: int, *, ttl_minutes: int, now: float | None = None
) -> bool:
    """缓存存在且未过期。`ttl_minutes == 0` 表示永不过期。"""
    path = bg_path(data_dir, user_id)
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size < _MIN_BG_BYTES:
        return False
    if ttl_minutes <= 0:
        return True
    stamp = time.time() if now is None else now
    return (stamp - stat.st_mtime) < ttl_minutes * 60


async def _http_get(
    url: str, *, headers: dict[str, str], timeout: float, follow_redirects: bool = True
) -> bytes:
    """单点 HTTP GET；抽成独立函数便于测试替换。

    `follow_redirects=False` 用于带凭证的请求：httpx 默认会把自定义头（如 `x-api-key`）
    原样带到重定向目标，一旦上游返回跨域 302 就把 key 泄给第三方。
    """
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=follow_redirects
    ) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


async def _fetch_random_image(api_key: str, timeout: float) -> bytes | None:
    """从 xbm 随机图 API 取一张原图的字节。"""
    base = plugin_config.checkin_bg_url.rstrip("/")
    # 带 key 的这次请求**不跟随重定向**：见 _http_get 的说明。
    raw = await _http_get(
        base + "?count=1",
        headers={"x-api-key": api_key},
        timeout=timeout,
        follow_redirects=False,
    )
    items = json.loads(raw)
    if not items:
        return None
    image_url: str = items[0]["url"]
    # 同机回环：把公网 URL 换成本地直连，省一次 CF 往返
    if "://" in image_url:
        path = image_url.split("/", 3)[3]
        local = base.split("/v1/")[0] + "/" + path
    else:
        local = image_url
    # 取图字节这次不带凭证，可以安全跟随重定向
    return await _http_get(local, headers={}, timeout=timeout)


def to_webp(body: bytes, *, quality: int = _WEBP_QUALITY) -> bytes | None:
    """把任意图片字节转 WebP，**长边**统一缩到 _WEBP_MAX_EDGE。

    非图片字节、或 Pillow 缺 WebP 支持时返回 None（调用方降级为渐变背景）。
    """
    try:
        from PIL import Image
    except ImportError:  # Pillow 不在依赖里时静默降级
        logger.warning("Pillow 不可用，跳过 WebP 转换（改用渐变背景）")
        return None
    if not body.startswith((_JPEG_MAGIC, _PNG_MAGIC, _RIFF_MAGIC)):
        logger.warning(f"背景图既非 JPEG/PNG/WebP，前 8 字节={body[:8]!r}")
        return None
    limit = _WEBP_MAX_EDGE  # 长边上限
    try:
        with Image.open(io.BytesIO(body)) as im:
            rgb = im.convert("RGB")
            rgb.thumbnail((limit, limit))
            buf = io.BytesIO()
            rgb.save(buf, "WEBP", quality=quality, method=_WEBP_METHOD)
            out = buf.getvalue()
    except Exception as exc:  # 解码失败 / libwebp 缺失
        logger.warning(f"WebP 转换失败: {exc!r}")
        return None
    return out or None


async def ensure_bg(
    data_dir: Path, user_id: int, *, url: str | None = None, api_key: str | None = None
) -> Path | None:
    """确保某人有可用 WebP 背景图；返回缓存路径，失败返回 None（调用方用渐变兜底）。

    命中且新鲜 → 直接返回；否则拉一张新的、转 WebP 后原子落盘，失败不写任何东西。
    滚动超时：API 请求与取图下载共享同一个总预算，避免最坏情况等两个超时。
    """
    del url  # 保留参数位；当前来源统一走 checkin_bg_url
    key = plugin_config.checkin_bg_api_key if api_key is None else api_key
    if not key:
        return None
    if bg_is_fresh(data_dir, user_id, ttl_minutes=plugin_config.checkin_bg_ttl_minutes):
        return bg_path(data_dir, user_id)
    try:
        raw = await asyncio.wait_for(
            _fetch_random_image(key, plugin_config.checkin_bg_timeout_seconds),
            timeout=plugin_config.checkin_bg_timeout_seconds,
        )
    except (TimeoutError, Exception) as exc:  # 取图失败不该影响签到
        logger.warning(f"拉取随机背景图失败: user_id={user_id}, {exc!r}")
        return None
    if not raw:
        return None
    webp = to_webp(raw)
    if not webp:
        return None
    dest = bg_path(data_dir, user_id)
    tmp = dest.with_suffix(f".{uuid.uuid4().hex[:12]}.part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件名必须唯一：同一用户并发刷新时不能共用一个 .part
        tmp.write_bytes(webp)
        tmp.replace(dest)
    except OSError as exc:
        logger.warning(f"背景图落盘失败: user_id={user_id}, {exc!r}")
        return None
    finally:
        tmp.unlink(missing_ok=True)  # replace 成功后是空操作；失败时清掉残留
    return dest


# ── 个性签名 ──


def _extract_long_nick(info: object) -> str | None:
    """从 get_stranger_info 的返回里取个性签名（long_nick）。"""
    if not isinstance(info, dict):
        return None
    raw = info.get("long_nick") or info.get("longNick")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


async def fetch_signature(bot: Bot | None, group_id: int, user_id: int) -> str | None:
    """取某人的 QQ 个性签名。优先用缓存，过期再拉；任何失败返回 None。

    三重兜底：① 缓存读失败不能挂掉回执 ② 协议端请求有超时上限
    ③ 拿不到 / 存不进都只降级（隐藏引用区），绝不影响签到。
    """
    ttl = plugin_config.checkin_quote_ttl_minutes
    try:
        if store.signature_is_fresh(group_id, user_id, ttl_minutes=ttl):
            return store.get_signature(group_id, user_id)
    except Exception as exc:  # 缓存层异常（磁盘 / 未建表）不该让回执失败
        logger.warning(f"签名缓存读取失败: group={group_id} user={user_id}, {exc!r}")
    if bot is None:
        return None
    try:
        info = await asyncio.wait_for(
            bot.get_stranger_info(user_id=user_id), timeout=_SIGNATURE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # 协议端不支持 / 超时 / 网络异常都降级
        logger.warning(f"获取个性签名失败: user_id={user_id}, {exc!r}")
        return None
    text = _extract_long_nick(info)
    if text is None:
        return None
    limit = plugin_config.checkin_quote_max_chars
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    try:
        store.save_signature(group_id, user_id, text)
    except Exception as exc:
        logger.warning(f"个性签名落库失败: user_id={user_id}, {exc!r}")
    return text
