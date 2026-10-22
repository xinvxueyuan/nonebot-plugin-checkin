"""配置：默认值、env 覆盖、边界校验。"""

from __future__ import annotations

from pydantic import ValidationError
import pytest


def test_defaults() -> None:
    from nonebot_plugin_checkin.config import Config

    c = Config()
    assert c.checkin_daily_points == 10
    assert c.checkin_streak_bonus == 2
    assert c.checkin_streak_bonus_cap == 20
    assert c.checkin_rank_size == 10
    assert c.checkin_cmd == "签到"
    assert c.checkin_rank_cmd == "签到排行"
    assert c.checkin_me_cmd == "我的签到"
    assert c.checkin_timezone == "Asia/Shanghai"
    assert c.checkin_nickname_ttl_minutes == 30
    assert c.checkin_avatar_ttl_minutes == 30


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_checkin.config import Config

    monkeypatch.setenv("CHECKIN_DAILY_POINTS", "25")
    monkeypatch.setenv("CHECKIN_CMD", "打卡")
    c = Config()
    assert c.checkin_daily_points == 25
    assert c.checkin_cmd == "打卡"


def test_bounds_reject_out_of_range() -> None:
    from nonebot_plugin_checkin.config import Config

    with pytest.raises(ValidationError):
        Config(checkin_daily_points=0)
    with pytest.raises(ValidationError):
        Config(checkin_rank_size=1)
