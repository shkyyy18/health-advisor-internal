# 健康顾问（Health Advisor）

**面向骑行爱好者及其他运动爱好者，将 Strava 运动记录与自己的健康数据结合分析的本地优先工具。**

**A local-first tool for cyclists and other sports enthusiasts to analyze Strava activities alongside their own health data.**

Strava 记录了“练了什么”，体重、体脂、睡眠、心率和饮食记录则补充“身体状态如何”。健康顾问希望把这些分散的数据放在一起，帮助用户理解训练负荷、恢复状态与身体变化之间的关系，辅助安排训练、恢复和饮食。

> **核心人群是使用 Strava、希望结合自身健康数据进行分析的骑行爱好者，并兼顾有同类需求的其他运动爱好者。** 减脂和体重管理是其中的应用场景，不是唯一定位；本项目不是泛人群健康咨询平台，也不是单纯的数据采集工具。

## 演示素材

本次干净发行版暂不附带旧截图。后续仅接收具有可复现合成数据来源、经人工复核的演示素材。

## 目标用户

- **骑行爱好者（核心人群）：**在 Strava 记录骑行，希望把活动记录与自己的睡眠、心率、体重和体脂等数据结合起来看，而不只关注单次里程和速度；
- **其他运动爱好者：**在 Strava 记录跑步等运动，同样需要综合理解训练、恢复和身体变化；
- **有多源数据整合需求的人：**运动记录和健康数据分散在不同应用中，希望在一个本地看板内统一分析；
- **重视隐私、接受本地部署的人：**希望自己掌握个人数据的存储与访问权限。

**当前适配范围：**运动数据接入 Strava，设备健康数据通过 Mi Fitness Data Bridge 接入小米生态，饮食支持手工或可选照片辅助记录。这不代表已支持所有品牌设备或具备各运动项目的专项训练模型。照片分析需显式配置外部接口，使用时餐食图片会发送到该接口；本地优先不等于所有功能都不访问外部服务。

当前不是医疗诊断工具、通用医院健康平台或多人 SaaS，也不承诺自动、无误差地识别所有饮食。

## 真正要解决的问题

**单独看 Strava 活动，或单独看体重、睡眠等健康指标，都难以完整理解训练与身体状态。** 本项目的核心是联动分析，而不是再增加一个孤立的数据看板。

围绕这个目标，重点帮助用户观察：

- 近期运动量与睡眠、恢复状态放在一起看，有哪些值得留意的变化；
- 体重、体脂趋势与训练、饮食记录是否呈现一致或相反的变化；
- 数据是否足够支持下一步训练、恢复和饮食调整，哪些信息仍然缺失。

这些是基于已有记录的辅助分析，不把相关性当成因果，也不承诺竞技表现提升。当前功能重点是训练负荷、恢复、体重/体脂趋势和饮食记录；减脂是这些能力的一种应用场景。

为补充饮食信息，项目提供两种记录路径：

1. **快速手工记录：**食物描述必填，热量和营养素不知道就留空，不强迫用户编数字；
2. **照片辅助记录：**配置图片分析接口（`MEAL_LLM_API_KEY`）后，估算餐食组成并保留不确定性说明。

看板展示近 7 天饮食记录覆盖天数、条数和数据置信度。数据不足时只给目标，不假装能判断真实摄入。

## 核心能力

- 汇总小米体脂、睡眠、步数、心率、SpO2 和压力数据；
- 同步 Strava 活动、训练量与近期强度；
- 计算恢复状态、训练负荷、体重和体脂趋势；
- 快速手工记录或照片辅助记录饮食；
- 生成可解释的训练、饮食和恢复建议；
- 所有个人数据默认保存在本地 SQLite；服务绑定 `0.0.0.0` 以便手机局域网访问，非本机来源一律要求访问令牌（见下文"隐私与安全"）。

## 与 Mi Fitness Data Bridge 的关系

