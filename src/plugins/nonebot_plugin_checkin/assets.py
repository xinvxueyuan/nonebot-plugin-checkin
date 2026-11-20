"""设计系统素材：背景图（xbm 随机图 API，按人缓存 + 同群不撞图）+ 个性签名。

背景图统一转 **WebP** 后落盘：原图 ~184KB → WebP q=80 + 长边 800 → ~58KB，
base64 后 ~77KB。Chromium 渲染 WebP data URI 已实测通过（渲染结果有十余万种颜色）。

上游图库只有几十张，纯随机抽必然出现「同群两人撞同一张」（生日碰撞，不是缓存复用）。
所以落盘时把**上游原图的 sha256** 记进 `backgrounds/index.json`，抽图时避开本群
仍在有效期内的其他用户已占用的图；图库真被用尽时宁可重复也不让用户没背景。

两者都遵循同一条铁律：**失败只返回 None，绝不写负缓存、绝不让命令失败**。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import time
from typing import TYPE_CHECKING, NamedTuple, TypedDict
import uuid

import httpx

from . import store
from .config import plugin_config

if TYPE_CHECKING:
    from collections.abc import Mapping
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
_SIGNATURE_TIMEOUT_SECONDS = 5.0  # get_stranger_info 的等待上限，防止吊死回执
_MAX_JSON_BYTES = 64 * 1024  # 随机图 API 的 JSON 响应上限
_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 单张背景图上限（20MB，超了就降级为渐变）
_WEBP_MIN_HEADER = 12  # RIFF(4) + 体积(4) + "WEBP"(4)：少于这个长度不可能是 WebP
_MAX_PIXELS = (
    40_000_000  # 解码前像素预算（4000万≈120MB RGB）：挡住「小文件大像素」的炸弹
)
_BG_PRUNE_EXTRA_SECONDS = 3600  # 清理时比 TTL 多留 1 小时，避免刚过期的被立刻删
_BG_INDEX_NAME = "index.json"  # 背景图身份索引（与图片同目录，便于一起备份/迁移）
_BG_BATCH_MAX = 50  # 一次批量要多少候选的上限（上游 `?count` 支持 1–50）
_BG_MAX_DOWNLOADS = 3  # 单次分配最多下载几张候选：撞到多张都有主也不至于把图库全下完


class ResponseTooLargeError(Exception):
    """上游响应超过体积上限（不携带消息，细节由调用方记日志）。"""


# ── 背景图身份索引（同群去重） ──
#
# 为什么用 sidecar JSON 而不是 sqlite（store.py 已有库）：store 管的是签到数据，
# 背景图身份属于素材层的实现细节，混表会把两件互不相干的事绑在一起；这里只需要
# 「按 user_id 存一条小记录」，JSON 边车足够，而且人工可读、坏文件可自愈
# （读不出来就当空索引，绝不阻断签到）。


class BgRecord(TypedDict):
    """一条背景图分配记录：上游原图身份 + 归属群 + 分配时刻。"""

    sha256: str
    url: str
    group_id: int | None
    assigned_at: float


class _Occupied(NamedTuple):
    """本群仍被占用的图身份（sha256 与上游 URL 两套，URL 用于省下载）。"""

    shas: frozenset[str]
    urls: frozenset[str]


def bg_index_path(data_dir: Path) -> Path:
    """背景图身份索引：`{user_id: {sha256, url, group_id, assigned_at}}`。"""
    return data_dir / "backgrounds" / _BG_INDEX_NAME


def _parse_record(value: object) -> BgRecord | None:
    """校验一条索引记录；任何字段不合法就整条丢弃（坏一行不拖垮整个索引）。"""
    if not isinstance(value, dict):
        return None
    sha = value.get("sha256")
    url = value.get("url")
    group = value.get("group_id")
    stamp = value.get("assigned_at")
    if not isinstance(sha, str) or not sha:
        return None
    if group is not None and (not isinstance(group, int) or isinstance(group, bool)):
        return None
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    return BgRecord(
        sha256=sha,
        url=url if isinstance(url, str) else "",
        group_id=group,
        assigned_at=float(stamp),
    )


def read_bg_index(data_dir: Path) -> dict[int, BgRecord]:
    """读背景图身份索引；文件缺失 / 损坏 / 字段不对一律当空表。

    去重信息没了最多让「这次抽图」退化成纯随机，绝不能让签到失败 ——
    所以这里吞掉所有异常，只记日志。
    """
    path = bg_index_path(data_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning(f"背景图索引读取失败，本次按空表处理: {exc!r}")
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:  # 半截 JSON / 手改坏 / 编码问题
        logger.warning(f"背景图索引损坏，本次按空表处理: {exc!r}")
        return {}
    if not isinstance(data, dict):
        logger.warning("背景图索引结构不是对象，本次按空表处理")
        return {}
    records: dict[int, BgRecord] = {}
    for key, value in data.items():
        record = _parse_record(value)
        if record is None:
            continue
        try:
            records[int(key)] = record
        except (TypeError, ValueError):
            continue
    return records


def _write_bg_index(data_dir: Path, records: Mapping[int, BgRecord]) -> None:
    """原子写索引（唯一临时文件 + replace）：读者永远看不到半截 JSON。

    读-改-写由调用方在同一段同步代码里完成（中间没有 await），见 `_commit_background`。
    """
    path = bg_index_path(data_dir)
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:12]}.part")
    payload = {str(uid): dict(record) for uid, record in records.items()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)  # replace 成功后是空操作；失败时清掉残留


def _occupied_identities(
    data_dir: Path,
    *,
    user_id: int,
    group_id: int | None,
    ttl_minutes: int,
    now: float | None = None,
) -> _Occupied:
    """本群**仍在有效期**的其他用户已占用的图身份。

    有效期以「他那张缓存文件还在、且没过期」为准（和 `bg_is_fresh` 同一把尺子）：
    过期 / 被剪枝掉的图谁都不会再看到，不该继续挡着别人 —— 这样索引里的陈记录
    会自愈，不需要额外的清理任务。
    """
    if group_id is None:
        return _Occupied(frozenset(), frozenset())
    stamp = time.time() if now is None else now
    shas: set[str] = set()
    urls: set[str] = set()
    for other_id, record in read_bg_index(data_dir).items():
        if other_id == user_id or record["group_id"] != group_id:
            continue
        if not bg_is_fresh(data_dir, other_id, ttl_minutes=ttl_minutes, now=stamp):
            continue
        shas.add(record["sha256"])
        if record["url"]:
            urls.add(record["url"])
    return _Occupied(frozenset(shas), frozenset(urls))


# ── 背景图 ──


def bg_path(data_dir: Path, user_id: int) -> Path:
    """某人的背景图缓存文件（WebP）。"""
    return data_dir / "backgrounds" / f"{user_id}.webp"


def _is_valid_webp(path: Path) -> bool:
    """按文件头判断是否有效 WebP（不按体积：小图合法时会小于 2KB）。

    空文件 / 半截文件 / 别的格式落进来都要判无效，否则会把坏缓存当命中。
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    return (
        len(head) >= _WEBP_MIN_HEADER
        and head[:4] == _RIFF_MAGIC
        and head[8:12] == b"WEBP"
    )


