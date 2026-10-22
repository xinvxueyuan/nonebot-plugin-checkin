"""变异检验：把签到规则、存储与出图的关键行为**故意改坏**，确认测试真的变红。

没红过的断言只是装饰 —— 它可能断言了恒真条件、或读错了属性名，
这两种情况在正常代码上都是绿的。用法：

    env -u UV_PYTHON ... uv run python scripts/mutation_check.py

判据：每条变异体必须被**真实断言**捕获（输出里有 `FAILED ...::test_x`）。
只有收集错误 / 语法错（没有 `FAILED` 行）算「假捕获」，一律按漏网处理。
"""

# ruff: noqa: T201  # 这是命令行脚本：print 就是它的输出通道

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src/plugins/nonebot_plugin_checkin"
SERVICE = PKG / "service.py"
STORE = PKG / "store.py"
MEMBERS = PKG / "members.py"
RENDER = PKG / "render.py"

# ⚠️ 不要加 `--cov`：本仓没配覆盖率阈值，只跑断言。
_COMMON = ["-q", "-p", "no:cacheprovider", "-x", "--no-cov"]
TESTS = ["tests/", *_COMMON]

#: 每条只跑相关子集：全量含真渲染（单轮 80s+），9 条会拖成十几分钟。
#: 子集必须包含「该行为唯一的捕获测试」，否则会把捕获误报成漏网。
SUBSETS = {
    "M1": ["tests/test_service.py", *_COMMON],
    "M2": ["tests/test_service.py", *_COMMON],
    "M3": ["tests/test_service.py", *_COMMON],
    "M4": ["tests/test_store.py", *_COMMON],
    "M5": ["tests/test_store.py", *_COMMON],
    "M6": ["tests/test_render.py::test_fallback_text_contains_key_numbers", *_COMMON],
    "M7": ["tests/test_members.py", *_COMMON],
    "M8": ["tests/test_members.py", *_COMMON],
    "M9": ["tests/test_render.py::test_rank_card_renders_png", *_COMMON],
}


#: 剔除会干扰子进程的环境变量（本机 uv 约定）。
_DROP_ENV = (
    "UV_PYTHON",
    "UV_PROJECT_ENVIRONMENT",
    "SSL_CERT_FILE",
    "VIRTUAL_ENV",
    "PYTHONPATH",
)

#: 本机 pytest 默认临时根可能残留死 junction（收尾 PermissionError → 假红）；
#: 每次给一个干净的 basetemp，放在 TMPDIR（由调用方指定）下面。
_BASETEMP = (
    pathlib.Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "checkin_gate_t"
)


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in _DROP_ENV:
        env.pop(key, None)
    _BASETEMP.mkdir(parents=True, exist_ok=True)
    # ⚠️ 必须用 posix 风格：PYTEST_ADDOPTS 走 shlex，路径里的反斜杠会被吃掉，
    # 结果 `C:\Users\...` 变成仓库根下的 `C:Users...` 垃圾目录。
    env.setdefault("PYTEST_ADDOPTS", f"--basetemp={_BASETEMP.as_posix()}")
    return env


def run(extra: list[str] | None = None) -> tuple[bool, str]:
    """跑测试；返回 (是否全绿, 第一条失败证据)。"""
    r = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", *(extra or TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_child_env(),
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    out = (r.stdout or "") + (r.stderr or "")
    detail = ""
    for line in out.splitlines():
        if line.startswith("FAILED "):
            detail = line.strip()
            break
    return r.returncode == 0, detail


