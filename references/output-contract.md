# 输出契约

## 阶段一：取数事实与报告

成功取数保留 `facts/qianchuan-script-source-pack.json`、`acquisition-receipt.json`、报表快照和逐素材来源。脚本文本、公式、detail 与 data 分开保存；重复正文只用于内容去重，素材排名、指标和来源仍逐素材保留。旧 text-only source pack 按公式等结构字段缺失处理。

实时 `acquire/continue-acquire` 完成后自动校验并写报告；`render-summary` 保留离线恢复/历史运行入口。输出：

| 文件 | Schema / 含义 |
| --- | --- |
| `overview/summary-data.json` | `summary-data.schema.json`；计数、逐素材排名/指标、脚本与结构字段可用性、重复正文和缺口；新增可选leaderboard保存完整榜单、展示定义及快照来源哈希 |
| `overview/index.html` | 默认脚本数据报告入口；素材筛选条件、素材榜单、脚本内容公式、单素材脚本、脚本片段库五页签；标题/ID 搜索、指标排序、标签/关键词筛选、分页、完整可信正文及公式图表/原文联动 |
| `overview/report.md` | 可读报告；只呈现事实包已提供的周期、口径、原字段指标、脚本摘要与来源入口 |
| `overview/receipt.json` | `summary-report-receipt.schema.json`；HTML/Markdown、结构数据和 source pack 的 SHA-256 |
| `analysis-handoff.json` | `analysis-handoff.schema.json`；runId、事实包与报告路径/哈希、选材范围、字段可用性、缺口和等待状态 |
| `workbench-state.json` | 工作台暂停状态 `awaitingAnalysisInput`；不覆盖 acquisition `status.json` |

报告验证失败时不得创建成功交接。`partialFailed` 报告保留 `partialFailed`，不会被报告文件提升为 `ready`。没有可用脚本文本时，交接 `analysisAllowed=false`，不可准备阶段二。

### HTML 展示口径

素材榜单只按标题或 ID 搜索；固定首列“素材名称”展示单行省略的名称和下方 ID，榜单覆盖本次完整报表全部素材，不限于采集脚本的TopN；不设置独立排名列或脚本状态列/筛选。自定义指标弹窗按分组与搜索提供本次快照实际返回的全部指标，可勾选、移除、上下移动顺序、全选/清空、恢复默认，确定生效、取消不改当前列。点击指标按升序、降序、恢复原序切换，缺失指标不补零；显示平台ValueStr（含百分比、千分位和“-”），排序使用对应Value，缺失/“-”置后；上方展示总条数，页脚展示当前范围及首页/上一页/页码/下一页/尾页，每页 10 条。全榜只有采集素材链接到对应脚本；公式、片段、单素材与分析交接仍使用原TopN。单素材页保留左侧素材列表、名称/ID/排名、指标、内容公式与完整正文，不展示平台原始结构、身份来源折叠区或已核验徽标。

脚本内容公式仅使用平台显式返回的可读标签。一级竖向柱状图按素材 ID 去重计数，覆盖率分母为有可读一级公式的素材数；点击一级后展示其二级环图和可交互图例，二者同步高亮、再次点击取消，切换一级或收起时清除二级选择。二级覆盖率分母是当前一级覆盖的素材数；环图面积按二级标签覆盖计数之和归一，同一素材可包含多个标签，不将环图面积解释成互斥素材占比。

单素材“本视频内容公式”按平台提供的公式顺序展示一级/二级卡片、箭头和对应颜色，保留重复步骤。正文保留原字、段落和顺序，只为精确命中的 detail 引用增加颜色和定位关系；重复原句关联所有命中位置，重叠片段保留全部公式归属。点击公式定位正文，点击正文定位对应公式，不扩大到同一级的其他二级引用。复制公式保留顺序与层级，复制文案保留完整原文；未命中的引用不通过改写或模糊匹配强行关联。

脚本片段库只从已核验可用正文对应的 detail 中提取非空原句，逐条验证其在所属正文中精确出现，身份拒收内容不进入片段库。一级/二级标签以两组可直接点击的标签和片段数展示；切换一级更新二级候选并清除二级选择。支持关键词过滤、每页 12 条、复制原句和跳转所属素材完整脚本；仅有 detail 而没有可读公式映射的原句保留为未分类，不推断一级标签。未匹配原句保留在 summary/facts 中，不作为可定位片段展示。

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
