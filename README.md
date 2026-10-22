# nonebot-plugin-checkin

> **qbot 插件** · 宿主仓库：[xinvxueyuan/qbot](https://github.com/xinvxueyuan/qbot)

QQ 群每日签到：每天签一次、连续天数加成、积分累计、群内积分排行。

## 功能特性

- **每日签到**：每个群每人每天只记一次；同日重复投递由 `checkin_log` 主键拦下，不重复加分。
- **连续加成**：连续天数越多单次奖励越高，加成有上限；断签一天就从 1 重新计。
- **积分累计**：积分与连续天数按群隔离，换群从头开始。
- **群内排行**：按积分降序，同分按连续天数降序，取前 `CHECKIN_RANK_SIZE` 名。
- **出图**：签到卡与排行卡用 htmlrender 渲染（排行卡含头像）；渲染不可用时自动回退纯文本，信息等价。
- **缓存**：昵称存库、头像落盘，两者都按 TTL 刷新；头像下载失败不写负缓存。

## 安装

```bash
nb plugin install nonebot-plugin-checkin
```

或在 `pyproject.toml` 的依赖里加 `nonebot-plugin-checkin` 后 `uv sync`。
需要 OneBot V11 适配器；出图依赖 `nonebot-plugin-htmlrender`（随插件安装）。

## 配置

配置项写在 `.env` 里，键名 = 字段名大写（NoneBot 约定，大小写不敏感）。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `CHECKIN_DAILY_POINTS` | `10` | 每日基础积分（1–1000） |
| `CHECKIN_STREAK_BONUS` | `2` | 每多连续一天额外积分（0–100） |
| `CHECKIN_STREAK_BONUS_CAP` | `20` | 连续加成封顶（0–1000） |
| `CHECKIN_RANK_SIZE` | `10` | 排行显示人数（3–50） |
| `CHECKIN_CMD` | `签到` | 签到命令词 |
| `CHECKIN_RANK_CMD` | `签到排行` | 排行命令词 |
| `CHECKIN_ME_CMD` | `我的签到` | 查询自己积分的命令词 |
| `CHECKIN_TIMEZONE` | `Asia/Shanghai` | 判定「今天」的时区 |
| `CHECKIN_NICKNAME_TTL_MINUTES` | `30` | 昵称缓存时长，**单位分钟**（默认 30；`0` = 永不过期，上限 10080 = 7 天） |
| `CHECKIN_AVATAR_TTL_MINUTES` | `30` | 头像缓存时长，**单位分钟**（默认 30；`0` = 永不过期，上限 10080 = 7 天） |

## 使用 / 命令

| 命令 | 说明 |
| --- | --- |
| `签到` | 今天签到（每天一次）；回执含本次积分、累计积分、连续天数与本群排名 |
| `我的签到` | 查看自己的累计积分、连续天数与最近签到日期 |
| `签到排行` | 本群积分前 `CHECKIN_RANK_SIZE` 名（图卡含头像与昵称） |

三条命令都只响应群消息，回复会 @ 发起人；群里还没人签到时，排行会提示「本群还没有人签到过」。

## 开发与测试

```bash
uv sync
uv run pytest -q                                        # 43 个用例
uv run ruff check . && uv run ruff format --check .     # 风格
uv run pyright                                          # 类型（strict）
uv run python scripts/mutation_check.py                 # 变异门禁：9 条，必须 9/9
```

源码在 `src/plugins/nonebot_plugin_checkin/`：`service.py` 是纯规则（无 IO，便于穷举）、
`store.py` 管 sqlite、`members.py` 管昵称与头像缓存、`render.py` 出图与文本回退、
`handle.py` 注册命令。改规则或存储行为时，请同步更新变异门禁里的锚点并重跑。

## 许可证与相关仓库

- 许可证：MIT，见 [LICENSE](LICENSE)。
- 本插件：[xinvxueyuan/nonebot-plugin-checkin](https://github.com/xinvxueyuan/nonebot-plugin-checkin)
- 宿主仓库：[xinvxueyuan/qbot](https://github.com/xinvxueyuan/qbot)
