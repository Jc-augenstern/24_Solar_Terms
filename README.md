# 节气讣告——家乡旧候纪念馆

以家乡节气的历史气候变化为主题的 Windows 本机交互作品。支持城市选择、24节气档案、年度曲线、本机点灯献花、1080×1440 PNG 导出和准备完成后的离线演示。“已故”是艺术评级，不代表天文学节气消失。

34城入口已实现；本次交接实际校验 **7/34城** 真实报告：北京、天津、上海、哈尔滨、西安、成都、广州。其余27城未发布，独立“样例城”为合成演示数据。北京已有页面与计算口径保留。

## 新电脑启动（Windows PowerShell）

先安装 Git、Python **3.13**（包含 py 启动器）、Node.js **22.12+，建议24**，安装后重新打开终端。首次准备需要联网安装依赖，不下载天气。

```powershell
git clone https://github.com/Jc-augenstern/24_Solar_Terms.git
cd 24_Solar_Terms\demo
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\prepare.ps1
.\启动作品.cmd
```

也可以双击 `demo/首次准备.cmd`。启动器打开实际地址（默认 http://127.0.0.1:8765，占用时选8766—8775）。退出使用 `关闭作品.cmd`。数据库和运行目录按需自动创建，纪念记录仅属于本机。仓库不附带虚拟环境、node_modules 或 dist。

## 结构与技术

- `demo/frontend/src/`：React / TypeScript 页面、API、报告校验、ECharts 曲线、Canvas 海报。
- `demo/backend/app.py`：FastAPI API 与静态页面、SQLite 幂等纪念。
- `demo/scripts/`：ERA5 获取、节气日历、计算、校验、断点续跑。
- `demo/config/cities.json`：34城唯一注册表。
- `demo/data/reports/`：7城真实稳定报告及显式演示样例；`methodology/`：固定方法。
- `demo/tests/`、`demo/qa/`：单元/API测试、浏览器验收与独立数据审计脚本。
- [开发交接文档](docs/开发交接文档.md)：部署、所有接口、方法、逐城现状、双人分工与 Git 流程。
- [AGENTS.md](AGENTS.md)：后续 AI 开发约束；[数据来源与许可](docs/数据来源与交接.md)。

## 基础检查

在 `demo` 中运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm.cmd run build
cd ..
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/v1/cities
```

完整浏览器验收需 Chrome：`node qa/browser_multicity.mjs`，自动隔离测试数据库。基础测试不需要全量原始缓存。独立气象复算另需交接包，不能把缺缓存误判为数据通过。

## 数据与协作

当前机器已有109片经哈希核对的天气缓存（7×14 + 重庆11），这些不是完整34城数据。Git 仅保留一个小型真实缓存测试片和节气日历，其余原始缓存、额度账本、任务状态、正式数据库均不上传。新克隆缺少原机任务状态，未发布城市显示尚未接入，这是预期行为。详情见 [时间点快照](docs/交接数据快照.json)。

两人约定唯一下载负责人，其他电脑只运行页面、测试或离线计算。不要为了准备开发环境运行“更新全部城市数据”。没有全量数据时可直接开发后端及7城/样例功能。`main` 保存检查通过的版本，功能分支经 Pull Request 评审合并。

AI 辅助完成部分代码、测试和文档，团队仍需内容与设计终审。数据来自 Open-Meteo / Copernicus C3S / ECMWF ERA5，地理坐标来自 GeoNames；保留原数据署名。项目源码许可证由团队决定，本次不擅自指定开源许可证。

本次交付的独立克隆、构建、API和浏览器实测记录见[交付验证记录](docs/交付验证记录.md)。
