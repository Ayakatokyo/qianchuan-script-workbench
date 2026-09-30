# 输入契约

## 派生入参同步与实时校验

派生 Skill 继承同一表单及映射，表单、提示模板、输入 Schema 和调用代码一起更新。`describe-acquire` 返回 `derivedInputMapping`；`preview-acquire` 可离线检查本次填写值。使用本次实际输入生成请求，不能引用固化流程时保存的客户账号或旧日期。

| 表单字段 | 内部入参 | 必须保留的约束 |
|---|---|---|
| `api_shop` | `liveAcquire.apiShop` | `api_shop` 选择器，`application_id: OCEANENGINE`；授权项取 `extra.shop_id` |
| `rpa_shop` | `liveAcquire.rpaShop` | `rpa_shop` 选择器，`application_id: RPA_JULIANG_QC`、`value_format: both`；与 API 店铺分域，广告主由实时授权关系解析 |
| `date_range` | `period.startDate/endDate` | `YYYY-MM-DD`，`max_policy: t_plus_2`，北京时间前天及以前，开始不晚于结束 |
| `top_n` | `liveAcquire.topN` | 正整数，默认 10；只控制本地选材数量，不截断完整报表 |
| `material_filter_sort` | `liveAcquire.materialFilterSort` | 可选；未填写条件时不加筛选，默认按整体消耗（`stat_cost_for_roi2`）降序；归一化为已注册字段的排序与 filters；仅作用于完整报表后的本地选材 |

完整快照保留平台返回的所有报表行。本地筛选后、取 TopN 前，将 `roi2_material_video_type.Value=4` 或类型展示含 AIGC 的聚合行排除；平台结构化 `material_id` 非正数字、展示值 `-` 以及负数哨兵 ID 也不可作为详情 RPA 目标。排除原因与原行号写入 `material-selection.json.excludedRows`；有效候选按原排序补足 TopN，普通智能优选视频不因类型被排除。过滤不改用户条件、报表 API 请求或全量榜单。

实时日期由 `scripts/date_policy.py::validate_period` 在网络请求前验证；单独复用入口为 `python "$SKILL_ROOT/scripts/date_policy.py" --start-date YYYY-MM-DD --end-date YYYY-MM-DD`，非零退出必须阻断后续请求。非法值不会被自动修正。离线 `verifiedRun` 导入只验证历史周期格式和顺序，不套用实时可用日。

派生 Skill 必须同步首批 CSV 门禁及恢复行为，不能把 `rpaPaused` 当可继续的 `partialFailed`。暂停后先核实旧任务并检查参数；修正后用新的运行目录验证首批。第二阶段分析、生成、改写的业务入参保持与采集入参分开。

阶段一取数先校验 `qianchuan-script-acquisition-input.schema.json`。必须恰好选择实时授权采集 `liveAcquire` 或离线验证运行 `verifiedRun`；不得把授权凭证写入输入 JSON、命令行、文件、日志或收据。`apiShop` 与 `rpaShop` 来自不同授权域，数字广告主 ID 从 RPA 授权关系解析并核对，不让用户手工拼接内部 ID。

```bash
python "$SKILL_ROOT/scripts/run.py" describe-acquire
python "$SKILL_ROOT/scripts/run.py" preview-acquire --input "$INPUT_JSON"
python "$SKILL_ROOT/scripts/run.py" acquire --input "$INPUT_JSON" --output-root "$DATA_ROOT"
python "$SKILL_ROOT/scripts/run.py" continue-acquire --input "$CORRECTED_INPUT_JSON" --run-dir "$RUN_DIR"
python "$SKILL_ROOT/scripts/run.py" import-run --source-run "$VERIFIED_RUN" --output-root "$DATA_ROOT"
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR"
python "$SKILL_ROOT/scripts/run.py" render-summary --run-dir "$RUN_DIR"
```

`DATA_ROOT` 默认是调用方当前工作目录下的 `千川素材脚本数据/`。每个唯一 `runId` 独立存储。完整报表快照和哈希保存后才本地筛选、排序并选取 TopN。口径未知时进入 `awaitingSelection`，必须用 `continue-acquire` 对同一已核验快照续跑；不得重拉报表或自动开始 RPA。