def bg_is_fresh(
    data_dir: Path, user_id: int, *, ttl_minutes: int, now: float | None = None
) -> bool:
    """缓存存在、是有效 WebP 且未过期。`ttl_minutes == 0` 表示永不过期。"""
    path = bg_path(data_dir, user_id)
    try:
        stat = path.stat()
    except OSError:
        return False
    if not _is_valid_webp(path):
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


async def _fetch_random_urls(api_key: str, timeout: float, *, count: int) -> list[str]:
    """从 xbm 随机图 API 一次批量取 count 个候选 URL。

    上游 `?count=N`（1–50）**同一请求内无放回**，所以一次批量拿多个候选就够，
    撞图要换下一张时不必再打一次 API。
    """
    base = plugin_config.checkin_bg_url.rstrip("/")
    # 带 key 的这次请求**不跟随重定向**：见 _http_get 的说明。
    raw = await _http_get(
        f"{base}?count={max(1, count)}",
        headers={"x-api-key": api_key},
        timeout=timeout,
        follow_redirects=False,
        max_bytes=_MAX_JSON_BYTES,
    )
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    urls: list[str] = []
    for item in items:
        image_url = item.get("url") if isinstance(item, dict) else None
        if isinstance(image_url, str) and image_url:
            urls.append(image_url)
    return urls


