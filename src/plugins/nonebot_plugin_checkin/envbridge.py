"""把 .env 里读进 driver.config 的键桥接回 os.environ。

为什么需要：nonebot 的 `.env` 只喂 `driver.config`，**不回写 `os.environ`**；
而 Playwright 只读 `os.environ` 来定位浏览器目录。2026-11-19 实测：
只把 `PLAYWRIGHT_BROWSERS_PATH` 写进 `.env` 时 `os.environ` 仍为 None，
htmlrender 会尝试自行下载浏览器并失败（`RuntimeError: Playwright environment
is not set up correctly`）。

桥接是「只补不改」：已有真实环境变量（systemd `Environment=`）优先，绝不被覆盖。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("nonebot_plugin_checkin")

_KEY = "PLAYWRIGHT_BROWSERS_PATH"


def bridge_playwright_path(value: str | None) -> bool:
    """把配置值写进 os.environ（若尚未设置）。返回是否真的写入了。"""
    if not value or not value.strip():
        return False
    clean = value.strip()
    if os.environ.get(_KEY):
        return False  # systemd / 真实环境优先，不覆盖
    os.environ[_KEY] = clean
    logger.info(f"已把 {_KEY} 桥接到 os.environ: {clean}")
    return True
