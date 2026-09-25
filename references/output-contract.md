# 输出契约

## 阶段一：取数事实与报告

成功取数保留 `facts/qianchuan-script-source-pack.json`、`acquisition-receipt.json`、报表快照和逐素材来源。脚本文本、公式、detail 与 data 分开保存；重复正文只用于内容去重，素材排名、指标和来源仍逐素材保留。旧 text-only source pack 按公式等结构字段缺失处理。

`render-summary` 在校验完整运行目录后写入：

| 文件 | Schema / 含义 |
| --- | --- |
| `overview/summary-data.json` | `summary-data.schema.json`；计数、逐素材排名/指标、脚本与结构字段可用性、重复正文和缺口 |
| `overview/report.md` | 可读报告；只呈现事实包已提供的周期、口径、原字段指标、脚本摘要与来源入口 |
| `overview/receipt.json` | `summary-report-receipt.schema.json`；报告、结构数据和 source pack 的 SHA-256 |
| `analysis-handoff.json` | `analysis-handoff.schema.json`；runId、事实包与报告路径/哈希、选材范围、字段可用性、缺口和等待状态 |
| `workbench-state.json` | 工作台暂停状态 `awaitingAnalysisInput`；不覆盖 acquisition `status.json` |

报告验证失败时不得创建成功交接。`partialFailed` 报告保留 `partialFailed`，不会被报告文件提升为 `ready`。没有可用脚本文本时，交接 `analysisAllowed=false`，不可准备阶段二。

## 阶段二：自定义脚本分析

`analysis/<analysisId>/` 写入 `request.json`、`validated-plan.json`、`facts-slice.json`、`model-input.json`、`prompt-snapshot.md`、`prepare-receipt.json` 和 `status.json`。准备态为 `awaitingModel`，operation 固定记录为 `analysis`。所选素材、字段、指标与字段来源均已验证；缺失事实进入 `gaps`，不会猜值或扩大素材范围。

有效模型结果发布为 `analysis-result.json`、`report.md`、`receipt.json` 和 `status.json`。每条结构化结论必须区分平台事实、文本/结构观察、模型推断或待验证建议，并引用事实切片中的字段及 sourceRefs。Schema 与 `publish-analysis` 一同拒绝错误素材、缺失字段、未选指标、错误来源和哈希不匹配。模型没有交回有效结果时不进入 `completed`。

## 生成与改写

工作台通过本轮 handoff 调用保留的生成和改写会话。生成结果继续满足 `generated-scripts.schema.json`、客户事实引用与参考素材引用；改写继续满足 `rewritten-script.schema.json`、原稿哈希、不可变项和变更日志。生成与改写状态都显式记录 operation 和 handoff 哈希。每次操作使用新 `analysisId`，不能覆盖源包或先前结果。

## 状态边界

取数：`awaitingInput|querying|awaitingSelection|rpaProcessing|rpaPaused|sourcePackBuilding|sourcePackVerifying|ready|partialFailed|failed`。分析：`awaitingModel|completed|blocked|failed`。生成/改写沿用 `prepared|awaitingModel|draftOnly|completed|blocked|failed`。`verify` 是只读一致性检查；技术校验通过不代表平台在线流程实际运行、客户事实已确认、模型结论正确或文案可直接投放。

`first-batch-csv-gate.json` 记录首批固定素材、已确认/有效 CSV/未知素材及 `pending|passed|blocked|unconfirmed`。首批全已确认而零有效 CSV 的错误码为 `first_batch_no_valid_csv`，状态和采集回执为 `rpaPaused`，提示入参可能有问题；未知状态保留独立错误码。`acquisition-results.json.firstBatchCsvGate` 保存相同门禁。暂停保留来源及逐任务错误，但不构建成功事实包或交接；`verify` 核对暂停证据后返回 `verification=paused`，退出码 2，不应据此进入报告或分析。

平台脚本、素材指标、客户事实和模型推断分层保存。指标只能描述所选期间和口径下的观测，不作因果结论；品牌专属规则、画面/音频分析和视频加工不属于本 Skill。
