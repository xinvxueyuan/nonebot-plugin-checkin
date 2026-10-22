"""签到存储：stdlib sqlite3 + localstore 数据目录；每日唯一性由 log 主键保证。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import time

from .service import CheckinState

_T_STATS = "checkin_stats"
_T_LOG = "checkin_log"
_T_MEMBERS = "checkin_members"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_T_STATS} (
    group_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    points    INTEGER NOT NULL DEFAULT 0,
    streak    INTEGER NOT NULL DEFAULT 0,
    last_date TEXT,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS {_T_LOG} (
    group_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    date_key  TEXT    NOT NULL,
    points    INTEGER NOT NULL,
    streak    INTEGER NOT NULL,
    at        REAL    NOT NULL,
    PRIMARY KEY (group_id, user_id, date_key)
);
CREATE TABLE IF NOT EXISTS {_T_MEMBERS} (
    group_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    nickname    TEXT    NOT NULL,
    nickname_at REAL    NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
"""

_db_path: Path | None = None


def default_db_path() -> Path:
    """生产路径：localstore 的插件数据目录（只在 NoneBot 初始化后调用）。"""
    import nonebot_plugin_localstore as localstore

    return localstore.get_data_file("nonebot_plugin_checkin", "checkin.sqlite3")


def data_dir() -> Path:
    """插件数据目录（= 已初始化库文件的父目录）；头像缓存放它下面的 avatars/。"""
    if _db_path is None:
        msg = "store.init() 还没调用"
        raise RuntimeError(msg)
    return _db_path.parent


def init(path: Path) -> None:
    """指定库文件并建表；启动钩子与测试都走这里。"""
    global _db_path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = path
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def _conn() -> sqlite3.Connection:
    if _db_path is None:
        msg = "store.init() 还没调用"
        raise RuntimeError(msg)
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_state(*, group_id: int, user_id: int) -> CheckinState:
    """读当前状态；没有记录返回全零状态。"""
    with _conn() as conn:
        row = conn.execute(
            f"SELECT points, streak, last_date FROM {_T_STATS} "
            "WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
    if row is None:
        return CheckinState()
    last = date.fromisoformat(str(row["last_date"])) if row["last_date"] else None
    return CheckinState(
        points=int(row["points"]), streak=int(row["streak"]), last_date=last
    )


def save_checkin(
    *,
    group_id: int,
    user_id: int,
    date_key: str,
    points: int,
    streak: int,
    total_points: int,
    at: float | None = None,
) -> bool:
    """落库一次签到；**当日已签过返回 False 且不改任何数据**。

    幂等完全由 `checkin_log` 的主键保证：先 INSERT ... ON CONFLICT DO NOTHING，
    再按 `rowcount` 判断本次是否真的插入；只有插入了才 UPSERT 统计表。
    两步在同一个事务里，并发重复投递也不会重复加分。
    """
    stamp = time.time() if at is None else at
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO {_T_LOG} (group_id, user_id, date_key, points, streak, at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(group_id, user_id, date_key) DO NOTHING",
            (group_id, user_id, date_key, points, streak, stamp),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            f"INSERT INTO {_T_STATS} (group_id, user_id, points, streak, last_date) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(group_id, user_id) DO UPDATE SET "
            "points = excluded.points, streak = excluded.streak, "
            "last_date = excluded.last_date",
            (group_id, user_id, total_points, streak, date_key),
        )
    return True


def top(*, group_id: int, limit: int) -> list[tuple[int, int, int]]:
    """群内排行：积分降序，同分按连续天数降序。返回 (user_id, points, streak)。"""
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT user_id, points, streak FROM {_T_STATS} WHERE group_id = ? "
            "ORDER BY points DESC, streak DESC, user_id ASC LIMIT ?",
            (group_id, limit),
        ).fetchall()
    return [(int(r["user_id"]), int(r["points"]), int(r["streak"])) for r in rows]


def get_member_names(*, group_id: int) -> dict[int, tuple[str, float]]:
    """读整群昵称缓存：{user_id: (nickname, nickname_at)}。"""
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT user_id, nickname, nickname_at FROM {_T_MEMBERS} "
            "WHERE group_id = ?",
            (group_id,),
        ).fetchall()
    return {
        int(r["user_id"]): (str(r["nickname"]), float(r["nickname_at"])) for r in rows
    }


def save_member_names(*, group_id: int, names: dict[int, str], at: float) -> None:
    """批量写昵称缓存（一次事务，UPSERT）。"""
    if not names:
        return
    with _conn() as conn:
        conn.executemany(
            f"INSERT INTO {_T_MEMBERS} (group_id, user_id, nickname, nickname_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(group_id, user_id) DO UPDATE SET "
            "nickname = excluded.nickname, nickname_at = excluded.nickname_at",
            [(group_id, uid, name, at) for uid, name in names.items()],
        )


def count_log(*, group_id: int, user_id: int) -> int:
    """该用户在该群的流水行数（测试与排障用）。"""
    with _conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {_T_LOG} WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
    return int(row["n"]) if row else 0