小米连接器已经拆分为独立项目：[Mi Fitness Data Bridge（Mi Fitness 数据桥）](https://github.com/shkyyy18/mi_fitness_data_bridge)。

- **Mi Fitness Data Bridge（Mi Fitness 数据桥）：**帮助用户拥有、导出和复用自己的小米健康数据；
- **Health Advisor：**面向骑行及其他运动爱好者，把 Strava、个人健康和饮食数据组合起来，辅助理解训练、恢复与身体变化；减脂是应用场景之一。

本项目不再复制或 vendor 小米连接器源码。桥接器是唯一连接器实现，健康顾问只把它作为数据源依赖。

## 架构

```text
Mi Fitness Data Bridge ─┐
                        ├─> 本地 SQLite ─> 可解释分析 ─> 每周行动建议
Strava API ─────────────┤
手工/照片饮食记录 ─────┘
```

- **Connector layer：**Mi Fitness Data Bridge、Strava；
- **Storage layer：**`data/health.db`，同一时间只允许一个写入者；
- **Analysis layer：**恢复、训练负荷、体重/体脂趋势、饮食覆盖度；
- **Presentation layer：**FastAPI 本地看板和手机饮食记录页。

## 安装

推荐把两个仓库放在同一个父目录：

```powershell
cd <your-projects-directory>
git clone https://github.com/shkyyy18/mi_fitness_data_bridge.git mi_fitness_data_bridge
git clone https://github.com/shkyyy18/health-advisor-internal.git health-advisor-internal
cd health-advisor-internal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ..\mi_fitness_data_bridge
pip install -e ".[dev,xiaomi]"
```

> 本目录是代码发布版本，不包含维护者个人资料、健康数据库、个人项目记忆或原开发历史。个人配置与运行数据仅保存在本地。

复制 `.env.example` 为 `.env`，填写本地配置，然后运行：

```powershell
.\run.ps1
```

本地看板：`http://127.0.0.1:8000/`

Windows 启动入口和计划任务安装器优先使用项目 `.venv\Scripts\python.exe`，不存在时回退到 PATH 中的 Python。VBS 负责隐藏窗口，使用 `python.exe` 保留标准输出/错误及失败退出码。安装器修改或卸载已有计划任务前会备份 XML 到 `logs/task-backups/`；本次代码审计没有修改机器上的现有计划任务。

Public tunnels are **disabled by default**. The startup script only attempts to launch ngrok when `.env` explicitly contains `HEALTH_ENABLE_NGROK=true` and authentication, privacy, exposed routes, and log handling have been reviewed separately. Keep the value `false` for normal local use; a configured Strava callback URL alone must never enable public access.

## 首次连接小米

桥接器提供健康数据读取接口；当前二维码登录辅助脚本仍由本项目的 `mijiaAPI` 可选依赖提供：

```powershell
python scripts\mijia_health_sync.py login
python scripts\mijia_health_sync.py doctor
python scripts\mijia_health_sync.py sync
```

登录文件位于 `data\.mijia\auth.json`，包含敏感 token，不得上传、打印或分享。

## 每日自动同步

安装后，计划任务 `HealthAssistantDailySync` 每天 08:10 和 21:40 自动运行 `scripts\daily_sync.py`：通过本地服务接口同步小米 Mi Fitness（睡眠、体成分、日常指标）和 Strava 活动，结果写入 `logs\daily_sync.log`，任务返回码非 0 表示有失败项。`StartWhenAvailable` 会在开机后补跑错过的同步。

安装或卸载：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_sync_task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_sync_task.ps1 -Uninstall
```

手工同步一次：`python scripts\daily_sync.py`。小米 token 过期时同步会失败，需要重新执行 `python scripts\mijia_health_sync.py login`。

## 饮食记录

打开 `http://127.0.0.1:8000/mobile`：

- 先查看今日联动教练、训练/恢复动作和随训练变化的一日菜单；
- 不配置图片分析接口也可以手工记录；
- 配置 `MEAL_LLM_API_KEY` 后可以上传餐食照片辅助估算（接口与模型见 `.env.example`）；
- 原始照片不会写入本地数据库，只保存文字分析和营养估算；
- 手工和照片估算都不是实验室测量，建议优先记录“吃了什么和份量”，再逐步提高数字精度。

## 测试

```powershell
python -m pytest -q -p no:cacheprovider
python -m py_compile app\analytics.py app\db.py app\main.py app\xiaomi_sync.py
```

测试会在导入应用前隔离配置与 LAN 令牌，并把数据库切换到临时目录，不加载工作目录中的真实 `.env` 或读写真实的 `data/health.db`。独立验证时可设置 `HEALTH_ENV_FILE` 指向专用配置文件；默认仍加载项目 `.env`。

2026-09-07（Windows / Python 3.14）验证：**88 passed，1 条第三方 TestClient 弃用警告**。覆盖小米/Strava/图片分析 mock、饮食记录、看板、访问控制以及 Windows 启动脚本。wheel 构建及隔离安装启动通过，首页、移动页、汇总接口和静态资源返回 200，合成饮食记录写入成功。没有同步记录时显示“尚未同步”，不把数据库文件修改时间冒充同步时间。

**验证边界：**真实小米登录/同步、Strava OAuth 授权和外部餐食图片接口尚未完成本轮实账号端到端验收；不应将 mock 通过表述为所有云端流程已经跑通。

## 隐私与安全

以下内容均被 Git 忽略，禁止提交：

- `.env`、访问 token、登录文件；
- SQLite 数据库、导出数据；
- 健康日志、餐食照片、运行日志；
- 包含真实个人指标的截图和测试夹具。

局域网查看健康页面/API 时，使用 `HEALTH_LAN_TOKEN` 或本机生成的 `data/lan_token.txt` 中令牌（查询参数 `token` 或请求头 `X-LAN-Token`）；不得把含令牌的地址或文件上传。静态资源无需令牌，本机回环访问免令牌；显式开启的公网隧道另走受限路由及访问验证。仅需本机使用时可直接运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。

详见 `SECURITY.md`。

## 项目边界

- 内容用于个人运动和体重管理，不替代医生、注册营养师或持证教练的个体化评估；
- 不生成诊断或治疗建议；
- 不把历史观测最高心率冒充实验室最大心率；
- 数据不足时必须明确降低结论置信度。

## GitHub 双项目实验

桥接器和完整健康顾问都可以独立发布，由真实用户选择价值：

- Star 衡量传播；
- 安装、成功同步、Issue 和 PR 衡量生态价值；
- 7 天饮食记录、周报生成、4 周留存和建议执行衡量问题是否真正被解决。

公开版本只包含通用软件；用户活动记录与个人经营实验不随软件发布。

## 发布

版本变更见 `CHANGELOG.md`，GitHub 发布、服务切换和产品实验检查见 `docs/release-checklist.md`。

## License

MIT，见 `LICENSE`。第三方依赖和来源说明见 `THIRD_PARTY_NOTICES.md`。

## Windows 扫码、重新登录与无终端看板

这条流程把**登录成功**和**同步成功**分开验证；有 `auth.json` 并不代表健康数据已经同步。

### 首次准备（在项目目录执行）

已按上方步骤创建 `.venv` 并把数据桥仓库放在同级目录后，安装两种独立组件：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[xiaomi]' -e ..\mi_fitness_data_bridge
```

- `mijiaAPI` / `qrcode`：负责小米账号二维码登录。
- `mi_fitness_data_bridge`：负责读取运动健康数据。只安装扫码组件仍然不能同步健康数据。

### 扫码登录

```powershell
.\.venv\Scripts\python.exe scripts\mijia_health_sync.py login
```

需要登录时，程序先生成 `data\.mijia\login_qr.png`，再立即调用系统图片查看器，随后等待扫码。使用**米家 App**，登录与“小米运动健康”相同的小米账号，扫码并确认；保持登录进程运行，等待成功提示。

- 不复制二维码到桌面。
- 如果没有图片窗口，终端会显示原图路径，可手动打开。
- 已有登录可复用时，不重复弹二维码。
- 二维码和登录文件都属于敏感本地数据，不应上传或分享。

### 需要重新扫码时

```powershell
.\.venv\Scripts\python.exe scripts\mijia_health_sync.py login --reset-login
```

该命令仅将旧 `auth.json` 重命名为同目录的带时间戳备份，再申请新二维码；**不清空健康数据库、不修改 Strava 配置**。备份仍包含敏感凭据，只保留在 Git 忽略的本地 `data/` 中。登录失败不会伪报同步完成。

### 同步并检查结果

若看板已运行，登录成功后通过同一个后台同步，避免同时启动另一个数据库写入进程：

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/sync/xiaomi' -TimeoutSec 600
```

请求完成后刷新看板核对数据。若返回缺少连接器、鉴权失败或网络错误，应先处理对应错误，不应仅因没有数据就删除数据库。只有在看板和其他同步任务均停止时，才使用前文的独立 `sync` 命令。

### 日常打开看板（不显示终端）

双击 `scripts\run_healthboard.vbs`，或创建指向它的桌面快捷方式。该入口隐藏启动后台、打开浏览器，并尝试同步；失败不会阻止查看已有数据，可查 `logs/open_dashboard.log`。浏览器普通刷新只重新加载页面，不等同于云端同步成功。

Strava 仍需单独配置 Client ID / Client Secret 并完成浏览器授权。修改 `.env` 后，旧服务不会自动读取新值，必须重启真正监听 8000 端口的进程，而不只是其 Windows 虚拟环境父进程。小米重新扫码不会修复 Strava 配置问题。

**验证边界：**二维码展示顺序、查看器失败提示、登录备份及无终端启动已覆盖隔离回归测试；用户实账号的云端授权和最新数据是否齐全，仍应以实际同步结果为准。
