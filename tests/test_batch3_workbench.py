import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
WORKBENCH_ROOT = PROJECT_ROOT
sys.path.insert(0, str(WORKBENCH_ROOT / "scripts"))

from workbench_analysis import WorkbenchError, prepare_analysis, publish_analysis, verify_analysis
from workbench_reporting import render_summary, verify_handoff


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_run(root: Path, *, state: str = "ready") -> Path:
    run_dir = root / "run-synthetic"
    write_json(run_dir / "status.json", {"schemaVersion": 1, "runId": run_dir.name, "state": state})
    write_json(run_dir / "acquisition-results.json", {
        "materials": [
            {"materialId": "m1", "state": "available"},
            {"materialId": "m2", "state": "available"},
        ]
    })
    script_text = "开场讲清痛点，再说明产品体验。"
    source_pack = {
        "schemaVersion": 1,
        "runId": run_dir.name,
        "period": {"startDate": "2026-09-08", "endDate": "2026-09-15"},
        "selection": {
            "rankingField": "stat_cost_for_roi2", "rankingLabel": "整体消耗", "direction": "desc", "filters": [],
            "topN": 2, "reportRowCount": 20, "matchingRowCount": 20, "rankableRowCount": 20,
        },
        "materials": [
            {"materialId": "m1", "rank": 1, "metrics": {"stat_cost_for_roi2": 0}, "sourceRefs": ["report:row:1"]},
            {"materialId": "m2", "rank": 2, "metrics": {"stat_cost_for_roi2": 12.5}, "sourceRefs": ["report:row:2"]},
        ],
        "scripts": [
            {
                "scriptId": "s1", "materialId": "m1", "rawText": script_text,
                "rawTextSha256": hashlib.sha256(script_text.encode()).hexdigest(),
                "normalizedTextSha256": "a" * 64, "parseStatus": "parsed",
                "completeness": {"text": True, "formulaLabels": True, "detailLabels": False, "structuredData": False},
                "sourceRefs": ["attempt:m1:payload"], "formula": {"labels": ["痛点开场"]}, "detail": None, "data": None,
                "text": script_text,
                "fieldSourceRefs": {"formula": ["attempt:m1:formula"], "detail": [], "data": [], "text": ["attempt:m1:text"]},
                "materialFile": "facts/materials/m1.json",
            },
            {
                "scriptId": "s2", "materialId": "m2", "rawText": script_text,
                "rawTextSha256": hashlib.sha256(script_text.encode()).hexdigest(),
                "normalizedTextSha256": "a" * 64, "parseStatus": "parsed",
                "completeness": {"text": True, "formulaLabels": True, "detailLabels": False, "structuredData": False},
                "sourceRefs": ["attempt:m2:payload"], "formula": {"labels": ["体验说明"]}, "detail": None, "data": None,
                "text": script_text,
                "fieldSourceRefs": {"formula": ["attempt:m2:formula"], "detail": [], "data": [], "text": ["attempt:m2:text"]},
                "materialFile": "facts/materials/m2.json",
            },
        ],
        "deduplication": {"uniqueScriptCount": 1, "groups": [{"normalizedTextSha256": "a" * 64, "materialIds": ["m1", "m2"]}]},
        "availability": {"requested": 2, "available": 2, "missing": 0, "failed": 0},
        "sourceRefs": ["acquisition:run-synthetic"],
    }
    write_json(run_dir / "facts" / "qianchuan-script-source-pack.json", source_pack)
    return run_dir


def plan_for(run_dir: Path, analysis_id: str = "analysis-synthetic") -> dict:
    return {
        "schemaVersion": 1, "runId": run_dir.name, "analysisId": analysis_id, "operation": "analysis",
        "requestText": "比较两个素材的公式和消耗表现。",
        "materialSelection": {"mode": "all"}, "scriptFields": ["formula", "text"],
        "metricFields": ["stat_cost_for_roi2"],
        "comparison": {"mode": "sideBySide", "groupBy": ["formula"]},
        "outputGoal": "列出文本观察与指标分布，不推断因果。",
    }


