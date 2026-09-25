# 输入契约

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

阶段一报告要求 source pack、收据、选择记录、RPA 结果与来源哈希全部通过 `verify`。它将查询周期、选材条件和脚本字段可用性映射到 `overview/summary-data.json`、`overview/report.md`、`overview/receipt.json` 及 `analysis-handoff.json`。报告只读已落盘事实。`partialFailed` 保持部分失败；继续处理须在每个阶段二命令显式传入 `--allow-partial`。

阶段二计划通过 `script-analysis-plan.schema.json` 校验，必须显式包括本轮 `runId`、唯一 `analysisId`、`operation=analysis`、用户请求原文、素材范围、脚本字段、指标字段、分组/比较方式和输出目标。素材范围只能是事实包中的全部、排名区间或素材 ID；指标字段须存在于包内注册表。计划不接受新的账户、周期、TopN、筛选排序或 RPA 参数。未知字段或无可用字段返回缺口；不可把缺失补成零。

```bash
python "$SKILL_ROOT/scripts/run.py" prepare-analysis --run-dir "$RUN_DIR" --plan "$PLAN_JSON"
python "$SKILL_ROOT/scripts/run.py" publish-analysis --analysis-root "$RUN_DIR/analysis/$ANALYSIS_ID" --result "$MODEL_RESULT_JSON"
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR/analysis/$ANALYSIS_ID"
```

`prepare-analysis` 校验阶段一交接文件、事实包、Schema、哈希、素材身份和字段来源；随后只写用户选定的最小事实切片、模型输入与 prompt 快照。模型结果必须符合 `script-analysis-result.schema.json`，逐条结论使用素材、字段和 sourceRefs 组成的证据引用。

生成请求校验 `script-generation-request.schema.json`，并要求 `customerFacts`、`businessMethod`、`target`；改写请求校验 `script-rewrite-request.schema.json`，并额外要求非空 `originalText`、`immutableItems`、`deleteItems` 和 `strength`。两个请求都绑定当前阶段一交接和 source pack，并复用旧的生成/改写校验器；不得将改写缺少原稿自动转换为生成。
