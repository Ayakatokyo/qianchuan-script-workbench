import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from short_video_foundation.script_creation.selection import select_reference_scripts
from short_video_foundation.script_creation.session import prepare_generation, publish_generation
from short_video_foundation.script_creation.validation import PublishError, validate_generation_draft


DIGEST = "a" * 64


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def analyses_for_selection(selection):
    result = []
    for selected in selection.scripts:
        if not selected.material_facts:
            continue
        items = []
        for fact in selected.material_facts:
            completeness = fact["completeness"]
            has_structure = any(completeness.get(key) for key in ("formulaLabels", "detailLabels", "structuredData"))
            relation = "unclear" if has_structure else "textOnly"
            observations = {
                "formula": json.dumps(fact["formula"], ensure_ascii=False) if completeness.get("formulaLabels") else None,
                "detail": json.dumps(fact["detail"], ensure_ascii=False) if completeness.get("detailLabels") else None,
                "data": json.dumps(fact["data"], ensure_ascii=False) if completeness.get("structuredData") else None,
                "transcript": fact["text"],
            }
            basis = "；".join(observations[key] for key in ("formula", "detail", "data") if observations[key]) or "无可用平台结构字段"
            comparison = {
                key: {
                    "alignment": relation,
                    "platformBasis": basis,
                    "transcriptBasis": fact["text"],
                    "modelInference": "仅记录可审阅的文本和平台结构对照。",
                }
                for key in ("opening", "sellingPointProgression", "evidence", "callToAction")
            }
            items.append({
                "materialId": fact["materialId"],
                "evidenceMode": "structuredAndText" if has_structure else "textOnly",
                "platformObservations": observations,
                "comparison": comparison,
                "borrowableMethod": "借鉴表达的组织方式，不复制平台标签为客户事实。",
                "fieldSources": fact["fieldSourceRefs"],
            })
        result.append({"referenceRef": selected.script_id, "materialAnalyses": items})
    return result


def source_pack_with_six_duplicate_materials():
    materials = [{"materialId": f"m{i}", "rank": i, "metrics": {"综合成本": str(100 - i)}, "sourceRefs": [f"report:m{i}"]} for i in range(1, 7)]
    scripts = [{
        "scriptId": "script:shared",
        "materialId": material["materialId"],
        "rawText": "共享参考脚本",
        "rawTextSha256": DIGEST,
        "normalizedTextSha256": "b" * 64,
        "parseStatus": "parsed",
        "completeness": {"text": True},
        "sourceRefs": [f"rpa:{material['materialId']}"],
    } for material in materials]
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        "selection": {"rankingField": "综合成本", "direction": "desc", "filters": []},
        "materials": materials,
        "scripts": scripts,
        "deduplication": {"uniqueScriptCount": 1, "groups": [{"scriptId": "script:shared", "materialIds": [f"m{i}" for i in range(1, 7)], "materialMetrics": {f"m{i}": {"综合成本": str(100 - i)} for i in range(1, 7)}}]},
        "availability": {"requested": 6, "available": 6, "missing": 0, "failed": 0},
        "sourceRefs": ["run-1"],
    }


def request_payload(customer_facts=None):
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "analysisId": "analysis-1",
        "sourcePack": "source-pack.json",
        "customerFacts": customer_facts or {"complete": True, "facts": [{"id": "fact-1", "text": "客户确认的真实卖点"}]},
        "businessMethod": "先呈现具体痛点，再展示客户确认的证据。",
        "target": {"scriptCount": 2, "durationSec": 30, "cta": "了解更多"},
    }


