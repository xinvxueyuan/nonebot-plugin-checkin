"""存储：建表幂等、签到落库、同日幂等、排行、按群隔离。"""

from __future__ import annotations

from datetime import date
import time

G, G2, U1, U2, U3 = 1001, 2002, 11, 22, 33


def _checkin(group: int, user: int, day: str, points: int, streak: int) -> bool:
    from nonebot_plugin_checkin import store

    return store.save_checkin(
        group_id=group,
        user_id=user,
        date_key=day,
        points=points,
        streak=streak,
        total_points=points,  # 测试里直接用本次值当累计值
        at=time.time(),
    )


def test_init_is_idempotent() -> None:
    from nonebot_plugin_checkin import store

    store.init(store._db_path)  # 只为验证重复 init 不炸
    store.init(store._db_path)
    assert store.get_state(group_id=G, user_id=U1).points == 0


def test_state_is_empty_before_any_checkin() -> None:
    from nonebot_plugin_checkin import store

    s = store.get_state(group_id=G, user_id=U1)
    assert (s.points, s.streak, s.last_date) == (0, 0, None)


def test_save_then_read() -> None:
    from nonebot_plugin_checkin import store

    assert _checkin(G, U1, "2026-10-22", 10, 1) is True
    s = store.get_state(group_id=G, user_id=U1)
    assert (s.points, s.streak, s.last_date) == (10, 1, date(2026, 10, 22))


def test_same_day_twice_is_rejected() -> None:
    assert _checkin(G, U1, "2026-10-22", 10, 1) is True
    assert _checkin(G, U1, "2026-10-22", 999, 99) is False  # 幂等：第二次返回 False
    from nonebot_plugin_checkin import store

    s = store.get_state(group_id=G, user_id=U1)
    assert (s.points, s.streak) == (10, 1)


def test_points_accumulate_across_days() -> None:
    from nonebot_plugin_checkin import store

    _checkin(G, U1, "2026-10-21", 10, 1)
    store.save_checkin(
        group_id=G,
        user_id=U1,
        date_key="2026-10-22",
        points=12,
        streak=2,
        total_points=22,
        at=time.time(),
    )
    s = store.get_state(group_id=G, user_id=U1)
    assert (s.points, s.streak, s.last_date) == (22, 2, date(2026, 10, 22))


def test_rank_is_desc_by_points_then_streak() -> None:
    from nonebot_plugin_checkin import store

    store.save_checkin(
        group_id=G,
        user_id=U1,
        date_key="2026-10-22",
        points=10,
        streak=5,
        total_points=50,
        at=time.time(),
    )
    store.save_checkin(
        group_id=G,
        user_id=U2,
        date_key="2026-10-22",
        points=10,
        streak=9,
        total_points=50,
        at=time.time(),
    )
    store.save_checkin(
        group_id=G,
        user_id=U3,
        date_key="2026-10-22",
        points=10,
        streak=1,
        total_points=80,
        at=time.time(),
    )
    top = store.top(group_id=G, limit=10)
    # 80 分第一；同为 50 分时 streak 9 在 5 前
    assert [row[0] for row in top] == [U3, U2, U1]


def test_rank_respects_limit() -> None:
    from nonebot_plugin_checkin import store

    for i, u in enumerate((U1, U2, U3)):
        store.save_checkin(
            group_id=G,
            user_id=u,
            date_key="2026-10-22",
            points=10,
            streak=1,
            total_points=10 * (i + 1),
            at=time.time(),
        )
    assert len(store.top(group_id=G, limit=2)) == 2


def test_groups_are_isolated() -> None:
    from nonebot_plugin_checkin import store

    _checkin(G, U1, "2026-10-22", 10, 1)
    _checkin(G2, U1, "2026-10-22", 77, 3)
    assert store.get_state(group_id=G, user_id=U1).points == 10
    assert store.get_state(group_id=G2, user_id=U1).points == 77


def test_log_has_one_row_per_day() -> None:
    from nonebot_plugin_checkin import store

    _checkin(G, U1, "2026-10-21", 10, 1)
    _checkin(G, U1, "2026-10-22", 12, 2)
    _checkin(G, U1, "2026-10-22", 12, 2)  # 重复
    assert store.count_log(group_id=G, user_id=U1) == 2


def test_signature_upsert_and_read(tmp_path):
    from nonebot_plugin_checkin import store as st

    st.init(tmp_path / "c.sqlite")
    assert st.get_signature(1, 2) is None
    st.save_signature(1, 2, "人生的最后一课，学会离别")
    assert st.get_signature(1, 2) == "人生的最后一课，学会离别"
    st.save_signature(1, 2, "新签名")
    assert st.get_signature(1, 2) == "新签名"


def test_signature_ttl_freshness(tmp_path):
    import time

    from nonebot_plugin_checkin import store as st

    st.init(tmp_path / "c.sqlite")
    st.save_signature(1, 2, "旧")
    assert st.signature_is_fresh(1, 2, ttl_minutes=5) is True
    assert st.signature_is_fresh(1, 2, ttl_minutes=5, now=time.time() + 6 * 60) is False
    assert st.signature_is_fresh(1, 2, ttl_minutes=0) is True
    assert st.signature_is_fresh(9, 9, ttl_minutes=5) is False


def test_signature_older_write_does_not_clobber_newer(tmp_path):
    """并发下先发出去的请求可能后返回：旧签名不得盖掉新签名。"""
    import time

    from nonebot_plugin_checkin import store as st

    st.init(tmp_path / "c.sqlite")
    t0 = time.time()
    st.save_signature(1, 2, "新签名", now=t0 + 10)  # 后发出的那次先返回
    st.save_signature(1, 2, "旧签名", now=t0)  # 先发出的那次后返回
    assert st.get_signature(1, 2) == "新签名"
    # only_if_newer=False 时仍是无条件覆盖（显式刷新场景）
    st.save_signature(1, 2, "强制覆盖", now=t0, only_if_newer=False)
    assert st.get_signature(1, 2) == "强制覆盖"
