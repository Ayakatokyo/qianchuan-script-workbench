# 输出契约

## 阶段一：取数事实与报告

成功取数保留 `facts/qianchuan-script-source-pack.json`、`acquisition-receipt.json`、报表快照和逐素材来源。脚本文本、公式、detail 与 data 分开保存；重复正文只用于内容去重，素材排名、指标和来源仍逐素材保留。旧 text-only source pack 按公式等结构字段缺失处理。

`material-selection.json` 保留完整报表行数、用户筛选匹配数、可选行数和 `excludedRows`。AIGC 聚合行记为 `aigc_aggregate`，无可定位 ID 的行记为 `material_id_unavailable`；两者不进入 TopN 或详情 RPA，仍可在完整报表榜单查看。`selectedCount` 与详情请求数仅计算实际可选素材；若不足 TopN，按实际数量交付并在审计中保留原因。真正发起采集后失败的素材仍按失败与缺口披露。

实时 `acquire/continue-acquire` 完成后自动校验并写报告；`render-summary` 保留离线恢复/历史运行入口。输出：

| 文件 | Schema / 含义 |
| --- | --- |
| `overview/summary-data.json` | `summary-data.schema.json`；计数、逐素材排名/指标、脚本与结构字段可用性、重复正文和缺口；新增可选leaderboard保存完整榜单、展示定义及快照来源哈希 |
| `overview/index.html` | 单页脚本工作台；仅展示已采集详情素材的取数与选材条件、内容公式分布、素材列表、当前素材指标/完整正文/公式；不提供素材口径切换、榜单或独立原句区；保留精确原句的正文定位 |
| `overview/report.md` | 可读报告；只呈现事实包已提供的周期、口径、原字段指标、脚本摘要与来源入口 |
| `overview/receipt.json` | `summary-report-receipt.schema.json`；HTML/Markdown、结构数据和 source pack 的 SHA-256 |
| `analysis-handoff.json` | `analysis-handoff.schema.json`；runId、事实包与报告路径/哈希、选材范围、字段可用性、缺口和等待状态 |
| `workbench-state.json` | 工作台暂停状态 `awaitingAnalysisInput`；不覆盖 acquisition `status.json` |

报告验证失败时不得创建成功交接。`partialFailed` 报告保留 `partialFailed`，不会被报告文件提升为 `ready`。没有可用脚本文本时，交接 `analysisAllowed=false`，不可准备阶段二。

### HTML 展示口径

第一阶段 HTML 改为单页脚本工作台：顶部折叠“本次取数与选材条件”和“本批详情的内容公式分布”，主体并列左侧详情素材列表、中间当前素材指标与完整正文、右侧当前素材内容公式。页面不展示全量/详情素材榜单、独立来源原句区、素材搜索或脚本来源筛选。完整报表快照及 `summary-data.json.leaderboard` 继续保存并校验；TopN 详情素材范围与第二阶段交接不变。选材筛选条件按 `selection.filters` 逐条展示，卡片数量自适应；无可用正文显示缺口，不展示平台原始结构或身份来源折叠区。“投放数据”优先展示与千川元技能相同的八项默认指标中本素材实际返回的字段：`stat_cost_for_overall_roi2`、`stat_cost_for_roi2`、`total_pay_order_count_for_roi2`、`total_order_settle_amount_for_roi2_1h`、`total_prepay_and_pay_settle_roi2_1h`、`live_show_count_for_roi2_v2`、`live_watch_count_for_roi2_v2`、`live_cvr_rate_for_roi2_v2`；八项均未返回时展示前八项可用指标。其余实际返回字段可按当前素材独立选择。卡片优先使用 ValueStr，缺失值显示“—”；无 ValueStr 的数值采用千分位、最多四位小数。

脚本内容公式仅使用平台显式返回的可读标签。一级竖向柱状图按素材 ID 去重计数、保持单行，宽度不足时横向滚动；点击一级后展示居中的二级环图及网格图例，并按该一级公式筛选左侧详情素材。环图和图例支持同一二级标签高亮，再次点击取消；切换一级或品牌条件时清除二级选择。环图面积按二级标签覆盖计数之和归一，同一素材可包含多个标签，不将环图面积解释成互斥素材占比。

右侧“当前素材的内容公式”按平台提供的一级/二级顺序展示，保留重复步骤。正文保留原字、段落和顺序；点击二级步骤时，只有其 detail 原句在本素材已核验正文中精确出现才高亮并定位首个可用原句。未命中的引用不通过改写或模糊匹配强行关联。

独立脚本片段库不再渲染；detail 原句和来源映射仍保留在 summary/facts。页面仅使用所属正文中精确命中的可读公式引用进行定位；身份拒收内容不进入当前素材脚本。

HTML 不再展示“完整性与缺口”页，以及顶部部分失败、等待第二阶段、“第一阶段仅平台事实”和 `partialFailed` 状态告示。无可用正文时仍显示简短提示；summary、facts、收据、交接和审计记录继续保留结构字段、身份/来源证据、可用性、失败、缺口及等待状态。首批 CSV、身份核对、哈希校验和第二阶段准入均保持原规则，拒收素材不会因简化展示而被采信。

## 阶段二：自定义脚本分析

`analysis/<analysisId>/` 写入 `request.json`、`validated-plan.json`、`facts-slice.json`、`model-input.json`、`prompt-snapshot.md`、`prepare-receipt.json` 和 `status.json`。准备态为 `awaitingModel`，operation 固定记录为 `analysis`。所选素材、字段、指标与字段来源均已验证；缺失事实进入 `gaps`，不会猜值或扩大素材范围。