def valid_generation_draft(status="completed"):
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "analysisId": "analysis-1",
        "status": status,
        "inputHashes": {"customerFactsSha256": DIGEST, "methodSha256": "b" * 64, "sourcePackSha256": "c" * 64},
        "referenceScripts": [{"scriptId": "script:shared", "materialIds": ["m1", "m2", "m3", "m4", "m5", "m6"], "sourceRefs": ["run-1"]}],
        "scripts": [
            {"id": "v1", "title": "痛点版", "primaryVariable": "hook", "text": "客户确认的真实卖点和新的表达", "claims": [{"text": "客户确认的真实卖点", "customerFactRefs": ["fact-1"]}], "referenceRefs": ["script:shared"], "referenceAnalysisRefs": [{"referenceRef": "script:shared", "materialId": "m1"}], "review": {"issues": [], "humanReviewRequired": True}},
            {"id": "v2", "title": "机制版", "primaryVariable": "mechanism", "text": "客户确认的真实卖点和另一种表达", "claims": [{"text": "客户确认的真实卖点", "customerFactRefs": ["fact-1"]}], "referenceRefs": ["script:shared"], "referenceAnalysisRefs": [{"referenceRef": "script:shared", "materialId": "m1"}], "review": {"issues": [], "humanReviewRequired": True}},
        ],
        "checks": {"customerFactsComplete": True, "referencesAvailable": True, "constraintsPassed": True},
        "missing": [],
        "nonCausalBoundary": "指标只用于选择参考素材，不表示脚本结构导致效果。",
        "referenceAnalyses": [{
            "referenceRef": "script:shared",
            "materialAnalyses": [{
                "materialId": f"m{i}", "evidenceMode": "textOnly",
                "platformObservations": {"formula": None, "detail": None, "data": None, "transcript": "共享参考脚本"},
                "comparison": {key: {"alignment": "textOnly", "platformBasis": "无可用平台结构字段。", "transcriptBasis": "共享参考脚本", "modelInference": "仅作文本观察。"} for key in ("opening", "sellingPointProgression", "evidence", "callToAction")},
                "borrowableMethod": "仅参考正文写法。",
                "fieldSources": {"formula": [], "detail": [], "data": [], "text": [f"rpa:m{i}"]},
            } for i in range(1, 7)],
        }],
    }