async def _download_image(image_url: str, timeout: float) -> bytes:
    """下载单张候选原图（不带凭证，可跟随重定向；体积有硬上限）。"""
    base = plugin_config.checkin_bg_url.rstrip("/")
    # 同机回环：把公网 URL 换成本地直连，省一次 CF 往返。
    # 用 split("/", 3) 而不是固定下标：URL 无路径段时不会 IndexError。
    parts = image_url.split("/", 3)
    if len(parts) >= 4 and parts[3]:
        local = base.split("/v1/")[0] + "/" + parts[3]
    else:
        local = image_url
    return await _http_get(
        local, headers={}, timeout=timeout, max_bytes=_MAX_IMAGE_BYTES
    )


def _candidate_count(occupied_urls: int, group_id: int | None) -> int:
    """一次批量要几个候选。

    没有群上下文（老调用方）→ 只要 1 张，行为和以前完全一致。
    有群 → 要「已占用 + 2」：上游同一请求内无放回，k+2 个候选里至少有两张没人用，
    即使并发签到同时起跑、第一张被隔壁抢走，也还有一张备选。
    """
    if group_id is None:
        return 1
    return min(_BG_BATCH_MAX, max(2, occupied_urls + 2))


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
    data_dir: Path,
    user_id: int,
    *,
    url: str | None = None,
    api_key: str | None = None,
    group_id: int | None = None,
) -> Path | None:
    """确保某人有可用 WebP 背景图；返回缓存路径，失败返回 None（调用方用渐变兜底）。

    命中且新鲜 → 直接返回；否则拉一张新的、转 WebP 后原子落盘，失败不写任何东西。
    滚动超时：API 请求与取图下载共享同一个总预算，避免最坏情况等两个超时。

    传了 `group_id` 就做**同群去重**：避开本群其他用户当前仍在有效期内的那张图
    （图库 59 张 vs 群友十几人，容量够）。不传则保持老行为 —— 纯随机、一次只取一张，
    既有调用方与测试都不用改。
    """
    del url  # 保留参数位；当前来源统一走 checkin_bg_url
    key = plugin_config.checkin_bg_api_key if api_key is None else api_key
    if not key:
        return None
    ttl_minutes = plugin_config.checkin_bg_ttl_minutes
    if bg_is_fresh(data_dir, user_id, ttl_minutes=ttl_minutes):
        return bg_path(data_dir, user_id)
    try:
        return await asyncio.wait_for(
            _allocate_background(
                data_dir,
                user_id,
                group_id=group_id,
                api_key=key,
                ttl_minutes=ttl_minutes,
            ),
            timeout=plugin_config.checkin_bg_timeout_seconds,
        )
    except Exception as exc:  # 取图失败不该影响签到（含 asyncio 超时）
        logger.warning(f"拉取随机背景图失败: user_id={user_id}, {exc!r}")
        return None


