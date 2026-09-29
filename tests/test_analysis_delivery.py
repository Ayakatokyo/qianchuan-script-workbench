import json
import tempfile
import unittest
from pathlib import Path

from tests.test_batch3_workbench import synthetic_run, plan_for, write_json
from workbench_reporting import render_summary
from workbench_analysis import prepare_analysis, publish_analysis, analysis_delivery_status, register_analysis_report
from analysis_delivery import prepare_pages, read_page, read, verify_delivery, register_host_report


class AnalysisDeliveryTests(unittest.TestCase):
    def test_report_revisions_and_text_formats_keep_old_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "analysis-1"
            root.mkdir()
            write_json(root / "facts.json", {"fact": 1})
            identity = {"runId": "run-1", "analysisId": root.name}
            first = root / "analysis-report/revisions/0001"
            first.mkdir(parents=True)
            (first / "report.md").write_text("# 首版\n有来源的发现。", encoding="utf-8")
            register_host_report(root, identity, ["facts.json"], "0001", "markdown")
            saved = (first / "receipt.json").read_bytes()
            second = root / "analysis-report/revisions/0002"
            second.mkdir()
            (second / "report.txt").write_text("修订后的简明结论", encoding="utf-8")
            reply = register_host_report(root, identity, ["facts.json"], "0002", "text")
            self.assertEqual(reply["revision"], "0002")
            self.assertEqual((first / "receipt.json").read_bytes(), saved)
            self.assertEqual(len(verify_delivery(root)["revisionHistory"]), 2)
            (first / "report.md").write_text("偷偷改动", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output"):
                verify_delivery(root)

    def test_pages_keep_full_text_boundaries_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_json(root / "input.json", {"run": 1})
            records = [{"id": i, "text": "完整正文<&>" * 2000} for i in range(11)]
            prepare_pages(root, {"runId": "r", "analysisId": "a"}, records, ["input.json"], {"claim": ""}, [])
            collected = [item for n in range(1, 4) for item in read_page(root, n)["records"]]
            self.assertEqual(collected, records)
            with self.assertRaises(ValueError):
                read_page(root, 0)
            write_json(root / "input.json", {"run": 2})
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                read_page(root, 1)

    def test_host_report_registration_and_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            run = synthetic_run(Path(d))
            render_summary(run)
            plan = Path(d) / "plan.json"
            write_json(plan, plan_for(run))
            root = Path(prepare_analysis(run, plan)["outputPath"])
            template = read(root / "result-template.json")
            with self.assertRaises(Exception):
                publish_analysis(root, root / "result-template.json")
            template["conclusions"] = [{"claim": "零值方向", "classification": "platformFact",
                "evidenceRefs": [{"materialId": "m1", "field": "metric", "fieldId": "stat_cost_for_roi2", "sourceRefs": ["report:row:1"]}]}]
            write_json(Path(d) / "result.json", template)
            reply = publish_analysis(root, Path(d) / "result.json")
            self.assertEqual(reply["deliveryStatus"], "awaiting_host_report")
            self.assertFalse((root / "analysis-report/index.html").exists())
            self.assertFalse(analysis_delivery_status(root)["reportVerified"])
            handoff = read(root / "host-report-handoff.json")
            self.assertEqual(handoff["businessQuestion"], read(root / "validated-plan.json")["requestText"])
            folder = root / "analysis-report"
            folder.mkdir()
            (folder / "index.html").write_text("<html><nav>三个方向</nav><main><img src='visuals/chart.svg'></main></html>")
            with self.assertRaisesRegex(ValueError, "asset missing"):
                register_analysis_report(root)
            (folder / "visuals").mkdir()
            (folder / "visuals/chart.svg").write_text("<svg></svg>")
            report = register_analysis_report(root)
            self.assertEqual(report["deliveryStatus"], "completed")
            self.assertTrue(analysis_delivery_status(root)["reportVerified"])
            self.assertEqual(verify_delivery(root)["producer"], "conversation_host")
            (folder / "visuals/chart.svg").unlink()
            with self.assertRaises(ValueError):
                verify_delivery(root)
            (folder / "visuals/chart.svg").write_text("<svg></svg>")
            write_json(root / "analysis-result.json", {**read(root / "analysis-result.json"), "limitations": ["changed"]})
            with self.assertRaises(Exception):
                analysis_delivery_status(root)
