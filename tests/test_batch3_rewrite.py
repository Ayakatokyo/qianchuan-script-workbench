import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from short_video_foundation.script_creation.session import prepare_rewrite, publish_rewrite
from short_video_foundation.script_creation.validation import PublishError, validate_rewrite_draft


DIGEST = "a" * 64


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_pack():
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        "selection": {"rankingField": "综合成本", "direction": "desc", "filters": []},
        "materials": [{"materialId": "m1", "rank": 1, "metrics": {"综合成本": "10"}, "sourceRefs": ["report:m1"]}],
        "scripts": [{"scriptId": "script-1", "materialId": "m1", "rawText": "参考脚本", "rawTextSha256": DIGEST, "normalizedTextSha256": "b" * 64, "parseStatus": "parsed", "completeness": {"text": True}, "sourceRefs": ["rpa:m1"]}],
        "deduplication": {"uniqueScriptCount": 1, "groups": []},
        "availability": {"requested": 1, "available": 1, "missing": 0, "failed": 0},
        "sourceRefs": ["run-1"],
    }


ORIGINAL = "必须保留的事实\n原稿中的第二段"


def request_payload(strength="strong"):
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "analysisId": "rewrite-1",
        "sourcePack": "source-pack.json",
        "originalText": ORIGINAL,
        "customerFacts": {"complete": True, "facts": [{"id": "fact-1", "text": "必须保留的事实"}]},
        "businessMethod": "强化开头节奏并保留已确认事实。",
        "immutableItems": ["必须保留的事实"],
        "deleteItems": ["待删除句"],
        "strength": strength,
        "target": {"durationSec": 30, "cta": "了解更多"},
    }


def valid_rewrite_draft(text=None, strength="strong"):
    original_hash = hashlib.sha256(ORIGINAL.encode("utf-8")).hexdigest()
    return {
        "schemaVersion": 1,
        "runId": "run-1",
        "analysisId": "rewrite-1",
        "status": "completed",
        "strength": strength,
        "inputHashes": {"originalTextSha256": original_hash, "customerFactsSha256": DIGEST, "methodSha256": "b" * 64, "sourcePackSha256": "c" * 64},
        "originalText": ORIGINAL,
        "rewrittenText": text or "必须保留的事实\n新的更紧凑表达",
        "changes": [{"type": "rewrite", "content": "新的更紧凑表达", "reason": "强化节奏", "referenceRefs": ["script-1"]}],
        "checks": {"immutableItemsPreserved": True, "deleteItemsRemoved": True, "customerFactsComplete": True, "constraintsPassed": True},
        "referenceRefs": ["script-1"],
        "referenceAnalysisRefs": [{"referenceRef": "script-1", "materialId": "m1"}],
        "referenceAnalyses": [{
            "referenceRef": "script-1",
            "materialAnalyses": [{
                "materialId": "m1", "evidenceMode": "textOnly",
                "platformObservations": {"formula": None, "detail": None, "data": None, "transcript": "参考脚本"},
                "comparison": {key: {"alignment": "textOnly", "platformBasis": "无可用平台结构字段。", "transcriptBasis": "参考脚本", "modelInference": "仅作文本观察。"} for key in ("opening", "sellingPointProgression", "evidence", "callToAction")},
                "borrowableMethod": "仅参考正文写法。",
                "fieldSources": {"formula": [], "detail": [], "data": [], "text": ["rpa:m1"]},
            }],
        }],
        "review": {"issues": [], "humanReviewRequired": True},
    }


