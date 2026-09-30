---
name: 千川素材脚本工作台
description: 适用于采集和核对千川素材脚本，按用户自定义问题分析已验证脚本，或根据客户确认事实生成脚本、按原稿要求改写脚本。
argument_hint: 先选择千川授权店铺、RPA 授权账号、时间范围和详情素材数；取数报告完成后等待用户描述分析、生成或改写目标。
---

# 千川素材脚本工作台

先阅读[输入契约](references/input-contract.md)、[输出契约](references/output-contract.md)和[维护说明](MAINTENANCE.md)。独立包入口为 `scripts/run.py`，运行环境需 Python 3.11 或更高版本并安装包内 `requirements.txt`。

## 第一阶段：取数、汇总、暂停

`describe-acquire` 显示可选输入与已注册指标；`preview-acquire` 只做本地输入预检；`acquire` 执行用户授权的千川报表与素材脚本取数。完整报表先保存并计算哈希，再按用户口径在本地选材。未填写筛选与排序条件时不加筛选，默认按整体消耗（`stat_cost_for_roi2`）降序选取 TopN；显式用户排序优先。选材和第二阶段指标注册表覆盖固定报表请求的 102 项原始指标，包括“净成交ROI”；筛选或排序时仍须使用本次快照实际返回的值。选材条件不明时停在 `awaitingSelection`，只允许 `continue-acquire` 复用同一份已验证报表快照。

本地选材在取 TopN 前排除 AIGC 动态创意聚合行，以及无可定位素材 ID 的报表行（如 ID `-2` 或展示值 `-`）；这些行仍留在完整报表快照和 `material-selection.json.excludedRows`，不占脚本素材数、不提交详情 RPA。带有效素材 ID 的智能优选视频继续按用户筛选排序参与选材。可选素材不足 TopN 时如实记录实际数量，不将采集失败静默替换为下一条。

```bash
python "$SKILL_ROOT/scripts/run.py" describe-acquire
python "$SKILL_ROOT/scripts/run.py" preview-acquire --input "$INPUT_JSON"
python "$SKILL_ROOT/scripts/run.py" acquire --input "$INPUT_JSON" --output-root "$DATA_ROOT"
python "$SKILL_ROOT/scripts/run.py" continue-acquire --input "$CORRECTED_INPUT_JSON" --run-dir "$RUN_DIR"
# 已完成取数自动校验并出报告；以下用于离线恢复或历史目录
python "$SKILL_ROOT/scripts/run.py" render-summary --run-dir "$RUN_DIR"
# 仅失败诊断或专项审计时单独核验
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR"
```

`acquire` / `continue-acquire` 到达 `ready` 或 `partialFailed` 后自动执行一次离线校验并生成 `overview/index.html`、`overview/summary-data.json`、兼容 `overview/report.md`、`overview/receipt.json` 和根目录 `analysis-handoff.json`。返回的 `reportPath` 是主要阅读入口，`workflowState=awaitingAnalysisInput`；采集状态保持原值。报告失败保留采集事实并返回明确错误，修复后只需 `render-summary` 离线重试，不重新取数。暂停或待选材不生成成功报告。HTML 展示周期、选材口径、素材名称/ID、已落盘指标、完整可信正文和公式；formula/detail/data、重复正文、来源与失败缺口保留在 summary、facts 及相关底层产物中。HTML 内嵌样式与交互，无远程资源依赖；关闭 JavaScript 仍能查看内容。单位只使用字段注册表已提供的值，不推断缺失单位。报告成功后明确暂停，请用户描述分析目标、素材范围或选择生成/改写；不得因用户说“参考脚本”就自动开始创作。

第一阶段 HTML 为单页脚本工作台：顶部折叠展示本次取数与选材条件、详情素材内容公式分布；主体同时展示详情素材列表、当前素材指标与完整脚本、当前素材内容公式。一级柱图保持单行，宽度不足时横向滚动；点击一级后以居中的环图和网格图例展示二级分布，并筛选左侧详情素材。条件随本轮 `selection.filters` 增加而逐条展示。页面不提供全量/详情切换、素材榜单、素材搜索/来源筛选；分布图下方设独立的“内容公式与原句”区块，一二级选择同步筛选左侧详情素材，只展示与可信正文逐字命中的原句及上下文，点击可定位完整脚本；一级、二级公式使用分区标题和不同视觉层级，原句每页四条、桌面双列排列，支持上一页和下一页。完整报表快照仍哈希绑定并用于选材、来源校验与第二阶段分析；`summary-data.json.leaderboard` 仍保存已验证全榜事实。单素材“投放数据”只提供本素材实际返回的指标，优先使用平台 ValueStr；点击二级公式步骤可定位完整正文中的精确原句。公式覆盖按素材 ID 去重，仅使用平台显式标签，不把缺失结构或数值 ID 猜成标签。

