---
name: 千川素材脚本工作台
description: Use when a user wants to acquire and review Qianchuan material scripts, analyze those scripts with a custom question, generate scripts from confirmed customer facts, or rewrite a supplied original.
metadata:
  argument_hint: 先选择千川授权店铺、RPA 授权账号、时间范围和详情素材数；取数报告完成后等待用户描述分析、生成或改写目标。
  pre_input: |
    请采集千川素材脚本数据：
    千川授权店铺：__field:api_shop__（必填）
    千川广告主ID：__field:rpa_shop__（必填）
    时间范围：__field:date_range__（必填）
    脚本素材数：__field:top_n__（必填）
    素材筛选与排序：__field:material_filter_sort__（可选）
---

# 千川素材脚本工作台

先阅读[输入契约](references/input-contract.md)、[输出契约](references/output-contract.md)和[维护说明](MAINTENANCE.md)。独立包入口为 `scripts/run.py`，运行环境需 Python 3.11 或更高版本并安装包内 `requirements.txt`。

## 第一阶段：取数、汇总、暂停

`describe-acquire` 显示可选输入与已注册指标；`preview-acquire` 只做本地输入预检；`acquire` 执行用户授权的千川报表与素材脚本取数。完整报表先保存并计算哈希，再按用户口径在本地选材。选材条件不明时停在 `awaitingSelection`，只允许 `continue-acquire` 复用同一份已验证报表快照。

```bash
python "$SKILL_ROOT/scripts/run.py" describe-acquire
python "$SKILL_ROOT/scripts/run.py" preview-acquire --input "$INPUT_JSON"
python "$SKILL_ROOT/scripts/run.py" acquire --input "$INPUT_JSON" --output-root "$DATA_ROOT"
python "$SKILL_ROOT/scripts/run.py" continue-acquire --input "$CORRECTED_INPUT_JSON" --run-dir "$RUN_DIR"
python "$SKILL_ROOT/scripts/run.py" verify --path "$RUN_DIR"
python "$SKILL_ROOT/scripts/run.py" render-summary --run-dir "$RUN_DIR"
```

只有 `verify` 返回通过且运行状态为 `ready` 或 `partialFailed` 时才生成 `overview/summary-data.json`、`overview/report.md`、`overview/receipt.json` 和根目录 `analysis-handoff.json`。报告保留周期、筛选排序口径、素材排名和原始指标字段、脚本/公式字段可用性、重复正文、来源与失败缺口。单位仅在字段注册表提供时显示，缺失单位标为“源数据未提供”。报告成功后明确暂停，请用户描述分析目标、素材范围或选择生成/改写；不得因用户说“参考脚本”就自动开始创作。

`partialFailed` 报告仍保持部分失败状态。若用户决定继续，必须对该次操作显式使用 `--allow-partial`，且分析只能引用已验证的部分事实。没有可用平台脚本文本的运行不可进入第二阶段。

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
