import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_batch3_workbench import synthetic_run, plan_for, write_json
from workbench_reporting import render_summary
from workbench_analysis import describe_analysis, prepare_analysis, check_analysis_result, publish_analysis
from analysis_delivery import read, prepare_pages, read_page, verify_pages
from script_cli import build_parser


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class ExecutionFlowTests(unittest.TestCase):
    def test_field_discovery_and_preflight_do_not_mutate_and_publish_keeps_gates(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            run = synthetic_run(base)
            render_summary(run)
            before = snapshot(run)
            description = describe_analysis(run, ["text", "formula", "data", "stat_cost_for_roi2"])
            self.assertEqual(snapshot(run), before)
            fields = {item["field"]: item for item in description["fields"]}
            self.assertEqual(fields["formula"]["valueTypes"], ["object"])
            self.assertEqual(fields["stat_cost_for_roi2"]["availableCount"], 2)
            self.assertIn("0", fields["stat_cost_for_roi2"]["samples"][0]["preview"])
            write_json(base / "plan.json", plan_for(run))
            root = Path(prepare_analysis(run, base / "plan.json")["outputPath"])
            payload = read(root / "result-template.json")
            payload["conclusions"] = [{"claim": "零值是实际观察", "classification": "platformFact",
                "evidenceRefs": [{"materialId": "m1", "field": "metric", "fieldId": "stat_cost_for_roi2", "sourceRefs": ["report:row:1"]}]}]
            result = base / "result.json"
            write_json(result, payload)
            before = snapshot(run)
            self.assertFalse(check_analysis_result(root, result)["published"])
            self.assertEqual(snapshot(run), before)
            payload["conclusions"][0]["evidenceRefs"][0]["sourceRefs"] = ["invented"]
            write_json(result, payload)
            with self.assertRaises(Exception):
                check_analysis_result(root, result)
            self.assertEqual(snapshot(run), before)
            payload["conclusions"][0]["evidenceRefs"][0]["sourceRefs"] = ["report:row:1"]
            write_json(result, payload)
            publish_analysis(root, result)
            self.assertEqual(read(root / "status.json")["state"], "completed")

    def test_page_range_checks_once_and_keeps_full_text_and_tamper_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_json(root / "input.json", {"run": 1})
            records = [{"id": i, "text": "全文" * 1000} for i in range(11)]
            prepare_pages(root, {"runId": "r", "analysisId": "a"}, records, ["input.json"], {}, [])
            with patch("analysis_delivery.verify_pages", wraps=verify_pages) as verify:
                response = read_page(root, 1, 3)
            self.assertEqual(verify.call_count, 1)
            self.assertEqual([row for page in response["pages"] for row in page["records"]], records)
            (root / "fact-pages/0003.json").write_text("{}")
            with self.assertRaises(ValueError):
                read_page(root, 1, 1)
            self.assertEqual(build_parser().parse_args(["describe-analysis", "--run-dir", d]).command, "describe-analysis")
