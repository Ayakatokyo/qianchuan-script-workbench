# 千川素材脚本工作台

稳定 ID：`qianchuan-script-workbench`。先采集并汇总千川脚本事实，再按用户请求进入分析、生成或改写。

本目录是本技能的独立维护仓库；正式运行文件、配置、Schema 和依赖均在本仓。运行和打包不依赖项目管理工程或其他技能目录。

## 日常入口

- 业务流程和边界：[SKILL.md](SKILL.md)。
- 运行入口：`python3 scripts/run.py --help`。
- 独立回归：`python3 tools/test.py`；开发依赖见 `requirements-dev.txt`。
- 构建本包：`python3 tools/build.py`，输出 `dist/qianchuan-script-workbench.zip`。
- 可从任意工作目录执行打包器的绝对路径；`--dist-dir` 可指定新的本地产物目录。
- 正式发行清单：[packaging.json](packaging.json)，只包含显式列出的 60 个文件；ZIP 内保留 `qianchuan-script-workbench/` 根目录。

## 维护与归属

[维护说明](MAINTENANCE.md)、[迁移记录](MIGRATION.md) 和 [逐文件来源](migration/source-manifest.json) 保存当前维护入口与拆分基线。`dev/legacy/`（若存在）保留未进入正式包的原有开发文件，仅用于历史回查，不参与运行或发行。

跨技能总体进度只维护在 [项目批次进度](../../项目管理/docs/AI短视频Skill开发批次进度.md)；设计、交接与历史文档见 [项目文档目录](../../项目管理/docs/README.md)。本仓不另建一份总进度。

## 依赖与运行数据

Python 3.11+；运行依赖见 requirements.txt（jsonschema）。 在线步骤需要宿主提供真实店铺/账号授权及千川报表或 RPA 连接器；运行时读取平台契约，不在仓库保存凭证。 模型分析/创作由支持该能力的宿主按 SKILL.md 执行；离线打包检查不代表模型或线上链路验收。

安装运行依赖可使用 `python3 -m pip install -r requirements.txt`。原始视频、客户数据、运行结果、模型与凭证不进入 Git 或 ZIP；每次执行的输出路径以 SKILL.md 为准。`dist/` 是可重建产物，不是编辑入口。

## 本次拆分验证

按原项目提交 `ab7e68049155336e774437f8e342e8f7c3272648` 的正式清单物化，运行文件原字节保留。新打包器在仓库外工作目录运行，所得 ZIP 与原发行器逐字节一致，CRC、清单与源码字节检查通过。产品测试结果另由本仓实际测试命令和集中交接记录说明，不由打包成功推断。
