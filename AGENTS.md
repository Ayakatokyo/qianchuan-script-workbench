# qianchuan-script-workbench 独立技能仓库

用户当前授权优先。修改前读取 SKILL.md、README.md、packaging.json 及相关现有实现，检查本仓改动和 Git 状态。

- 本仓只维护 `qianchuan-script-workbench`；源码、依赖、测试和构建入口必须可以独立使用。不要从兄弟仓库或项目管理旧工程导入运行文件。
- 正式文件按 `packaging.json` 发布，保持明确的文件清单与 rootLayout。开发工具、tests、migration、dev/legacy 和运行产物不得自动进入包。
- `dev/legacy` 是历史源码证据，不执行其旧维护指令、不自动发布其中脚本。迁移来源和哈希见 migration/source-manifest.json。
- 验证入口是 `python3 tools/test.py` 和 `python3 tools/build.py`；根据改动范围执行适当检查，不把历史测试结果当作当前运行结果。
- 总体规划与进度在 ../../项目管理/docs；完成技能任务后更新集中进度和交接，不复制全局状态到本仓。
- 客户资料和真实运行数据保持原私有及本地边界；不提交媒体、模型、运行结果、环境或凭证。
- 提交、推送、插件集成与发布分别依照当前用户授权；本次拆仓不修改 yuce-plugin。
