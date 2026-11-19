import asyncio
import os
import sys

os.environ.setdefault("ENVIRONMENT", "dev")

import nonebot

nonebot.init(driver="~none")
nonebot.load_plugin("nonebot_plugin_htmlrender")

sys.path.insert(0, "src/plugins")
from nonebot_plugin_checkin import render  # noqa: E402


async def main() -> None:
    png = await render.render_checkin_card(
        title="签到成功",
        nickname="测试用户",
        points_gained=12,
        total_points=222,
        streak=6,
        rank=3,
        already=False,
    )
    print("card bytes:", len(png) if png else None)
    rows = [
        {"rank": i, "name": f"用户{i}", "points": 100 - i, "streak": 5, "avatar_png": None}
        for i in range(1, 4)
    ]
    png2 = await render.render_rank_card(rows, title="本群签到排行")
    print("rank bytes:", len(png2) if png2 else None)


asyncio.run(main())