当前素材“投放数据”优先展示综合成本、整体消耗、整体成交订单数、净成交金额、净成交ROI、整体展现次数、整体点击次数和整体点击率这八项中本素材实际返回的字段；八项均未返回时展示前八项可用指标。自定义指标只提供当前素材实际返回的字段，支持按素材分别勾选及恢复默认；优先使用平台 ValueStr。右侧按平台提供的一级/二级顺序展示公式步骤，保留重复步骤；仅将所属已核验正文中精确命中的 detail 原句用于正文高亮与定位，不补编公式标签。独立片段库不再显示；原始明细和引用仍保存在结构化事实中。详细展示口径见[输出契约](references/output-contract.md)。

报告使用独立展示字段目录 `config/report-metric-labels.json`，不依赖兄弟仓运行代码；`total_ecpm_for_roi2` 统一显示“整体千次展现费用”，保留旧采集别名兼容。HTML 不展示“筛选条件与排序字段”技术区。

HTML 移除“完整性与缺口”页、顶部运行状态告示、榜单脚本状态筛选/列，以及单素材的已核验徽标、平台原始结构和身份来源折叠区。无可用正文时仍显示简短提示；展示调整不改变后台状态、首批 CSV 门禁、身份校验和阶段二准入，也不删除底层结构字段与审计证据。

报告以 SHA-256 绑定收据和新交接。已有 Markdown 目录通过校验后只追加 HTML 及收据字段，保留原 Markdown、结构数据与既有交接字节，不破坏旧分析引用；HTML 按当前已验证事实呈现上述业务内容，完整结构字段留在底层事实产物中。

`partialFailed` 报告仍保持部分失败状态。若用户决定继续，必须对该次操作显式使用 `--allow-partial`，且分析只能引用已验证的部分事实。没有可用平台脚本文本的运行不可进入第二阶段。

### 首批详情 CSV 熔断

素材详情连接器 `rpa.conn.juliang.qc.material.analysis.video.live.diagnosis` 先固定首批最多 3 个素材并保存 `first-batch-csv-gate.json`；目标不足 3 个时以实际目标数为首批。必须收齐首批结果后才允许后续素材或身份错配重试。有效结果须实际落盘、解析为非空业务 CSV，并通过素材身份校验；只有成功状态、文件链接、JSON records、空表头、登录页或错误素材内容均不能放行。CSV 有效但脚本文本缺失或后续本地处理失败，不等于 CSV 无效。

首批全部已确认且没有有效 CSV 时，门禁为 `blocked`，运行状态为 `rpaPaused`，错误码 `first_batch_no_valid_csv`。向使用者明确提示：“首批素材详情 RPA 未返回有效 CSV，当前入参可能有问题，已暂停后续所有 RPA。请检查授权账号、日期和素材定位参数，修正后使用新运行目录重新验证首批。” 不继续后续批次、补位或自动重试，也不宣称已取消远端在途任务。

首批仍有超时、未知或中断时保留 `pending/unconfirmed`，暂停新提交，先核实已有任务；不能把未知当参数错误或自动重提。至少一份 CSV 有效且首批全部已确认才放行。普通续跑、同目录修改参数、直接循环单素材调用均不能绕过持久门禁。`acquire`、`continue-acquire` 和 `verify` 遇到暂停返回非零退出码 2；`verify` 显示 `verification=paused`，不生成成功事实包、汇总或第二阶段交接。

### 身份错配与隔离恢复

返回载荷的 `materialId` 可能沿用请求值，必须继续以独立返回名称、创建时间等字段核对，不能因“有脚本”或 ID 相同而采信。页面 `materialIdTag` 明确为数字或“ID：数字”时也独立比对；同名同时间但页面 ID 冲突仍拒收。新审计用 `identityPolicy=metadata_and_returned_id_v2` 标记，旧审计按原策略复验，未知策略拒绝。发现错配后停止滚动补位，收齐在途任务后将本运行后续请求与恢复重试降为串行。`liveAcquire.identityRetryLimit` 表示额外重试次数，默认 2、范围 0–3；每次只重试已确认终态的身份错配，首批 CSV 暂停、未知任务及硬停止优先，不绕过门禁。

每次尝试保存原载荷、身份对照及脚本内容/返回身份指纹；恢复成功仅使用通过核对的那次脚本字段。最终仍错配时保持 `partialFailed` 与失败事实，摘要记录“已返回脚本内容，但素材身份不一致，未采信”，并与“平台未返回可用正文”分开。旧记录可从哈希已校验的原始 CSV 只读重算内容存在性与指纹，缺少有效 CSV 时保持未知；不回填或改写旧审计和事实。隔离恢复用于降低疑似并发串扰，不能保证修复连接器内部定位或回填问题。旧终态目录不追加在线重试。

## 第二阶段：用户自定义脚本分析

把用户的自然语言目标转成符合 `script-analysis-plan.schema.json` 的计划。计划只能选择本运行中的素材、已落盘的 `formula/detail/data/text` 字段和字段注册表中的指标；不得出现店铺、广告主、日期、TopN、RPA 或重新取数参数。未知字段、素材越界和字段缺失要保留为明确错误或缺口。

