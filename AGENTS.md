# 项目开发约束

- 应用根目录是 `demo/`；先读根 README、docs/开发交接文档.md 和 demo/CONTRACT.md。
- Windows + Python 3.13 + Node 22.12+；准备：在 demo 执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\prepare.ps1`。启动/关闭用对应 cmd；前端开发在 frontend 执行 npm run dev（后端默认8765）。
- 基础验证：demo 中 `.venv\Scripts\python.exe -m pytest tests -q`；frontend 中 `npm.cmd run build`。影响交互时运行 `node qa/browser_multicity.mjs`（需Chrome，测试库隔离）。
- 保留北京已认可视觉、34城选择、明确样例标识、曲线、跨城隔离、SQLite幂等、PNG导出和离线机制。不得无理由重构。
- 方法v0.1、schema 1.0：ERA5；1961—1990 vs 1996—2025；北京时间日窗口；权重0.60/0.25/0.15；有效日90%、各期27年。未经明确方法变更任务不得改口径或静默覆盖北京结果。
- 严禁重置真实报告、raw缓存、batch_tasks.json、request_budget.json、正式SQLite。正常问题排查和测试不得自动启动34城批量下载。
- 下载必须由团队指定唯一负责人；本机锁不跨电脑。使用完整缓存和 --offline；网络更新需明确数据任务授权。
- 测试通过 create_app 的 db_path 或 DEMO_DB_PATH、DEMO_STATE_DIR 指向临时目录。不要测试正式数据库。
- 提交前检查实际暂存内容；不得提交密钥、运行状态令牌、私人路径证据、原始大文件、依赖目录及正式数据库。更新报告先稳定快照、校验和SHA256。
- 源码许可证待团队决定；保留数据来源和第三方许可。
