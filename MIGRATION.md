# 独立仓库拆分记录

日期：2026-09-25。技能：`qianchuan-script-workbench`。

## 来源与历史

本仓从原规划项目 `Ayakatokyo/qianchuan-yuntu-ai-short-video-skills` 提交 `ab7e68049155336e774437f8e342e8f7c3272648` 物化。来源工程为 `develop/ai-short-video-skills`，技能原目录为 `skills/qianchuan-script-workbench`，原打包清单为 `packaging/qianchuan-script-workbench.json`。本次逐文件核对了对应 Git 提交内容。

这是保留内容与来源映射的快照拆分，**没有过滤出完整的逐技能 Git 历史**。原项目完整历史、批次设计、进度和交接继续由 [项目管理仓库](../../项目管理/README.md) 保留；历史回查使用上述 commit 与原仓相对路径。是否已创建本仓初始提交或远端，以实际 Git 状态为准。

## 文件保全

- 正式清单的 57 个文件按 source → destination 物化，配置、Schema 与依赖声明随本包完整带入；业务运行字节未改动。
- 本技能没有清单外原有非缓存文件；无需创建历史脚本副本。
- 缓存文件排除清单记录在 [source-manifest.json](migration/source-manifest.json)；原始客户数据、视频、模型、虚拟环境与运行目录未迁入新仓。
- 本包原 MAINTENANCE.md 已在正式发行清单中，根文件原字节保留；新的仓库入口说明写在 README.md 和本记录，不改变发行包。
- `packaging.json` 保存原 rootLayout 与 entrypoint，文件 source/destination 改为本仓相对路径；原清单完整内容与每个文件的原路径、目标、SHA-256 同时保存在来源映射。

## 独立构建验证

`tools/build.py` 从原显式清单构建器派生，仅适配本仓 scripts 布局与单包默认入口，并增加 CRC/清单/源码字节复核。无项目管理工程或兄弟仓库运行依赖。

- 在仓库外工作目录执行本仓构建入口：通过。
- 新 ZIP 与原发行器 ZIP：逐字节一致。
- CRC、正式清单精确集合、各文件源码字节：通过。
- 布局：ZIP 内保留 `qianchuan-script-workbench/` 根目录。
- 初始 ZIP SHA-256：`92f5e0b9e61384fa7b3f982ca8279324d4ea8b3ef2e599658d38f8d058de98be`。

本记录只证明拆分与构建保真；独立产品回归由 `python3 tools/test.py` 另行记录，线上 RPA、视频采集、模型与市场发布不在本次构建验证结论内。
