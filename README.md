# nonebot-plugin-checkin

QQ 群每日签到：每天签一次、连续天数加成、积分累计、群内积分排行。

> 骨架阶段：命令与出图在后续版本接入。当前版本提供插件元数据与配置项。

## 安装

```bash
nb plugin install nonebot-plugin-checkin
```

或在 `pyproject.toml` 里加依赖后 `uv sync`。

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
| `CHECKIN_NICKNAME_TTL_MINUTES` | `30` | 昵称缓存时长（分钟，`0` = 永不过期） |
| `CHECKIN_AVATAR_TTL_MINUTES` | `30` | 头像缓存时长（分钟，`0` = 永不过期） |

## 许可

MIT
