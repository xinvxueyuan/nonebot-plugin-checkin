"""签到规则纯逻辑：连续天数、加成、封顶、同日幂等、时区。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nonebot_plugin_checkin.service import CheckinState, evaluate, today_in

D = date(2026, 10, 22)
KW = {"daily_points": 10, "streak_bonus": 2, "streak_bonus_cap": 20}


def test_first_checkin_ever() -> None:
    r = evaluate(CheckinState(), today=D, **KW)
    assert (r.points_gained, r.streak, r.total_points, r.already) == (10, 1, 10, False)


def test_second_consecutive_day_adds_bonus() -> None:
    s = CheckinState(points=10, streak=1, last_date=D - timedelta(days=1))
    r = evaluate(s, today=D, **KW)
    assert (r.points_gained, r.streak, r.total_points) == (12, 2, 22)


def test_streak_bonus_accumulates() -> None:
    s = CheckinState(points=100, streak=5, last_date=D - timedelta(days=1))
    r = evaluate(s, today=D, **KW)
    assert r.streak == 6 and r.points_gained == 10 + min(5 * 2, 20)


def test_bonus_is_capped() -> None:
    s = CheckinState(points=999, streak=50, last_date=D - timedelta(days=1))
    r = evaluate(s, today=D, **KW)
    assert r.points_gained == 10 + 20  # 封顶 20


def test_broken_streak_resets_to_one() -> None:
    s = CheckinState(points=50, streak=7, last_date=D - timedelta(days=3))
    r = evaluate(s, today=D, **KW)
    assert (r.streak, r.points_gained) == (1, 10)


def test_same_day_twice_changes_nothing() -> None:
    s = CheckinState(points=30, streak=3, last_date=D)
    r = evaluate(s, today=D, **KW)
    assert (r.points_gained, r.streak, r.total_points, r.already) == (0, 3, 30, True)


def test_zero_bonus_config_is_allowed() -> None:
    s = CheckinState(points=0, streak=9, last_date=D - timedelta(days=1))
    r = evaluate(s, today=D, daily_points=5, streak_bonus=0, streak_bonus_cap=0)
    assert (r.points_gained, r.streak) == (5, 10)


def test_today_in_shanghai_for_utc_instant() -> None:
    # 2026-10-21T16:30Z == 2026-10-22 00:30 Asia/Shanghai
    assert (
        today_in(
            "Asia/Shanghai", now=datetime(2026, 10, 21, 16, 30, tzinfo=timezone.utc)
        )
        == D
    )


def test_today_in_shanghai_just_before_midnight() -> None:
    # 2026-10-21T15:59Z == 2026-10-21 23:59 Asia/Shanghai
    assert today_in(
        "Asia/Shanghai", now=datetime(2026, 10, 21, 15, 59, tzinfo=timezone.utc)
    ) == date(2026, 10, 21)
