# 维护说明

- 本包是“千川素材脚本工作台”的独立发行入口，运行时所需采集、生成、改写、Schema 与分析模块都必须进入自身 allowlist；不得跨包导入旧生成/改写 Skill 的安装路径。
- 两个旧 Skill `qianchuan-reference-script-generation` 和 `qianchuan-reference-script-rewrite` 保留独立目录、独立入口、独立 manifest 和既有 schema 契约。此包的入口/报告/工作流扩展不得回写它们的历史产物。
- `workbench_reporting.py` 只能投影通过 `verify` 的千川 source pack；报告与交接均以内容哈希绑定。禁止在此阶段执行第二次报表、RPA、媒体下载、ASR/OCR/VLM 或生成模型。
- `workbench_analysis.py` 负责阶段二计划、字段范围、来源、输入哈希和模型结果验证。业务分析语义交给宿主模型，输出需要证据引用；语义上的效果归因、跨样本规律或客户事实仍需人工审核。
- 变更采集字段、metric field registry 或 source-pack 字段时，更新新包及旧包各自的 schemas/manifest，并保留 text-only 旧 source pack 可读。
- 所有运行目录和客户数据放在包外的 `千川素材脚本数据/run-<runId>/`。禁止将 CSV、凭证、视频、客户事实文件或 run 产物加入 Git 或 ZIP。
- 发行前构建新包、生成/改写旧包并独立解包验证；在线报表/RPA 只在用户授权的运行中执行，离线模拟不得冒充线上成功。
