# Changelog

## [0.2.0] - 2026-11-19

### Added

- **设计系统**：两张图卡改用统一的半透光（glass）材质——半透明卡体 +
  `backdrop-filter: blur(40px) saturate(180%)` 磨砂透光、1px 高光描边、双层外阴影、
  左侧粗体标签 / 右侧玻璃胶囊值、细横分隔线、底部斜体引用。
  新增 `theme.py` 承载设计 token 与骨架，`render.py` 只做数据装配。
- **随机背景图**：从自建 xbm 随机图 API 取图，**按人缓存 15 分钟**独立轮换；
  落盘前统一转 **WebP**（q=80、长边 ≤800），体积约为原始 JPEG 的 1/3。
  新增 `assets.py`。
- **真实个性签名**：底部引用取发起人的 QQ 个性签名（`get_stranger_info` 的 `long_nick`），缓存 1 天。
- **`PLAYWRIGHT_BROWSERS_PATH` 自动注入**：新增 `envbridge.py`，启动钩子把 `.env` 里的该键
  桥接进 `os.environ`（nonebot 只把它读进 `driver.config`，而 Playwright 只认环境变量）。
  已有真实环境变量（systemd `Environment=`）优先，不覆盖。**运维只需改 `.env`，无需碰 systemd。**
- 新增 7 个配置项：`CHECKIN_BG_URL`、`CHECKIN_BG_API_KEY`、`CHECKIN_BG_TTL_MINUTES`、
  `CHECKIN_BG_TIMEOUT_SECONDS`、`CHECKIN_QUOTE_TTL_MINUTES`、`CHECKIN_QUOTE_MAX_CHARS`、
  `PLAYWRIGHT_BROWSERS_PATH`。
- 新增依赖 `pillow>=11.0.0`（WebP 转换；Pillow 自带 libwebp，无需系统包）。

### Changed

- 签到卡视口 520×360 → 612×700；排行卡 560×(120+64N) → 612×(230+57N)。
- 签到卡信息层级：标题 → 头像 → 5 行（昵称 / 今日积分 / 总积分 / 连续天数 / 本群排名）→ 引用。
- 存储新增 `checkin_signatures` 表（按群+人的签名缓存）。

### Fixed

- 背景图/签名/头像任一失败时，不再影响签到命令（各降级路径均不写负缓存）。

### Tests

- 用例 43 → **81**；变异门禁 9 → **12** 条（新增 M10 WebP 转换、M11 取图失败负缓存、M12 空引用区）。

## [0.1.0] - 2026-10-22

### Added

- 三条群命令：`签到`（每日一次，回执含本次积分、累计积分、连续天数与群内排名）、
  `我的签到`（累计积分 / 连续天数 / 最近签到日期）、`签到排行`（积分前 N 名，图卡含头像与昵称）。
- 签到规则：连续签到加成、加成封顶、断签重置为 1；同日幂等由纯逻辑与 `checkin_log` 主键双重保证。
- 存储：stdlib `sqlite3`，库文件与头像缓存落在 `nonebot-plugin-localstore` 的插件数据目录；
  启动钩子幂等建表。
- 缓存：昵称存库（TTL）、头像落盘（按文件 mtime 判 TTL）；下载失败不写负缓存。
- 出图：htmlrender 渲染签到卡与排行卡，渲染不可用自动回退等价纯文本。
- 配置：10 个 `CHECKIN_*` 配置项（积分 / 加成 / 封顶 / 排行人数 / 三条命令词 / 时区 / 昵称与头像 TTL）。
- 测试：43 个用例（含真渲染出 PNG）与 9 条变异门禁（`scripts/mutation_check.py`，捕获 9/9）。
