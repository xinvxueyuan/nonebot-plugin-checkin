"""签到纯逻辑：给定上次签到与今日算出本次结果（无 IO，便于穷举测试）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class CheckinState:
    """某人某群当前的签到状态。"""

    points: int = 0
    streak: int = 0
    last_date: date | None = None


@dataclass(frozen=True, slots=True)
class CheckinResult:
    """一次签到的结果。"""

    points_gained: int
    streak: int
    total_points: int
    already: bool = False


def today_in(tz_name: str, *, now: datetime | None = None) -> date:
    """取指定时区的今天；`now` 仅测试注入用。"""
    tz = ZoneInfo(tz_name)
    moment = now or datetime.now(tz=tz)
    return moment.astimezone(tz).date()


def evaluate(
    state: CheckinState,
    *,
    today: date,
    daily_points: int,
    streak_bonus: int,
    streak_bonus_cap: int,
) -> CheckinResult:
    """算出本次签到奖励；同日重复返回 `already=True` 且不变更任何数字。"""
    if state.last_date == today:
        return CheckinResult(0, state.streak, state.points, already=True)
    if state.last_date is not None and today - state.last_date == timedelta(days=1):
        streak = state.streak + 1
    else:
        streak = 1
    bonus = min(max(streak - 1, 0) * streak_bonus, streak_bonus_cap)
    gained = daily_points + bonus
    return CheckinResult(gained, streak, state.points + gained)