async def _allocate_background(
    data_dir: Path,
    user_id: int,
    *,
    group_id: int | None,
    api_key: str,
    ttl_minutes: int,
) -> Path | None:
    """抽一张本群还没人用的图 → 转 WebP → 原子落盘 → 记身份；拿不到图返回 None。

    候选是**一次批量**要来的（`?count=N`，上游同一请求内无放回）：先按上游 URL
    排掉本群已占用的（省一次下载），再逐张下载试落盘；提交时重读索引复判，所以
    并发签到不会都以为同一张空闲。全部候选都有主时允许重复 —— 绝不让人没背景。
    """
    timeout = plugin_config.checkin_bg_timeout_seconds
    occupied = _occupied_identities(
        data_dir, user_id=user_id, group_id=group_id, ttl_minutes=ttl_minutes
    )
    urls = await _fetch_random_urls(
        api_key, timeout, count=_candidate_count(len(occupied.urls), group_id)
    )
    if not urls:
        return None
    if group_id is None:
        free, taken = urls, []
    else:
        free = [u for u in urls if u not in occupied.urls]
        taken = [u for u in urls if u in occupied.urls]
    # 最多试 _BG_MAX_DOWNLOADS 张：撞到多张都有主时别把整个图库都下载一遍
    for image_url in free[:_BG_MAX_DOWNLOADS]:
        dest = await _try_candidate(
            data_dir,
            user_id,
            image_url=image_url,
            group_id=group_id,
            ttl_minutes=ttl_minutes,
            force=False,
        )
        if dest is not None:
            return dest
    # 图库真被本群用尽（或全被并发抢走 / 转码失败）：兜底允许重复一张
    for image_url in taken[:1]:
        dest = await _try_candidate(
            data_dir,
            user_id,
            image_url=image_url,
            group_id=group_id,
            ttl_minutes=ttl_minutes,
            force=True,
        )
        if dest is not None:
            logger.info(
                f"本群背景图候选都有主了，允许重复一张: group={group_id} user={user_id}"
            )
            return dest
    return None


async def _try_candidate(
    data_dir: Path,
    user_id: int,
    *,
    image_url: str,
    group_id: int | None,
    ttl_minutes: int,
    force: bool,
) -> Path | None:
    """下载一张候选并尝试定稿；下载失败返回 None（上层换下一张候选）。"""
    raw = await _download_image(image_url, plugin_config.checkin_bg_timeout_seconds)
    if not raw:
        return None
    return _commit_background(
        data_dir,
        user_id,
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        source_url=image_url,
        group_id=group_id,
        ttl_minutes=ttl_minutes,
        force=force,
    )


def _commit_background(
    data_dir: Path,
    user_id: int,
    *,
    raw: bytes,
    sha256: str,
    source_url: str,
    group_id: int | None,
    ttl_minutes: int,
    force: bool,
) -> Path | None:
    """定稿：重读索引 → 复判占用 → 转 WebP → 原子落盘 → 记身份。

    这个函数**没有任何 await**：asyncio 单线程下别的事件循环切不进来，所以
    「复判占用 + 写文件 + 写索引」对其他签到协程是原子的 —— 两个并发用户不会
    都判定同一张图空闲。这也是这里不需要加锁的原因（**别把网络请求塞进来**）。
    """
    if not force:
        occupied = _occupied_identities(
            data_dir, user_id=user_id, group_id=group_id, ttl_minutes=ttl_minutes
        )
        if sha256 in occupied.shas or source_url in occupied.urls:
            return None  # 刚被别人占掉：让上层换下一张候选
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
    _record_background(
        data_dir,
        user_id,
        sha256=sha256,
        source_url=source_url,
        group_id=group_id,
    )
    # 顺手清掉早已过期的以及遗留的 .part（避免磁盘无限增长）。
    # 清理是 best-effort：即便失败也**必须**把已生成好的背景返回，不能阻断签到回执。
    try:
        prune_backgrounds(data_dir)
    except Exception as exc:  # 清理绝不该影响主流程
        logger.warning(f"背景图清理失败（忽略）: {exc!r}")
    return dest


def _record_background(
    data_dir: Path, user_id: int, *, sha256: str, source_url: str, group_id: int | None
) -> None:
    """把这次分配记进索引（best-effort：写不进只降级去重，绝不影响出图）。"""
    try:
        records = read_bg_index(data_dir)
        records[user_id] = BgRecord(
            sha256=sha256,
            url=source_url,
            group_id=group_id,
            assigned_at=time.time(),
        )
        _write_bg_index(data_dir, records)
    except OSError as exc:
        logger.warning(f"背景图索引写入失败（去重降级）: user_id={user_id}, {exc!r}")


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