有效模型结果发布为 `analysis-result.json`、`report.md`、`receipt.json` 和 `status.json`。每条结构化结论必须区分平台事实、文本/结构观察、模型推断或待验证建议，并引用事实切片中的字段及 sourceRefs。Schema 与 `publish-analysis` 一同拒绝错误素材、缺失字段、未选指标、错误来源和哈希不匹配。模型没有交回有效结果时不进入 `completed`。

## 生成与改写

工作台通过本轮 handoff 调用保留的生成和改写会话。生成结果继续满足 `generated-scripts.schema.json`、客户事实引用与参考素材引用；改写继续满足 `rewritten-script.schema.json`、原稿哈希、不可变项和变更日志。生成与改写状态都显式记录 operation 和 handoff 哈希。每次操作使用新 `analysisId`，不能覆盖源包或先前结果。

## 状态边界

取数：`awaitingInput|querying|awaitingSelection|rpaProcessing|rpaPaused|sourcePackBuilding|sourcePackVerifying|ready|partialFailed|failed`。分析：`awaitingModel|completed|blocked|failed`。生成/改写沿用 `prepared|awaitingModel|draftOnly|completed|blocked|failed`。`verify` 是只读一致性检查；技术校验通过不代表平台在线流程实际运行、客户事实已确认、模型结论正确或文案可直接投放。

`first-batch-csv-gate.json` 记录首批固定素材、已确认/有效 CSV/未知素材及 `pending|passed|blocked|unconfirmed`。首批全已确认而零有效 CSV 的错误码为 `first_batch_no_valid_csv`，状态和采集回执为 `rpaPaused`，提示入参可能有问题；未知状态保留独立错误码。`acquisition-results.json.firstBatchCsvGate` 保存相同门禁。暂停保留来源及逐任务错误，但不构建成功事实包或交接；`verify` 核对暂停证据后返回 `verification=paused`，退出码 2，不应据此进入报告或分析。

平台脚本、素材指标、客户事实和模型推断分层保存。指标只能描述所选期间和口径下的观测，不作因果结论；品牌专属规则、画面/音频分析和视频加工不属于本 Skill。

## 身份拒收的呈现

采集结果继续保留兼容 `state=failed` / `material_identity_mismatch`；摘要的 `script.deliveryStatus=identityMismatch` 单独说明拒收原因，`returnedContentPresent` 区分已返回内容与旧记录未知值。摘要中的 `identityEvidence` 保存逐次期望/返回身份、错配字段、审计相对路径和内容指纹，不把拒收正文写入可分析事实。旧尝试缺内容指纹时，可从哈希绑定的原始 CSV 只读重算并标记 `contentEvidenceSource=verifiedCsvReplay`；没有可解析 CSV 时保持未知，不修改旧审计。`identityMismatchScripts` 统计最终未恢复项，`identityRecoveredScripts` 统计重试已恢复项；两者不代替原可用/缺失/失败计数。

## HTML 报告兼容与恢复

新摘要补充 `metricDefinitions`、素材名称、`script.text/formula/detail/data`，仅投影已通过原事实校验的字段；拒收正文不进入可用内容。新交接可选 `htmlReport` 指向 `overview/index.html`，回执以 `htmlReportSha256` 及 outputs 绑定；verify 同时核验 HTML。自动返回采集 `status=ready|partialFailed` 和 `workflowState=awaitingAnalysisInput`，以及 reportPath、summaryPath、handoffPath、analysisAllowed。没有正文仍可生成事实报告，但 analysisAllowed=false。

已有 Markdown 运行只追加 HTML 与回执字段，原 summary-data.json、report.md 和 analysis-handoff.json 保持原字节（旧分析可能绑定其哈希）。这类运行的 HTML 从当前已验证事实重新投影业务展示，完整结构字段保留在底层事实中，旧结构数据仍保留原格式。重复调用复用已通过哈希检查的产物；内容遭篡改时拒绝覆盖。渲染失败时不把采集状态降成失败或伪造成功交接；可修复文件系统问题后用 render-summary 离线恢复，不触发报表/RPA/模型。

报告展示扩展：`leaderboard.scope=fullReport` 时，`materials` 来自已校验快照的全部报表行，`metricDefinitions` 只描述实际返回指标，`sourceRef` 保存快照路径/SHA；旧导入缺少完整报表收据时使用 `scope=selectedMaterials`。这与顶层 `materials`（脚本选材）相互独立。新增字段为可选以兼容旧summary和分析哈希绑定，既有报告不自动覆盖。`config/report-metric-labels.json` 为报告专用名称目录；整体千次展现费用直接展示 `total_ecpm_for_roi2` 原值，不在页面重算。素材筛选条件移除“筛选条件与排序字段”区，选材事实仍保存。

## 指标证据修复（2026-09-28）

新采集的素材保存 `metricSourceRefs`，逐字段绑定完整报表快照 SHA-256、零基原始行号、素材 ID 和指标字段；`sourceRefs` 保留行级定位。构建和验证均核对真实值，不将缺值补零。旧 source pack 保持原字节：新建 `analysisId` 时，`prepare-analysis` 从该包已绑定、且与报表收据一致的完整快照派生字段引用，只写本次分析切片；`metricEvidencePolicy=verified_report_fields_v1` 标记此路径。发布及独立验证重新核对快照、字段值和来源；已有分析保持原验证语义，不覆盖旧报告或收据。

没有绑定快照的历史导入沿用其原证据，不能凭空补来源。重复 ID 无法唯一定位、快照/行/值/引用冲突直接报错。`metric_value_missing` 表示值为空，`metric_source_missing` 表示有值但没有可用来源；准备命令返回逐指标 `metricCoverage`。表现分组也需要引用指标证据，不能仅引用脚本文字支撑高低表现分类。

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
