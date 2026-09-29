# 维护说明

- 本包是“千川素材脚本工作台”的独立发行入口，运行时所需采集、生成、改写、Schema 与分析模块都必须进入自身 allowlist；不得跨包导入旧生成/改写 Skill 的安装路径。
- `qianchuan-reference-script-generation` 和 `qianchuan-reference-script-rewrite` 已退役；新的创作、改写都通过本包 `prepare-generation` / `publish-generation` 与 `prepare-rewrite` / `publish-rewrite`，绑定同一运行的已核验交接。历史产物仍按原字节保留，不原地改写或自动迁移。
- `workbench_reporting.py` 只能投影通过 `verify` 的千川 source pack；报告与交接均以内容哈希绑定。禁止在此阶段执行第二次报表、RPA、媒体下载、ASR/OCR/VLM 或生成模型。
- `workbench_analysis.py` 负责阶段二计划、字段范围、来源、输入哈希和模型结果验证。业务分析语义交给宿主模型，输出需要证据引用；语义上的效果归因、跨样本规律或客户事实仍需人工审核。
- 变更采集字段、metric field registry 或 source-pack 字段时，更新本包的 Schema/manifest，并保留可用的 text-only 历史 source pack 读取规则；旧独立包已退役，不再同步维护。
- 所有运行目录和客户数据放在包外的 `千川素材脚本数据/run-<runId>/`。禁止将 CSV、凭证、视频、客户事实文件或 run 产物加入 Git 或 ZIP。
- 详情首批门禁在实际调度器和低层提交许可处执行，`first-batch-csv-gate.json` 的暂停不可被续跑清除；更新时同步 CLI、状态/结果 Schema 和行为测试。新派生包须同步五字段的表单/入参映射、实时 T+2 校验、授权关系和同等熔断，不能只复制 SKILL 文字或导入兄弟仓模块。
- 发行前构建并独立解包验证本包的取数、分析、生成与改写运行闭包；在线报表/RPA 只在用户授权的运行中执行，离线模拟不得冒充线上成功。
