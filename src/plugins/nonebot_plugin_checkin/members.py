"""昵称与头像：两者都带缓存。昵称存 DB（TTL），头像存磁盘（文件 mtime 判 TTL）。"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

from . import store
from .config import plugin_config

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from nonebot.adapters.onebot.v11 import Bot

logger = logging.getLogger("nonebot_plugin_checkin")

AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def avatar_path(user_id: int) -> Path:
    """头像缓存文件路径（插件数据目录下的 avatars/）。"""
    return store.data_dir() / "avatars" / f"{user_id}.png"


def _as_int(value: object) -> int:
    """把协议端给的 id 统一成 int（字符串/缺失都容忍，拿不到返回 0）。"""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def avatar_is_fresh(
    user_id: int, *, ttl_minutes: int | None = None, now: float | None = None
) -> bool:
    """缓存存在且未过期？`ttl_minutes == 0` 表示永不过期。"""
    minutes = (
        plugin_config.checkin_avatar_ttl_minutes if ttl_minutes is None else ttl_minutes
    )
    try:
        stat = avatar_path(user_id).stat()
    except OSError:
        return False
    if stat.st_size == 0:
        return False
    if minutes <= 0:
        return True
    stamp = time.time() if now is None else now
    return (stamp - stat.st_mtime) < minutes * 60


async def _download(user_id: int) -> bytes | None:
    """下载头像；异常或非 PNG 都返回 None（不在磁盘上留任何痕迹）。"""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(AVATAR_URL.format(uid=user_id))
            resp.raise_for_status()
            data = resp.content
    except Exception as exc:  # 头像拿不到不该让命令失败
        logger.warning(f"拉取头像失败: user_id={user_id}, {exc!r}")
        return None
    if not data.startswith(_PNG_MAGIC):
        logger.warning(f"头像不是 PNG，丢弃: user_id={user_id}, {len(data)}B")
        return None
    return data


async def fetch_avatar(user_id: int, *, ttl_minutes: int | None = None) -> bytes | None:
    """取头像字节：缓存新鲜直接用；否则下载并**仅在成功时**落盘。"""
    path = avatar_path(user_id)
    cached: bytes | None = None
    if avatar_is_fresh(user_id, ttl_minutes=ttl_minutes):
        try:
            cached = path.read_bytes()
        except OSError as exc:
            logger.warning(
                f"头像缓存读取失败，改为重新下载: user_id={user_id}, {exc!r}"
            )
    if cached is not None:
        return cached
    data = await _download(user_id)
    if data is None:
        # 绝不写负缓存：一次网络抖动不该让某人永久没头像。
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        logger.warning(f"头像写缓存失败: user_id={user_id}, {exc!r}")
    return data


async def resolve_names(
    bot: Bot,
    *,
    group_id: int,
    user_ids: Sequence[int],
    ttl_minutes: int | None = None,
    event_name: tuple[int, str] | None = None,
) -> dict[int, str]:
    """批量解析昵称：缓存优先，未命中的用**一次** get_group_member_list 补齐。

    `event_name` 是「当前发言人」的现成昵称，给了就不用等群成员列表；
    API 失败只记日志、回退 QQ 号，**不写缓存**。
    """
    minutes = (
        plugin_config.checkin_nickname_ttl_minutes
        if ttl_minutes is None
        else ttl_minutes
    )
    cached = store.get_member_names(group_id=group_id)
    now = time.time()
    result: dict[int, str] = {}
    missing: list[int] = []
    for uid in dict.fromkeys(user_ids):
        hit = cached.get(uid)
        if hit is not None and (minutes <= 0 or (now - hit[1]) < minutes * 60):
            result[uid] = hit[0]
        else:
            missing.append(uid)
    if event_name is not None and event_name[0] in missing:
        result[event_name[0]] = event_name[1]
        missing.remove(event_name[0])
    if missing:
        rows: list[dict[str, object]] = []
        try:
            rows = await bot.get_group_member_list(group_id=group_id)
        except Exception as exc:  # 名字拿不到就退回 QQ 号
            logger.warning(f"拉取群成员列表失败: group_id={group_id}, {exc!r}")
        found: dict[int, str] = {}
        for row in rows:
            uid = _as_int(row.get("user_id"))
            if uid not in missing:
                continue
            name = str(row.get("card") or row.get("nickname") or "").strip()
            if name:
                found[uid] = name
        if found:
            store.save_member_names(group_id=group_id, names=found, at=now)
        result.update(found)
    for uid in user_ids:
        result.setdefault(uid, str(uid))
    return result
