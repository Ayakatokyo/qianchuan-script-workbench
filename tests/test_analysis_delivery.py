import json
import tempfile
import unittest
from pathlib import Path

from tests.test_batch3_workbench import synthetic_run, plan_for, write_json
from workbench_reporting import render_summary
from workbench_analysis import prepare_analysis, publish_analysis, analysis_delivery_status, render_analysis_delivery
from analysis_delivery import prepare_pages, read_page, read, verify_delivery


class AnalysisDeliveryTests(unittest.TestCase):
    def test_pages_keep_full_text_boundaries_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_json(root / "input.json", {"run": 1})
            records = [{"id": i, "text": "完整正文<&>" * 2000} for i in range(11)]
            prepare_pages(root, {"runId": "r", "analysisId": "a"}, records, ["input.json"], {"claim": ""}, [])
            collected = []
            for n in range(1, 4):
                page = read_page(root, n)
                collected.extend(page["records"])
                self.assertEqual(page["nextPage"], n + 1 if n < 3 else None)
            self.assertEqual(collected, records)
            with self.assertRaises(ValueError):
                read_page(root, 0)
            write_json(root / "input.json", {"run": 2})
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                read_page(root, 1)

    def test_publication_report_recovery_and_result_hash_gate(self):
        with tempfile.TemporaryDirectory() as d:
            run = synthetic_run(Path(d))
            render_summary(run)
            plan = Path(d) / "plan.json"
            write_json(plan, plan_for(run))
            prepared = prepare_analysis(run, plan)
            root = Path(prepared["outputPath"])
            self.assertFalse(analysis_delivery_status(root)["reportVerified"])
            template = read(root / "result-template.json")
            with self.assertRaises(Exception):
                publish_analysis(root, root / "result-template.json")
            template["conclusions"] = [{"claim": "零值<script>alert(1)</script>", "classification": "platformFact",
                "evidenceRefs": [{"materialId": "m1", "field": "metric", "fieldId": "stat_cost_for_roi2", "sourceRefs": ["report:row:1"]}]}]
            write_json(Path(d) / "result.json", template)
            reply = publish_analysis(root, Path(d) / "result.json")
            self.assertTrue(analysis_delivery_status(root)["reportVerified"])
            text = Path(reply["reportPath"]).read_text()
            self.assertNotIn("<script>", text)
            self.assertIn("&lt;script&gt;", text)
            data = read(root / "analysis-report/report.json")
            self.assertEqual(data["conclusions"][0]["evidence"][0]["value"], 0)
            Path(reply["reportPath"]).write_text("damaged")
            with self.assertRaises(ValueError):
                verify_delivery(root)
            render_analysis_delivery(root)
            self.assertEqual(Path(reply["reportPath"]).read_text(), text)
            write_json(root / "analysis-report/receipt.json", {"inputHashes": {}, "outputs": {}})
            with self.assertRaisesRegex(ValueError, "invalid analysis report receipt"):
                verify_delivery(root)
            render_analysis_delivery(root)
            write_json(root / "analysis-result.json", {**template, "status": "completed", "limitations": ["changed"]})
            with self.assertRaises(Exception):
                render_analysis_delivery(root)
            events = [json.loads(line) for line in (root / "execution-events.jsonl").read_text().splitlines()]
            self.assertTrue(any(e["status"] == "failed" and e["exitCode"] == 1 for e in events))
            self.assertTrue(all(e["wallSeconds"] >= 0 and e["startedAt"] <= e["endedAt"] for e in events))