```bash
python "$SKILL_ROOT/scripts/run.py" prepare-analysis --run-dir "$RUN_DIR" --plan "$PLAN_JSON"
# partialFailed 运行须经用户明确继续，并增加：--allow-partial
python "$SKILL_ROOT/scripts/run.py" publish-analysis --analysis-root "$RUN_DIR/analysis/$ANALYSIS_ID" --result "$MODEL_RESULT_JSON"
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR/analysis/$ANALYSIS_ID"
```

只把 `model-input.json` / `prompt-snapshot.md` 中的已验证事实切片交给模型。逐素材保留相同正文对应的不同公式和指标，逐条结论标注平台事实、文本/结构观察、模型推断或待验证建议，并引用匹配的素材、字段与来源。不得补写客户事实、缺失字段或平台结论；不得由指标推断脚本导致效果，也不得把有限样本概括为稳定爆款规律。没有有效模型结果时保持 `awaitingModel`，不生成成功报告。

同一 `runId` 的每次分析都使用新的 `analysisId`，输出到独立 `analysis/<analysisId>/`，不覆盖源事实或已有分析。分析问题改变时重新生成计划与分析输入，不重新取数。

## 可选操作：生成或改写

- 用户明确要生成时，收集真实产品事实、证据、允许承诺、目标、时长和 CTA；把请求绑定本次 `analysis-handoff.json` 与事实包，通过 `prepare-generation` 得到模型输入，模型返回结果后由 `publish-generation` 做原有 Schema、事实引用和参考引用校验。
- 用户明确要改写时，必须取得原稿、客户事实、改写目标、保留项、删除项、改写强度和目标；通过 `prepare-rewrite` / `publish-rewrite` 走原稿哈希、不可变项和变更记录校验。原稿缺失时停止改写，不自动转成生成。
- 两类操作都复用当前已验证事实包，并在 `status.json` 记录 `operation=generation|rewrite` 及交接哈希。`partialFailed` 运行须显式提供 `--allow-partial`。
- 每次操作单独使用 `analysisId` 并运行 `verify`。`completed` 表示本地契约校验完成，仍需人工审核，不代表已投放。

## 边界

指标描述所选日期和口径下的平台表现，不证明脚本写法导致效果。千川平台脚本、ASR/OCR、模型观察和客户确认事实是不同数据层；本工作台只使用千川脚本事实和素材指标，不下载视频、不执行 ASR/OCR/VLM、不生成画面分析或一家之言专属规则。客户文档中的示例声明、价格、功效和促销机制不能自动当成客户事实。

## 从完整运行创建派生 Skill

用户要求固化已完成的取数、分析、生成或改写流程时，以本次成功验证的 `acquisition-receipt.json`、`analysis-handoff.json`、事实包及分析回执为依据。把授权店铺、RPA 账号、日期、详情素材数、筛选排序和后续业务问题做成新 Skill 的入参；只保留字段类型与约束，不把本次客户 ID、账号值、日期、路径、原稿、客户事实或样本结论写成通用默认值。暂停或未验证运行不能作为成功模板。

入参同步必须同时覆盖新 Skill 的 `metadata.yaml.skill_form`、`pre_input`、`SKILL.md` frontmatter、输入 Schema、归一化和实际执行调用点。沿用[输入契约](references/input-contract.md)的五字段映射及 `describe-acquire` 的 `derivedInputMapping`；改变表单值必须真正改变本次请求或本地选材，不能继续读取模板生成时的旧配置。API 授权店铺与 RPA 授权账号是两个独立域，广告主数字 ID 由本轮授权关系解析和核对，不把选择器展示名称或授权项 ID 当广告主 ID。

日期表单保留 `max_policy: t_plus_2`，说明“北京时间前天及以前”。所有实时路径必须在报表、授权查询或详情 RPA 之前调用随包交付的 `scripts/date_policy.py::validate_period`，或委托本工作台完整入口。非法日期返回可用上限并阻断请求，不自动改日。独立包必须包含校验代码及其调用点，仅复制表单或文字不算继承。离线导入历史已验证事实不重跑实时取数。

详情采集必须委托完整 `acquire/continue-acquire` 编排；独立实现时须交付同等首批 CSV 验证、持久暂停、请求前检查和授权/身份核验。每次执行读取连接器实时定义并验证实际业务参数，不写死上次 schema、platformCode 或账号关系，不循环低层单素材提交绕过门禁。阶段二仍只用当前已验证事实，不借分析入参改变取数范围。

派生交付前做实际行为验收：更换两域账号、日期、TopN、筛选排序后，实际请求和落盘回执同步变化；北京时间 T-2 通过、T-1/今天/未来及反向日期拒绝且没有网络请求；首批全无有效 CSV 不提交下一批、部分有效且全体确认才继续、未知/中断/重启仍暂停；本地后处理错误不误判无 CSV。独立解包验证入口、运行模块、Schema、字段注册表和依赖齐全，测试保留在派生源码仓。旧派生包不会自动更新，须在其源仓升级、重建并验收。

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
