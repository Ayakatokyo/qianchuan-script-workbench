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
- 正式发行清单：[packaging.json](packaging.json)，只包含显式列出的 66 个文件（其中 30 个 Python 文件）；ZIP 内保留 `qianchuan-script-workbench/` 根目录。

## 第一阶段报告

固定报表请求的 102 项原始指标已纳入本地选材和第二阶段分析注册表；`describe-acquire` 可列出字段，只有本次实际返回且通过来源校验的值才能用于分析。报告展示目录独立维护名称及分组。

`overview/index.html` 提供素材筛选条件、素材榜单、脚本内容公式、单素材脚本、脚本片段库五个页签。榜单展示本次已验证完整报表的全部素材（不限于 TopN 脚本采集素材），支持标题/ID 搜索、排序和每页 10 条分页；名称与 ID 固定，自定义指标面板支持分组、搜索、勾选、移除、调整顺序和恢复默认，仅提供本次快照实际返回的指标。榜单默认指标按千川元技能顺序取本次实际返回的综合成本、净成交 ROI、净成交金额；缺失的素材基础字段不补造。素材筛选条件不展示“筛选条件与排序字段”技术区；“千次曝光成本”在报告中统一显示为“整体千次展现费用”。内容公式按素材去重，通过一级柱状图下钻二级环图，图例与环图联动；单素材“投放数据”默认显示元技能指定的八项可用指标，其他当前素材已返回指标可按素材独立选择，优先保留平台 ValueStr。单素材还保留一级/二级步骤顺序、箭头和对应颜色，公式与原文精确引用双向定位，并可复制公式或完整文案。片段库用两组可点击标签及片段数选择一级/二级，支持关键词筛选，每页 12 条，可复制原句并跳转完整脚本。

报告使用已核验的落盘事实，片段必须精确命中所属素材正文；只有明细而无公式映射的原句保留为未分类。HTML 不展示脚本状态筛选/列、原始结构与身份来源折叠区，也不提供“完整性与缺口”页或顶部运行状态告示。结构字段、身份和来源证据继续保存在 summary 与 facts 等底层产物中，后台采集状态、身份校验、首批 CSV 门禁和第二阶段准入保持原约束。展示口径与兼容恢复见[输出契约](references/output-contract.md)。

## 维护与归属

[维护说明](MAINTENANCE.md)、[迁移记录](MIGRATION.md) 和 [逐文件来源](migration/source-manifest.json) 保存当前维护入口与拆分基线。`dev/legacy/`（若存在）保留未进入正式包的原有开发文件，仅用于历史回查，不参与运行或发行。

跨技能总体进度只维护在 [项目批次进度](../../项目管理/docs/AI短视频Skill开发批次进度.md)；设计、交接与历史文档见 [项目文档目录](../../项目管理/docs/README.md)。本仓不另建一份总进度。

## 依赖与运行数据

Python 3.11+；运行依赖见 requirements.txt（jsonschema）。 在线步骤需要宿主提供真实店铺/账号授权及千川报表或 RPA 连接器；运行时读取平台契约，不在仓库保存凭证。 模型分析/创作由支持该能力的宿主按 SKILL.md 执行；离线打包检查不代表模型或线上链路验收。

安装运行依赖可使用 `python3 -m pip install -r requirements.txt`。原始视频、客户数据、运行结果、模型与凭证不进入 Git 或 ZIP；每次执行的输出路径以 SKILL.md 为准。`dist/` 是可重建产物，不是编辑入口。

## 本次拆分验证

按原项目提交 `ab7e68049155336e774437f8e342e8f7c3272648` 的正式清单物化，运行文件原字节保留。新打包器在仓库外工作目录运行，所得 ZIP 与原发行器逐字节一致，CRC、清单与源码字节检查通过。产品测试结果另由本仓实际测试命令和集中交接记录说明，不由打包成功推断。

第二阶段指标来源已修复：新采集写入字段级报表引用；旧运行创建新分析时只读核验原快照并派生证据，不覆盖原事实。准备回执含指标可用数，发布与 verify 再核对来源。详见输入/输出契约。

## 第二优先级：稳定分析交接与正式交付

分析准备完成后，先读返回的 `handoff-index.json`：其中列出全部事实页、输入 SHA-256、记录数量、缺口和结果模板。每页最多五条完整记录，保留全文与来源；不得自行截断正文或重排云图原始 fact_ref 下标。按问题选择的完整范围读完所需分页后，将 `result-template.json` **复制到另一个结果文件**，填写结论及证据；空白模板不能提交为完成结果。事实页、索引和模板属于输入快照，不原地修改。

```bash
python "$SKILL_ROOT/scripts/run.py" analysis-page --analysis-root "$ANALYSIS_ROOT" --page 1
python "$SKILL_ROOT/scripts/run.py" analysis-status --analysis-root "$ANALYSIS_ROOT"
python "$SKILL_ROOT/scripts/run.py" render-analysis-report --analysis-root "$ANALYSIS_ROOT"
```

标准发布流程自动生成 `analysis-report/index.html`、`report.json` 和 `receipt.json`，正文展示结论、类型、原始字段值、可比较的数值图及缺口。HTML 仅从已校验结果和对应事实生成，原始数值不因显示格式改变。`analysis-status` 分别返回业务状态、`deliveryStatus`、`reportVerified` 和下一步；进程退出码为 0、等待模型或分析结果已发布，都不能单独代表 HTML 已交付。报告生成失败时，先检查同一分析目录的状态，再运行 `render-analysis-report` 本地恢复；输入或结果已被修改时拒绝恢复，应创建新的分析。

新阶段回执追加在调用所属运行/分析目录的 `execution-events.jsonl`，记录本地阶段真实起止时间、单调时钟耗时、状态和退出码；`returned` 只表示函数返回，业务完成状态以正式回执为准。嵌套阶段不能直接求和，外部 Agent 等待时间和历史缺失耗时保持未知。命令返回后仍在运行的后台任务须另读业务终态，不能把启动命令耗时当作后台任务总耗时。本轮未改变阶段一五页报告。

千川 `prepare-analysis` 返回分页索引与模板路径，`publish-analysis` 校验原有证据链后自动交付 HTML；CLI JSON 的 `execution` 保留该进程命令的 `exitCode/startedAt/endedAt/wallSeconds`。旧分析仍可沿用原校验；没有分页索引时 `analysis-status` 标为 `legacy_not_generated`，不修改旧事实。