def material_reference_analyses(selection: dict) -> list[dict]:
    analyses = []
    for reference in selection["scripts"]:
        material_analyses = []
        for fact in reference["materialFacts"]:
            completeness = fact.get("completeness") or {}
            has_structure = any(completeness.get(key) for key in ("formulaLabels", "detailLabels", "structuredData"))
            observations = {
                "formula": json.dumps(fact["formula"], ensure_ascii=False) if completeness.get("formulaLabels") else None,
                "detail": json.dumps(fact["detail"], ensure_ascii=False) if completeness.get("detailLabels") else None,
                "data": json.dumps(fact["data"], ensure_ascii=False) if completeness.get("structuredData") else None,
                "transcript": fact["text"],
            }
            alignment = "partiallyAligned" if has_structure else "textOnly"
            comparison = {
                key: {
                    "alignment": alignment,
                    "platformBasis": "按事实切片记录平台脚本字段。" if has_structure else "没有可用结构字段。",
                    "transcriptBasis": fact["text"],
                    "modelInference": "该对照只描述可见文本与结构。",
                }
                for key in ("opening", "sellingPointProgression", "evidence", "callToAction")
            }
            material_analyses.append({
                "materialId": fact["materialId"],
                "evidenceMode": "structuredAndText" if has_structure else "textOnly",
                "platformObservations": observations,
                "comparison": comparison,
                "borrowableMethod": "参考正文的信息组织方式。",
                "fieldSources": fact["fieldSourceRefs"],
            })
        analyses.append({"referenceRef": reference["scriptId"], "materialAnalyses": material_analyses})
    return analyses