阶段一报告要求 source pack、收据、选择记录、RPA 结果与来源哈希全部通过 `verify`。实时 acquire/continue-acquire 在完成后自动执行该门禁，将查询周期、选材条件及完整可信脚本映射到 `overview/index.html`、`overview/summary-data.json`、兼容 `overview/report.md`、`overview/receipt.json` 及 `analysis-handoff.json`；render-summary 用于离线恢复。报告只读已落盘事实。`partialFailed` 保持部分失败；继续处理须在每个阶段二命令显式传入 `--allow-partial`。

HTML 内全量报表榜单的素材标题/ID搜索、自定义指标选择/顺序、指标排序、公式下钻及片段库一级/二级标签点击和关键词过滤都只改变本地展示，不是新的采集入参，也不修改选材范围、事实包或触发报表/RPA/模型。复制原句和跳转完整脚本沿用同一素材的已核验内容。移除脚本状态筛选/列、原始结构与身份来源折叠区、“完整性与缺口”页和顶部运行状态告示，不放宽上述校验与 `--allow-partial` 要求；summary、facts 和审计记录继续保留原字段与证据。

全量榜单只读取收据绑定的完整快照；不对未采集素材补抓脚本。报告展示目录与选材/分析注册表分别维护；当前注册表明确覆盖固定报表请求的 102 项指标，允许用已返回的“净成交ROI”等字段在本地筛选、排序及对已采集素材做第二阶段分析，缺失值不能补零。`total_ecpm_for_roi2` 的正式名称为“整体千次展现费用”，旧“千次曝光成本”采集别名仍兼容。

阶段二计划通过 `script-analysis-plan.schema.json` 校验，必须显式包括本轮 `runId`、唯一 `analysisId`、`operation=analysis`、用户请求原文、素材范围、脚本字段、指标字段、分组/比较方式和输出目标。素材范围只能是事实包中的全部、排名区间或素材 ID；指标字段须存在于包内注册表。计划不接受新的账户、周期、TopN、筛选排序或 RPA 参数。未知字段或无可用字段返回缺口；不可把缺失补成零。

```bash
python "$SKILL_ROOT/scripts/run.py" prepare-analysis --run-dir "$RUN_DIR" --plan "$PLAN_JSON"
python "$SKILL_ROOT/scripts/run.py" publish-analysis --analysis-root "$RUN_DIR/analysis/$ANALYSIS_ID" --result "$MODEL_RESULT_JSON"
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR/analysis/$ANALYSIS_ID"
```

`prepare-analysis` 校验阶段一交接文件、事实包、Schema、哈希、素材身份和字段来源；随后只写用户选定的最小事实切片、模型输入与 prompt 快照。模型结果必须符合 `script-analysis-result.schema.json`，逐条结论使用素材、字段和 sourceRefs 组成的证据引用。

生成请求校验 `script-generation-request.schema.json`，并要求 `customerFacts`、`businessMethod`、`target`；改写请求校验 `script-rewrite-request.schema.json`，并额外要求非空 `originalText`、`immutableItems`、`deleteItems` 和 `strength`。两个请求都绑定当前阶段一交接和 source pack，并复用旧的生成/改写校验器；不得将改写缺少原稿自动转换为生成。

## 身份错配恢复配置

内部实时输入 `liveAcquire.identityRetryLimit` 是额外重试上限，整数 0–3，默认 2（最多 3 次提交）；显式 3 时最多 4 次。布尔值、小数和超界值拒绝。此项不改变五项业务表单、报表口径或第二阶段输入。仅已结束的身份错配可重试，发生错配后先收齐在途任务，再串行执行余下队列；首批暂停或任务状态未知均阻断重试。

## 指标证据修复（2026-09-28）

新采集的素材保存 `metricSourceRefs`，逐字段绑定完整报表快照 SHA-256、零基原始行号、素材 ID 和指标字段；`sourceRefs` 保留行级定位。构建和验证均核对真实值，不将缺值补零。旧 source pack 保持原字节：新建 `analysisId` 时，`prepare-analysis` 从该包已绑定、且与报表收据一致的完整快照派生字段引用，只写本次分析切片；`metricEvidencePolicy=verified_report_fields_v1` 标记此路径。发布及独立验证重新核对快照、字段值和来源；已有分析保持原验证语义，不覆盖旧报告或收据。

没有绑定快照的历史导入沿用其原证据，不能凭空补来源。重复 ID 无法唯一定位、快照/行/值/引用冲突直接报错。`metric_value_missing` 表示值为空，`metric_source_missing` 表示有值但没有可用来源；准备命令返回逐指标 `metricCoverage`。表现分组也需要引用指标证据，不能仅引用脚本文字支撑高低表现分类。
