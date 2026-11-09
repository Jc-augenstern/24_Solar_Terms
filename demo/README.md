# 应用目录

新电脑完整步骤、当前数据状态与协作规则见[仓库README](../README.md)及[开发交接文档](../docs/开发交接文档.md)。本目录是实际应用根目录，所有Python和cmd入口从这里运行。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\prepare.ps1
.\启动作品.cmd
# 完成后
.\关闭作品.cmd
```

当前交接包含7城真实报告及明确标注的样例，34城全部真实数据尚未完成。首次准备只安装依赖和构建前端，不启动天气下载。原开发/验收记录保留为历史记录，相关截图和原始缓存留在原机。