class Batch3WorkbenchTests(unittest.TestCase):
    def test_summary_analysis_publish_and_verify_preserve_per_material_evidence(self):
        with tempfile.TemporaryDirectory(prefix="batch3-workbench-") as directory:
            root = Path(directory)
            run_dir = synthetic_run(root)
            rendered = render_summary(run_dir)
            self.assertEqual(rendered["status"], "awaitingAnalysisInput")
            handoff, pack, pack_path = verify_handoff(run_dir)
            self.assertEqual(handoff["materialIds"], ["m1", "m2"])
            self.assertEqual(pack_path, (run_dir / "facts" / "qianchuan-script-source-pack.json").resolve())
            summary = json.loads((run_dir / "overview" / "summary-data.json").read_text())
            self.assertEqual(summary["counts"]["availableScripts"], 2)
            self.assertEqual(summary["duplicateTextGroups"][0]["materialIds"], ["m1", "m2"])

            plan_path = root / "plan.json"
            write_json(plan_path, plan_for(run_dir))
            prepared = prepare_analysis(run_dir, plan_path)
            analysis_dir = Path(prepared["outputPath"])
            fact_slice = json.loads((analysis_dir / "facts-slice.json").read_text())
            self.assertEqual(fact_slice["materials"][0]["metrics"]["stat_cost_for_roi2"]["value"], 0)
            self.assertEqual(fact_slice["materials"][0]["scriptFields"]["formula"]["value"], {"labels": ["痛点开场"]})
            self.assertEqual(fact_slice["materials"][1]["scriptFields"]["formula"]["value"], {"labels": ["体验说明"]})

            result_path = root / "model-result.json"
            write_json(result_path, {
                "schemaVersion": 1, "runId": run_dir.name, "analysisId": "analysis-synthetic", "operation": "analysis",
                "sourcePackSha256": sha(pack_path), "planSha256": sha(analysis_dir / "validated-plan.json"),
                "modelInputSha256": sha(analysis_dir / "model-input.json"),
                "conclusions": [{
                    "claim": "m1 和 m2 的口播正文相同，平台公式标签不同。", "classification": "textObservation",
                    "evidenceRefs": [
                        {"materialId": "m1", "field": "formula", "sourceRefs": ["attempt:m1:formula"]},
                        {"materialId": "m2", "field": "formula", "sourceRefs": ["attempt:m2:formula"]},
                    ],
                }],
                "limitations": ["样本只有两个素材，不能据此归纳因果。"],
            })
            published = publish_analysis(analysis_dir, result_path)
            self.assertEqual(published["status"], "completed")
            self.assertIn("不能证明某种脚本写法导致效果", (analysis_dir / "report.md").read_text())
            checked = verify_analysis(analysis_dir)
            self.assertIn("analysis-result.json", checked)
            second_plan = plan_for(run_dir, "analysis-synthetic-second")
            second_plan_path = root / "second-plan.json"
            write_json(second_plan_path, second_plan)
            second = prepare_analysis(run_dir, second_plan_path)
            self.assertNotEqual(Path(second["outputPath"]), analysis_dir)
            self.assertTrue((analysis_dir / "analysis-result.json").is_file())
            with self.assertRaisesRegex(WorkbenchError, "analysisId already exists"):
                prepare_analysis(run_dir, plan_path)

    def test_clean_workbench_cli_binds_generation_and_rewrite_to_phase_one_handoff(self):
        with tempfile.TemporaryDirectory(prefix="batch3-workbench-cli-") as directory:
            root = Path(directory)
            run_dir = synthetic_run(root)
            render_summary(run_dir)
            source_pack = run_dir / "facts" / "qianchuan-script-source-pack.json"
            run_script = WORKBENCH_ROOT / "scripts" / "run.py"
            generation_request = {
                "schemaVersion": 1, "runId": run_dir.name, "analysisId": "generation-synthetic",
                "sourcePack": "facts/qianchuan-script-source-pack.json",
                "customerFacts": {"complete": True, "facts": [{"id": "fact-1", "text": "合成客户确认事实", "confirmed": True}]},
                "businessMethod": "先说痛点，再呈现体验。",
                "target": {"scriptCount": 2, "durationSec": 30, "cta": "了解更多"},
            }
            rewrite_request = {
                "schemaVersion": 1, "runId": run_dir.name, "analysisId": "rewrite-synthetic",
                "sourcePack": "facts/qianchuan-script-source-pack.json", "originalText": "旧版口播正文。",
                "customerFacts": {"complete": True, "facts": [{"id": "fact-1", "text": "合成客户确认事实", "confirmed": True}]},
                "businessMethod": "先说痛点，再呈现体验。", "immutableItems": [], "deleteItems": [],
                "strength": "medium", "target": {"durationSec": 30},
            }
            for operation, request in (("generation", generation_request), ("rewrite", rewrite_request)):
                request_path = root / f"{operation}-request.json"
                write_json(request_path, request)
                prepared = subprocess.run(
                    [sys.executable, str(run_script), f"prepare-{operation}", "--request", str(request_path),
                     "--source-pack", str(source_pack), "--output-root", str(root), "--analysis-id", f"{operation}-synthetic"],
                    cwd=root, env={"PYTHONDONTWRITEBYTECODE": "1"}, text=True, capture_output=True,
                )
                self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
                operation_dir = Path(json.loads(prepared.stdout)["outputPath"])
                saved_status = json.loads((operation_dir / "status.json").read_text())
                self.assertEqual(saved_status["operation"], operation)
                self.assertEqual(saved_status["sourceHandoffSha256"], sha(run_dir / "analysis-handoff.json"))
                selection = json.loads((operation_dir / "reference-selection.json").read_text())
                hashes = json.loads((operation_dir / "input-hashes.json").read_text())
                reference_id = selection["scripts"][0]["scriptId"]
                material_id = selection["scripts"][0]["materialIds"][0]
                if operation == "generation":
                    draft = {
                        "schemaVersion": 1, "runId": run_dir.name, "analysisId": "generation-synthetic", "status": "completed",
                        "inputHashes": hashes,
                        "referenceScripts": [{"scriptId": item["scriptId"], "materialIds": item["materialIds"], "sourceRefs": item["sourceRefs"]} for item in selection["scripts"]],
                        "scripts": [{
                            "id": f"version-{index}", "title": f"版本 {index}", "primaryVariable": f"variable-{index}",
                            "text": "合成客户确认事实的新表达。",
                            "claims": [{"text": "合成客户确认事实", "customerFactRefs": ["fact-1"]}],
                            "referenceRefs": [reference_id],
                            "referenceAnalysisRefs": [{"referenceRef": reference_id, "materialId": material_id}],
                            "review": {"issues": [], "humanReviewRequired": True},
                        } for index in (1, 2)],
                        "checks": {"customerFactsComplete": True, "referencesAvailable": True, "constraintsPassed": True},
                        "missing": [], "nonCausalBoundary": "投放指标不证明脚本结构导致效果。",
                        "referenceAnalyses": material_reference_analyses(selection),
                    }
                    draft_path = operation_dir / "model-draft.json"
                    write_json(draft_path, draft)
                else:
                    original = rewrite_request["originalText"]
                    draft = {
                        "schemaVersion": 1, "runId": run_dir.name, "analysisId": "rewrite-synthetic", "status": "completed",
                        "strength": "medium", "inputHashes": hashes, "originalText": original,
                        "rewrittenText": "合成客户确认事实的新版正文。",
                        "changes": [{"type": "rewrite", "content": "新版正文", "reason": "调整表达", "referenceRefs": [reference_id]}],
                        "checks": {"immutableItemsPreserved": True, "deleteItemsRemoved": True, "customerFactsComplete": True, "constraintsPassed": True},
                        "referenceRefs": [reference_id],
                        "referenceAnalysisRefs": [{"referenceRef": reference_id, "materialId": material_id}],
                        "review": {"issues": [], "humanReviewRequired": True},
                        "referenceAnalyses": material_reference_analyses(selection),
                    }
                    draft_path = operation_dir / "model-draft.json"
                    write_json(draft_path, draft)
                published = subprocess.run(
                    [sys.executable, str(run_script), f"publish-{operation}", "--draft", str(draft_path), "--analysis-root", str(operation_dir)],
                    cwd=root, env={"PYTHONDONTWRITEBYTECODE": "1"}, text=True, capture_output=True,
                )
                self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
                verified = subprocess.run(
                    [sys.executable, str(run_script), "verify", "--path", str(operation_dir)],
                    cwd=root, env={"PYTHONDONTWRITEBYTECODE": "1"}, text=True, capture_output=True,
                )
                self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
                self.assertEqual(json.loads(verified.stdout)["verification"], "passed")
                self.assertTrue((operation_dir / ("generated-scripts.json" if operation == "generation" else "rewritten-script.json")).is_file())

    def test_plan_scope_partial_opt_in_and_customer_fact_boundary(self):
        with tempfile.TemporaryDirectory(prefix="batch3-workbench-boundary-") as directory:
            root = Path(directory)
            run_dir = synthetic_run(root, state="partialFailed")
            render_summary(run_dir)
            plan_path = root / "plan.json"
            write_json(plan_path, plan_for(run_dir))
            with self.assertRaisesRegex(WorkbenchError, "explicit --allow-partial"):
                prepare_analysis(run_dir, plan_path)
            with self.assertRaisesRegex(WorkbenchError, "analysis plan selects materials outside"):
                invalid = plan_for(run_dir, "analysis-out-of-scope")
                invalid["materialSelection"] = {"mode": "materialIds", "materialIds": ["outside"]}
                write_json(plan_path, invalid)
                prepare_analysis(run_dir, plan_path, allow_partial=True)

            write_json(plan_path, plan_for(run_dir))
            prepared = prepare_analysis(run_dir, plan_path, allow_partial=True)
            analysis_dir = Path(prepared["outputPath"])
            plan = analysis_dir / "validated-plan.json"
            pack = run_dir / "facts" / "qianchuan-script-source-pack.json"
            write_json(root / "customer-result.json", {
                "schemaVersion": 1, "runId": run_dir.name, "analysisId": "analysis-synthetic", "operation": "analysis",
                "sourcePackSha256": sha(pack), "planSha256": sha(plan), "modelInputSha256": sha(analysis_dir / "model-input.json"),
                "conclusions": [{"claim": "未经客户提供的事实", "classification": "customerFact", "evidenceRefs": [
                    {"materialId": "m1", "field": "text", "sourceRefs": ["attempt:m1:text"]}
                ]}], "limitations": [],
            })
            with self.assertRaisesRegex(WorkbenchError, "customer facts are not part"):
                publish_analysis(analysis_dir, root / "customer-result.json")
            self.assertEqual(json.loads((analysis_dir / "status.json").read_text())["state"], "awaitingModel")

            invalid_evidence = json.loads((root / "customer-result.json").read_text())
            invalid_evidence["conclusions"][0]["classification"] = "textObservation"
            invalid_evidence["conclusions"][0]["evidenceRefs"][0]["sourceRefs"] = ["invented:source"]
            write_json(root / "invalid-evidence-result.json", invalid_evidence)
            with self.assertRaisesRegex(WorkbenchError, "sourceRefs do not match"):
                publish_analysis(analysis_dir, root / "invalid-evidence-result.json")

            fact_slice_path = analysis_dir / "facts-slice.json"
            fact_slice = json.loads(fact_slice_path.read_text())
            fact_slice["materials"][0]["rank"] = 99
            write_json(fact_slice_path, fact_slice)
            with self.assertRaisesRegex(WorkbenchError, "inputs changed after model preparation"):
                publish_analysis(analysis_dir, root / "invalid-evidence-result.json")


if __name__ == "__main__":
    unittest.main()
