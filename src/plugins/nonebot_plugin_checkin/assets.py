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
_MAX_JSON_BYTES = 64 * 1024  # 随机图 API 的 JSON 响应上限
_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 单张背景图上限（20MB，超了就降级为渐变）
_MAX_PIXELS = (
    40_000_000  # 解码前像素预算（4000万≈120MB RGB）：挡住「小文件大像素」的炸弹
)
_BG_PRUNE_EXTRA_SECONDS = 3600  # 清理时比 TTL 多留 1 小时，避免刚过期的被立刻删


class ResponseTooLargeError(Exception):
    """上游响应超过体积上限（不携带消息，细节由调用方记日志）。"""


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
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    follow_redirects: bool = True,
    max_bytes: int | None = None,
) -> bytes:
    """单点 HTTP GET；抽成独立函数便于测试替换。

    `follow_redirects=False` 用于带凭证的请求：httpx 默认会把自定义头（如 `x-api-key`）
    原样带到重定向目标，一旦上游返回跨域 302 就把 key 泄给第三方。

    `max_bytes` 用于限制响应体积（**流式读取**，超限即中止）：
    上游若返回一张几百 MB 的图，`resp.content` 会把它整个读进内存并 OOM。
    """
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=follow_redirects
    ) as client:
        if max_bytes is None:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content
        # 先看 Content-Length，能提前拒绝就直接拒
        async with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("content-length")
            if declared is not None and int(declared) > max_bytes:
                raise ResponseTooLargeError
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ResponseTooLargeError
            return bytes(buf)


async def _fetch_random_image(api_key: str, timeout: float) -> bytes | None:
    """从 xbm 随机图 API 取一张原图的字节。"""
    base = plugin_config.checkin_bg_url.rstrip("/")
    # 带 key 的这次请求**不跟随重定向**：见 _http_get 的说明。
    raw = await _http_get(
        base + "?count=1",
        headers={"x-api-key": api_key},
        timeout=timeout,
        follow_redirects=False,
        max_bytes=_MAX_JSON_BYTES,
    )
    items = json.loads(raw)
    if not items:
        return None
    image_url: str = items[0]["url"]
    # 同机回环：把公网 URL 换成本地直连，省一次 CF 往返。
    # 用 rsplit("/", 3) 而不是 split("/", 3)[3]：后者在 URL 无路径段时抛 IndexError。
    parts = image_url.split("/", 3)
    if len(parts) >= 4 and parts[3]:
        local = base.split("/v1/")[0] + "/" + parts[3]
    else:
        local = image_url
    # 取图字节这次不带凭证，可以安全跟随重定向；体积有硬上限。
    return await _http_get(
        local, headers={}, timeout=timeout, max_bytes=_MAX_IMAGE_BYTES
    )


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
            # 解码前先按**尺寸**拦一道：8000×8000 的纯色 PNG 只有 0.19MB，
            # 能绕过字节上限，但 convert("RGB") 会吃掉 ~183MB。必须在 convert 前拒绝。
            px = im.width * im.height
            if px > _MAX_PIXELS:
                logger.warning(
                    f"背景图 {im.width}x{im.height}={px} 像素超预算 {_MAX_PIXELS}，跳过"
                )
                return None
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
    # 顺手清掉早已过期的以及遗留的 .part（避免磁盘无限增长）。
    # 清理是 best-effort：即便失败也**必须**把已生成好的背景返回，不能阻断签到回执。
    try:
        prune_backgrounds(data_dir)
    except Exception as exc:  # 清理绝不该影响主流程
        logger.warning(f"背景图清理失败（忽略）: {exc!r}")
    return dest


def prune_backgrounds(
    data_dir: Path, *, ttl_minutes: int | None = None, now: float | None = None
) -> int:
    """删掉过期背景图与残留的 .part 文件，返回删除数量。

    TTL 为 0（永不过期）时只清 `.part` 残留。
    额外多留 1 小时再删：刚过期的文件还有人可能命中，别立刻抹掉。
    目录枚举失败也只记日志：清理是best-effort，绝不能阻断签到回执。
    """
    bg_dir = data_dir / "backgrounds"
    try:
        if not bg_dir.is_dir():
            return 0
        entries = list(bg_dir.iterdir())  # 枚举本身也可能 PermissionError
    except OSError as exc:
        logger.warning(f"背景图目录不可枚举，跳过清理: {bg_dir}, {exc!r}")
        return 0
    ttl = plugin_config.checkin_bg_ttl_minutes if ttl_minutes is None else ttl_minutes
    stamp = time.time() if now is None else now
    removed = 0
    for entry in entries:
        try:
            if entry.suffix == ".part":
                entry.unlink(missing_ok=True)
                removed += 1
                continue
            if entry.suffix != ".webp" or ttl <= 0:
                continue
            if (stamp - entry.stat().st_mtime) > ttl * 60 + _BG_PRUNE_EXTRA_SECONDS:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:  # 单个文件失败不影响其它
            logger.debug(f"清理背景图失败: {entry}, {exc!r}")
    if removed:
        logger.info(f"已清理 {removed} 个过期背景图/残留临时文件")
    return removed


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
    # 时间戳取「请求开始前」而非写入时刻：并发下 B 先返回新签名、A 后返回旧签名时，
    # 若用写入时刻，A 会拿到更大的时间戳从而通过 only_if_newer 的检查、把旧值盖回去。
    started_at = time.time()
    try:
        info = await asyncio.wait_for(
            bot.get_stranger_info(user_id=user_id), timeout=_SIGNATURE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # 协议端不支持 / 超时 / 网络异常都降级
        logger.warning(f"获取个性签名失败: user_id={user_id}, {exc!r}")
        return None
    text = _extract_long_nick(info)
    if text is None:
        # 空签名也要落库（用空串占位）：否则每次都判定缓存不新鲜 →
        # 每人每次都重新打协议端，白烧请求。
        try:
            store.save_signature(group_id, user_id, "", now=started_at)
        except Exception as exc:
            logger.warning(f"空签名落库失败: user_id={user_id}, {exc!r}")
        return None
    limit = plugin_config.checkin_quote_max_chars
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    try:
        store.save_signature(group_id, user_id, text, now=started_at)
    except Exception as exc:
        logger.warning(f"个性签名落库失败: user_id={user_id}, {exc!r}")
    return text
