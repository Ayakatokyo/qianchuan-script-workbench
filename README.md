# 千川素材脚本工作台

稳定 ID：`qianchuan-script-workbench`。先采集并汇总千川脚本事实，再按用户请求进入分析、生成或改写。

本目录是本技能的独立维护仓库；正式运行文件、配置、Schema 和依赖均在本仓。运行和打包不依赖项目管理工程或其他技能目录。

## 日常入口

- 业务流程和边界：[SKILL.md](SKILL.md)。
- 运行入口：`python3 scripts/run.py --help`。
- `acquire` / `continue-acquire` 到达 `ready` 或 `partialFailed` 后，自动校验并生成第一阶段报告 `overview/index.html`；`render-summary` 可离线恢复报告，完成后等待用户输入，不自动进入第二阶段。
- 独立回归：`python3 tools/test.py`；开发依赖见 `requirements-dev.txt`。
- 构建本包：`python3 tools/build.py`，输出 `dist/qianchuan-script-workbench.zip`。
- 可从任意工作目录执行打包器的绝对路径；`--dist-dir` 可指定新的本地产物目录。
- 正式发行清单：[packaging.json](packaging.json)，只包含显式列出的 65 个文件（其中 29 个 Python 文件）；ZIP 内保留 `qianchuan-script-workbench/` 根目录。

## 第一阶段报告

固定报表请求的 102 项原始指标已纳入本地选材和第二阶段分析注册表；`describe-acquire` 可列出字段，只有本次实际返回且通过来源校验的值才能用于分析。报告展示目录独立维护名称及分组。

未填写素材筛选与排序时，默认不加筛选、按整体消耗（`stat_cost_for_roi2`）降序选取详情素材；显式排序优先。

`overview/index.html` 是仅展示已采集详情素材的单页脚本工作台：折叠展示取数与选材条件、内容公式分布，主体并列展示素材列表、当前素材指标与完整正文、当前素材内容公式。一级柱图单行展示，二级环图和图例居中并按网格排列；点击公式步骤定位正文精确原句。页面不显示素材榜单、素材搜索/来源筛选；分布图下方另有横向占满页面的“内容公式与原句”区块，按一二级公式展示正文原句上下文并定位完整脚本；一二级公式分区显示，原句每页四条、桌面按 2×2 排列并可翻页。选材所用完整报表及指标继续保存在已核验事实、摘要与来源收据中。单素材“投放数据”保留元技能指定的八项可用默认指标，并可按当前素材自定义实际返回指标，优先使用平台 ValueStr。

报告使用已核验的落盘事实；只有精确命中所属正文的公式原句可用于定位。HTML 不展示脚本状态筛选/列、原始结构与身份来源折叠区，也不提供“完整性与缺口”页或顶部运行状态告示。结构字段、身份和来源证据继续保存在 summary 与 facts 等底层产物中，后台采集状态、身份校验、首批 CSV 门禁和第二阶段准入保持原约束。展示口径与兼容恢复见[输出契约](references/output-contract.md)。

## 维护与归属

[维护说明](MAINTENANCE.md)、[迁移记录](MIGRATION.md) 和 [逐文件来源](migration/source-manifest.json) 保存当前维护入口与拆分基线。`dev/legacy/`（若存在）保留未进入正式包的原有开发文件，仅用于历史回查，不参与运行或发行。

跨技能总体进度只维护在 [项目批次进度](../../项目管理/docs/AI短视频Skill开发批次进度.md)；设计、交接与历史文档见 [项目文档目录](../../项目管理/docs/README.md)。本仓不另建一份总进度。

## 依赖与运行数据

Python 3.11+；运行依赖见 requirements.txt（jsonschema）。 在线步骤需要宿主提供真实店铺/账号授权及千川报表或 RPA 连接器；运行时读取平台契约，不在仓库保存凭证。 模型分析/创作由支持该能力的宿主按 SKILL.md 执行；离线打包检查不代表模型或线上链路验收。

安装运行依赖可使用 `python3 -m pip install -r requirements.txt`。原始视频、客户数据、运行结果、模型与凭证不进入 Git 或 ZIP；每次执行的输出路径以 SKILL.md 为准。`dist/` 是可重建产物，不是编辑入口。

## 本次拆分验证

按原项目提交 `ab7e68049155336e774437f8e342e8f7c3272648` 的正式清单物化，运行文件原字节保留。新打包器在仓库外工作目录运行，所得 ZIP 与原发行器逐字节一致，CRC、清单与源码字节检查通过。产品测试结果另由本仓实际测试命令和集中交接记录说明，不由打包成功推断。

第二阶段指标来源已修复：新采集写入字段级报表引用；旧运行创建新分析时只读核验原快照并派生证据，不覆盖原事实。准备回执含指标可用数，发布与 verify 再核对来源。详见输入/输出契约。

## 第二阶段宿主报告交付（2026-09-29）

分析准备继续使用 `handoff-index.json` 的完整事实分页和 `result-template.json`；按业务问题读取所需页，保留原文、字段来源和哈希，复制模板到新结果文件再填写。`publish-analysis` 先校验结构化结果与证据，仅写 `host-report-handoff.json`，返回 `deliveryStatus=awaiting_host_report`；这不表示最终报告已交付。

当前对话宿主从已核验事实、原业务问题和必要的指标口径出发独立分析并组织报告。结构化结果用于审计重点主张，不规定报告的章节、结论数量、图表或叙事顺序；报告不必逐条复述结果卡。新增事实与计算须引用可核对的原字段和来源，推断、假设和建议须明确标注；需要更多同轮事实时使用现有读取或重新选择路径，不重新采集。按用户需求直接交付对话文本、Markdown 或 HTML；只有选择文件交付时才登记本地回执。

```bash
python "$SKILL_ROOT/scripts/run.py" analysis-page --analysis-root "$ANALYSIS_ROOT" --page 1
python "$SKILL_ROOT/scripts/run.py" analysis-status --analysis-root "$ANALYSIS_ROOT"
# 文件交付示例：把 report.md 放在 analysis-report/revisions/0001/ 后登记
python "$SKILL_ROOT/scripts/run.py" register-analysis-report --analysis-root "$ANALYSIS_ROOT" --revision 0001 --format markdown
# 同一分析下修订：保留 0001，在 revisions/0002/ 写新文件后登记
python "$SKILL_ROOT/scripts/run.py" register-analysis-report --analysis-root "$ANALYSIS_ROOT" --revision 0002 --format markdown
python "$SKILL_ROOT/scripts/run.py" analysis-status --analysis-root "$ANALYSIS_ROOT"
```

登记前重新核对分析结果、来源及交接哈希；文件交付支持 `index.html`、`report.md` 或 `report.txt`，分别用 `--format html|markdown|text`。登记时检查正文非空、HTML/CSS/Markdown 本地资源可用且不越出该版目录，记录输入及每个输出文件 SHA-256。`deliveryStatus=completed`、`reportVerified=true` 表示本地文件通过完整性校验，不代替事实解释、视觉观感或用户验收。展示修改在同一分析下新增递增的四位 revision，旧文件和旧收据保持不变；涉及新事实的实质修订先用既有事实读取与选择路径核验，并更新相应审计结果或建立新分析，无需重跑采集。旧版无 revision 的宿主 HTML 可继续校验。历史固定报告的 v1 收据只读核验，标为 `legacy_completed`。阶段一固定素材汇总报告不变。宿主报告制作耗时单独记录。