class Batch3GenerationTests(unittest.TestCase):
    def test_reference_selection_deduplicates_content_not_metrics(self):
        request = request_payload()
        selection = select_reference_scripts(source_pack_with_six_duplicate_materials(), request)
        self.assertEqual(len(selection.scripts), 1)
        self.assertEqual(len(selection.scripts[0].material_metrics), 6)

    def test_old_text_only_source_pack_remains_compatible_with_explicit_missing_formula(self):
        selection = select_reference_scripts(source_pack_with_six_duplicate_materials(), request_payload())
        material_fact = selection.scripts[0].to_dict()["materialFacts"][0]
        self.assertIsNone(material_fact["formula"])
        self.assertFalse(material_fact["completeness"]["formulaLabels"])
        self.assertEqual(material_fact["text"], "共享参考脚本")

    def test_generation_prompt_receives_formula_separate_from_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_pack_with_six_duplicate_materials()
            for index, script in enumerate(source["scripts"], start=1):
                script.update({
                    "formula": {"labels": [f"结构{index}"]},
                    "detail": {"labels": ["镜头提示"]},
                    "data": [],
                    "text": "共享参考脚本",
                    "completeness": {"text": True, "formulaLabels": True, "detailLabels": True, "structuredData": False, "transcript": True},
                    "fieldSourceRefs": {"formula": [f"attempt:{index}:payload"], "detail": [f"attempt:{index}:payload"], "data": [f"attempt:{index}:payload"], "text": [f"attempt:{index}:payload"]},
                })
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source)
            prompt_path = prepare_generation(root / "request.json", root / "source-pack.json", root / "analysis")
            prompt = prompt_path.read_text(encoding="utf-8")
            selection = json.loads((root / "analysis" / "reference-selection.json").read_text(encoding="utf-8"))
            reference = selection["scripts"][0]
            self.assertEqual(reference["text"], "共享参考脚本")
            self.assertEqual(reference["materialFacts"][0]["formula"], {"labels": ["结构1"]})
            self.assertIn("不能拼进或改写成口播正文", prompt)
            self.assertIn('"formula": {', prompt)

    def test_completed_generation_requires_source_bound_material_analyses_and_report_shows_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_pack_with_six_duplicate_materials()
            for index, script in enumerate(source["scripts"], start=1):
                script.update({
                    "formula": {"labels": [f"结构{index}"]}, "detail": {"labels": ["镜头提示"]}, "data": [],
                    "text": "共享参考脚本",
                    "completeness": {"text": True, "formulaLabels": True, "detailLabels": True, "structuredData": False, "transcript": True},
                    "fieldSourceRefs": {"formula": [f"rpa:{script['materialId']}:formula"], "detail": [f"rpa:{script['materialId']}:detail"], "data": [], "text": [f"rpa:{script['materialId']}:text"]},
                })
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source)
            analysis = prepare_generation(root / "request.json", root / "source-pack.json", root / "analysis")
            selection = select_reference_scripts(source, request_payload())
            draft = valid_generation_draft()
            draft["referenceAnalyses"] = analyses_for_selection(selection)
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(root / "analysis" / "draft.json", draft)
            result = publish_generation(root / "analysis" / "draft.json", root / "analysis")
            saved = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["referenceAnalyses"][0]["materialAnalyses"]), 6)
            report = (root / "analysis" / "report.md").read_text(encoding="utf-8")
            self.assertIn("Platform formula and transcript analysis", report)
            self.assertIn("rpa:m1:formula", report)
            saved.pop("referenceAnalyses")
            with self.assertRaisesRegex(PublishError, "referenceAnalyses"):
                validate_generation_draft(saved, json.loads((root / "analysis" / "customer-facts.json").read_text()), selection.to_dict())
            invalid = json.loads(result.read_text(encoding="utf-8"))
            invalid["referenceAnalyses"][0]["materialAnalyses"][0]["fieldSources"]["formula"] = ["mismatched-attempt:formula"]
            with self.assertRaisesRegex(PublishError, "unsupported formula source"):
                validate_generation_draft(invalid, json.loads((root / "analysis" / "customer-facts.json").read_text()), selection.to_dict())
            invalid = json.loads(result.read_text(encoding="utf-8"))
            invalid["scripts"][0]["referenceAnalysisRefs"] = [{"referenceRef": "script:shared", "materialId": "unknown"}]
            with self.assertRaisesRegex(PublishError, "missing or duplicate material analysis"):
                validate_generation_draft(invalid, json.loads((root / "analysis" / "customer-facts.json").read_text()), selection.to_dict())

    def test_prompt_snapshot_has_ordered_fact_method_reference_boundary_contract_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            source_path = root / "source-pack.json"
            write_json(request_path, request_payload())
            write_json(source_path, source_pack_with_six_duplicate_materials())
            prompt_path = prepare_generation(request_path, source_path, root / "analysis")
            prompt = prompt_path.read_text(encoding="utf-8")
            headings = ["## Customer facts", "## User method", "## Selected platform references", "## Non-causal boundary", "## Output contract"]
            self.assertEqual([prompt.index(heading) for heading in headings], sorted(prompt.index(heading) for heading in headings))
            self.assertTrue((root / "analysis" / "customer-facts.json").is_file())
            self.assertTrue((root / "analysis" / "reference-selection.json").is_file())

    def test_missing_customer_claim_source_cannot_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source_pack_with_six_duplicate_materials())
            analysis = prepare_generation(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_generation_draft(status="completed")
            draft["scripts"][0]["claims"][0]["customerFactRefs"] = []
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(analysis.parent / "draft.json", draft)
            with self.assertRaisesRegex(PublishError, "customer fact"):
                publish_generation(analysis.parent / "draft.json", analysis.parent)

    def test_publish_writes_synchronized_outputs_and_rejects_nonparsed_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "request.json", request_payload())
            source = source_pack_with_six_duplicate_materials()
            for script in source["scripts"]:
                script["parseStatus"] = "missing"
            write_json(root / "source-pack.json", source)
            analysis = prepare_generation(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_generation_draft()
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(analysis.parent / "draft.json", draft)
            with self.assertRaisesRegex(PublishError, "parsed"):
                publish_generation(analysis.parent / "draft.json", analysis.parent)
            source["scripts"][0]["parseStatus"] = "parsed"
            write_json(root / "source-pack.json", source)

    def test_completed_generation_is_atomic_and_reports_reference_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source_pack_with_six_duplicate_materials())
            analysis = prepare_generation(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_generation_draft()
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(analysis.parent / "draft.json", draft)
            result = publish_generation(analysis.parent / "draft.json", analysis.parent)
            self.assertTrue(result.is_file())
            self.assertTrue((analysis.parent / "report.md").is_file())
            self.assertTrue((analysis.parent / "receipt.json").is_file())
            self.assertEqual(json.loads((analysis.parent / "status.json").read_text())["state"], "completed")
            with self.assertRaisesRegex(PublishError, "exists"):
                publish_generation(analysis.parent / "draft.json", analysis.parent)


if __name__ == "__main__":
    unittest.main()