class Batch3RewriteTests(unittest.TestCase):
    def test_rewrite_without_original_is_rejected_before_analysis_is_created(self):
        for original in (None, ""):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request = request_payload()
                if original is None:
                    request.pop("originalText")
                else:
                    request["originalText"] = original
                write_json(root / "request.json", request)
                write_json(root / "source-pack.json", source_pack())
                from short_video_foundation.errors import ContractError
                with self.assertRaisesRegex(ContractError, "originalText"):
                    prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
                self.assertFalse((root / "analysis").exists())

    def test_prepare_rewrite_preserves_original_and_accepts_all_strengths(self):
        for strength in ("light", "medium", "strong"):
            with self.subTest(strength=strength), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_json(root / "request.json", request_payload(strength))
                write_json(root / "source-pack.json", source_pack())
                analysis = prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
                saved = json.loads((analysis.parent / "request.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["originalText"], ORIGINAL)
                self.assertEqual(json.loads((analysis.parent / "input-hashes.json").read_text())["originalTextSha256"], hashlib.sha256(ORIGINAL.encode()).hexdigest())

    def test_rewrite_prompt_receives_platform_formula_without_merging_into_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_pack()
            source["scripts"][0].update({
                "formula": {"labels": ["痛点", "解法"]},
                "detail": {"labels": ["镜头提示"]},
                "data": [{"key": "value"}],
                "text": "参考脚本",
                "completeness": {"text": True, "formulaLabels": True, "detailLabels": True, "structuredData": True, "transcript": True},
                "fieldSourceRefs": {"formula": ["attempt:1:payload"], "detail": ["attempt:1:payload"], "data": ["attempt:1:payload"], "text": ["attempt:1:payload"]},
            })
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source)
            analysis = prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
            prompt = analysis.read_text(encoding="utf-8")
            selection = json.loads((root / "analysis" / "reference-selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["scripts"][0]["text"], "参考脚本")
            self.assertEqual(selection["scripts"][0]["materialFacts"][0]["formula"]["labels"], ["痛点", "解法"])
            self.assertIn("不能拼进或改写成口播正文", prompt)

    def test_completed_rewrite_requires_joint_formula_analysis_and_report_displays_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_pack()
            source["scripts"][0].update({
                "formula": {"labels": ["痛点", "解法"]}, "detail": {"labels": ["特写"]},
                "data": [{"stage": "evidence"}], "text": "参考脚本",
                "completeness": {"text": True, "formulaLabels": True, "detailLabels": True, "structuredData": True, "transcript": True},
                "fieldSourceRefs": {"formula": ["rpa:m1:formula"], "detail": ["rpa:m1:detail"], "data": ["rpa:m1:data"], "text": ["rpa:m1:text"]},
            })
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source)
            analysis = prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_rewrite_draft()
            item = draft["referenceAnalyses"][0]["materialAnalyses"][0]
            item.update({
                "evidenceMode": "structuredAndText",
                "platformObservations": {"formula": "痛点→解法", "detail": "特写", "data": "证据阶段", "transcript": "参考脚本"},
                "comparison": {key: {"alignment": "partiallyAligned", "platformBasis": "平台结构观察。", "transcriptBasis": "口播中可见的正文依据。", "modelInference": "结构与口播部分吻合。"} for key in ("opening", "sellingPointProgression", "evidence", "callToAction")},
                "fieldSources": {"formula": ["rpa:m1:formula"], "detail": ["rpa:m1:detail"], "data": ["rpa:m1:data"], "text": ["rpa:m1:text"]},
            })
            draft["inputHashes"] = json.loads((root / "analysis" / "input-hashes.json").read_text())
            write_json(root / "analysis" / "draft.json", draft)
            publish_rewrite(root / "analysis" / "draft.json", root / "analysis")
            report = (root / "analysis" / "report.md").read_text(encoding="utf-8")
            self.assertIn("Platform formula and transcript analysis", report)
            self.assertIn("rpa:m1:formula", report)
            draft["referenceAnalysisRefs"] = [{"referenceRef": "script-1", "materialId": "unknown"}]
            selection = json.loads((root / "analysis" / "reference-selection.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(PublishError, "missing or duplicate material analysis"):
                validate_rewrite_draft(draft, request_payload(), request_payload()["customerFacts"], selection)

    def test_strong_rewrite_cannot_drop_immutable_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source_pack())
            analysis = prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_rewrite_draft(text="不包含用户指定保留句")
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(analysis.parent / "draft.json", draft)
            with self.assertRaisesRegex(PublishError, "immutable"):
                publish_rewrite(analysis.parent / "draft.json", analysis.parent)

    def test_publish_writes_change_log_and_synchronized_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "request.json", request_payload())
            write_json(root / "source-pack.json", source_pack())
            analysis = prepare_rewrite(root / "request.json", root / "source-pack.json", root / "analysis")
            draft = valid_rewrite_draft()
            draft["inputHashes"] = json.loads((analysis.parent / "input-hashes.json").read_text())
            write_json(analysis.parent / "draft.json", draft)
            result = publish_rewrite(analysis.parent / "draft.json", analysis.parent)
            self.assertTrue(result.is_file())
            self.assertTrue((analysis.parent / "report.md").is_file())
            self.assertTrue((analysis.parent / "receipt.json").is_file())
            self.assertEqual(json.loads((analysis.parent / "status.json").read_text())["state"], "completed")
            self.assertIn("change", (analysis.parent / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