#: (名称, 文件, 原文锚点, 变异, 说明)
#: 锚点必须在当前工作树命中**恰好 1 次**（`text.count(old) == 1`）。
MUTATIONS = [
    (
        "M1 连续天数断了不重置（久未签到仍续上）",
        SERVICE,
        "        streak = 1\n",
        "        streak = state.streak + 1\n",
        "断签 3 天后应回 1，变异后变成 8",
    ),
    (
        "M2 同日重复签到照样加分",
        SERVICE,
        "    if state.last_date == today:\n",
        "    if False:  # 变异：同日幂等失效\n",
        "同日第二次会按「断签」重新发分",
    ),
    (
        "M3 连续加成不封顶",
        SERVICE,
        "    bonus = min(max(streak - 1, 0) * streak_bonus, streak_bonus_cap)\n",
        "    bonus = max(streak - 1, 0) * streak_bonus\n",
        "连续 50 天时加成从 20 变 98",
    ),
    (
        "M4 同日可以重复落库（覆盖累计值）",
        STORE,
        '            "ON CONFLICT(group_id, user_id, date_key) DO NOTHING",\n',
        '            "ON CONFLICT(group_id, user_id, date_key) DO UPDATE SET "\n'
        '            "points = excluded.points",\n',
        "同日第二次返回 True 并改写积分",
    ),
    (
        "M5 排行按积分升序（榜首变榜尾）",
        STORE,
        '            "ORDER BY points DESC, streak DESC, user_id ASC LIMIT ?",\n',
        '            "ORDER BY points ASC, streak DESC, user_id ASC LIMIT ?",\n',
        "排行榜顺序反转",
    ),
    (
        "M6 回退文本丢了本次积分",
        RENDER,
        '    lines.append("今天已经签过啦" if already else '
        'f"本次 +{points_gained} 分")\n',
        '    lines.append("今天已经签过啦" if already else "签到成功")\n',
        "纯文本回退不再说加了多少分",
    ),
    (
        "M7 昵称缓存永不过期（TTL 被忽略）",
        MEMBERS,
        "    minutes = (\n"
        "        plugin_config.checkin_nickname_ttl_minutes\n"
        "        if ttl_minutes is None\n"
        "        else ttl_minutes\n"
        "    )\n",
        "    minutes = 0  # 变异：TTL 被忽略，缓存永不过期\n",
        "31 分钟前的旧昵称会一直命中",
    ),
    (
        "M8 头像失败也写负缓存（磁盘留空文件）",
        MEMBERS,
        "    if data is None:\n"
        "        # 绝不写负缓存：一次网络抖动不该让某人永久没头像。\n"
        "        return None\n",
        "    if data is None:\n"
        "        # 变异：失败也写负缓存\n"
        "        path.parent.mkdir(parents=True, exist_ok=True)\n"
        '        path.write_bytes(b"")\n'
        "        return None\n",
        "下载失败后头像路径被创建",
    ),
    (
        "M9 排行图卡丢掉昵称（昵称位置印名次）",
        RENDER,
        '        f\'<span class="nm">{escape(str(row["name"]))}</span>\'\n',
        '        f\'<span class="nm">{row["rank"]}</span>\'\n',
        "排行卡上只剩数字，认不出人",
    ),
]


def main() -> int:
    print("=== 基线 ===")
    ok, detail = run()
    if not ok:
        print(f"  ✗ 基线已红 —— 先修好再来做变异检验：{detail}")
        return 1
    print("  ✓ 全绿")

    results: list[tuple[str, bool, str]] = []
    for label, path, old, new, _why in MUTATIONS:
        subset = SUBSETS[label.split(" ", 1)[0]]

        # 读端用 read_text（通用换行）：与 anchor_audit 保持一致，
        # 写回用 bytes，避免 Windows 上的换行翻译把整棵树改脏。
        orig = path.read_text(encoding="utf-8")
        hits = orig.count(old)
        if hits != 1:
            print(f"  ⚠ {label}: 锚点命中 {hits} 次 —— 跳过（锚点要能唯一定位）")
            results.append((label, False, f"锚点命中 {hits} 次"))
            continue
        mutated = orig.replace(old, new)
        try:
            compile(mutated, str(path), "exec")  # 语法错=假捕获，先在本地拦住
        except SyntaxError as exc:
            print(f"  ⚠ {label}: 变异后语法错（{exc}）—— 换写法")
            results.append((label, False, f"SyntaxError: {exc}"))
            continue
        path.write_text(mutated, encoding="utf-8", newline="\n")
        try:
            green, detail = run(subset)
        finally:
            path.write_bytes(orig.encode("utf-8"))
        caught = (not green) and bool(detail)
        results.append((label, caught, detail or "测试仍全绿"))
        print(f"  {'[捕获]' if caught else '[漏网]'} {label}")

    caught_n = sum(1 for _, c, _ in results if c)
    print(f"\n=== 捕获 {caught_n}/{len(results)} ===")
    for label, c, detail in results:
        mark = "✓" if c else "✗"
        print(f"  {mark} {label} —— {detail}")
    return 0 if caught_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
