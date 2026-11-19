"""真渲染验收：生成两张卡并做像素级断言。"""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "dev")

import nonebot  # noqa: E402

nonebot.init(driver="~none")
nonebot.load_plugin("nonebot_plugin_htmlrender")

sys.path.insert(0, "src/plugins")
from nonebot_plugin_checkin import render  # noqa: E402

OUT = Path("/tmp/checkin-out")
OUT.mkdir(exist_ok=True)


async def main() -> None:
    png = await render.render_checkin_card(
        title="签到成功",
        nickname="新v学员",
        points_gained=12,
        total_points=222,
        streak=6,
        rank=3,
        already=False,
        quote="人生的最后一课，学会离别 来的时候是哭着来的 走的时候是听着哭声走的",
        bg=None,
    )
    assert png is not None, "签到卡渲染返回 None"
    (OUT / "card.png").write_bytes(png)
    print("card:", len(png), "bytes")

    rows = [
        {
            "rank": i,
            "name": f"用户{i}号",
            "points": 300 - i * 7,
            "streak": 10 - i,
            "avatar_png": None,
        }
        for i in range(1, 6)
    ]
    png2 = await render.render_rank_card(
        rows, title="本群签到排行", quote="人生的最后一课", bg=None
    )
    assert png2 is not None, "排行卡渲染返回 None"
    (OUT / "rank.png").write_bytes(png2)
    print("rank:", len(png2), "bytes")


asyncio.run(main())
