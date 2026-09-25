import json
from pathlib import Path
import tempfile
import unittest

from tests.test_batch3_workbench import synthetic_run, write_json
from workbench_reporting import WorkbenchError, build_summary
from script_creation_contracts import validate_payload


class IdentitySummaryTests(unittest.TestCase):
    def make_failed(self, root, error, present=None):
        run = synthetic_run(root, state="partialFailed")
        path = run / "facts/qianchuan-script-source-pack.json"
        pack = json.loads(path.read_text())
        pack["scripts"][1].update(rawText="", text=None, formula=None,
                                  parseStatus="failed", completeness={}, error=error)
        write_json(path, pack)
        attempt = {"attempt": 1, "identityState": "mismatch",
                   "identityAuditPath": "source-data/identity/m2.json",
                   "scriptContentSha256": "b" * 64}
        if present is not None:
            attempt["scriptContentPresent"] = present
        write_json(run / "source-data/identity/m2.json", {
            "expected": {"materialName": "素材二"}, "observed": {"materialName": ["素材一"]},
            "mismatchedFields": ["materialName"],
        })
        write_json(run / "acquisition-results.json", {"materials": [
            {"materialId": "m1", "state": "available"},
            {"materialId": "m2", "state": "failed", "errorCode": error, "attempts": [attempt]},
        ]})
        return run

    def test_returned_untrusted_script_is_not_reported_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_failed(Path(directory), "material_identity_mismatch", True)
            summary, markdown, handoff = build_summary(run)
            rejected = summary["materials"][1]["script"]
            self.assertEqual(rejected["deliveryStatus"], "identityMismatch")
            self.assertTrue(rejected["returnedContentPresent"])
            self.assertFalse(rejected["textAvailable"])
            self.assertIsNone(rejected["textExcerpt"])
            self.assertEqual(summary["counts"]["identityMismatchScripts"], 1)
            self.assertEqual(handoff["availableScriptMaterialIds"], ["m1"])
            self.assertIn("已返回脚本内容，但素材身份不一致，未采信", markdown)
            self.assertIn("素材二", markdown)
            self.assertIn("素材一", markdown)
            self.assertIn("source-data/identity/m2.json", markdown)
            validate_payload(summary, "summary-data.schema.json")

    def test_legacy_mismatch_does_not_invent_returned_script_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_failed(Path(directory), "material_identity_mismatch")
            summary, markdown, _ = build_summary(run)
            self.assertIsNone(summary["materials"][1]["script"]["returnedContentPresent"])
            self.assertIn("返回内容身份不一致，未采信", markdown)
            self.assertNotIn("已返回脚本内容，但", markdown)

    def test_matched_empty_script_and_remote_failure_keep_distinct_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_failed(Path(directory), "rpa_task_terminal_failure")
            summary, _, _ = build_summary(run)
            self.assertEqual(summary["materials"][1]["script"]["deliveryStatus"], "failed")
            path = run / "facts/qianchuan-script-source-pack.json"
            pack = json.loads(path.read_text())
            pack["scripts"][1]["parseStatus"] = "missing"
            write_json(path, pack)
            write_json(run / "acquisition-results.json", {"materials": [
                {"materialId": "m2", "state": "submittedWithoutScript", "attempts": []},
            ]})
            summary, markdown, _ = build_summary(run)
            self.assertEqual(summary["materials"][1]["script"]["deliveryStatus"], "missing")
            self.assertIn("平台未返回可用正文", markdown)

    def test_recovered_script_has_accepted_text_and_recovery_count(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory))
            write_json(run / "acquisition-results.json", {"materials": [{
                "materialId": "m2", "state": "available", "attempts": [
                    {"attempt": 1, "identityState": "mismatch", "scriptContentPresent": True},
                    {"attempt": 2, "identityState": "matched", "scriptContentPresent": True},
                ],
            }]})
            summary, _, handoff = build_summary(run)
            self.assertEqual(summary["counts"]["identityRecoveredScripts"], 1)
            self.assertEqual(summary["counts"]["identityMismatchScripts"], 0)
            self.assertEqual(summary["materials"][1]["script"]["deliveryStatus"], "available")
            self.assertEqual(summary["materials"][1]["script"]["textExcerpt"], "开场讲清痛点，再说明产品体验。")
            self.assertEqual(handoff["availableScriptMaterialIds"], ["m1", "m2"])

    def test_identity_evidence_cannot_escape_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory))
            write_json(run / "acquisition-results.json", {"materials": [{
                "materialId": "m2", "state": "failed", "attempts": [
                    {"attempt": 1, "identityAuditPath": "../private.json"},
                ],
            }]})
            with self.assertRaisesRegex(WorkbenchError, "inside the run"):
                build_summary(run)
