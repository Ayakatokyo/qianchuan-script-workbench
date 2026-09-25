"""CLI acquisition must deliver the verified first-stage report automatically."""
from argparse import Namespace
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import script_cli as cli
from test_batch3_acquisition_pipeline import RecordingReportGateway, RecordingRpaGateway, live_request
from test_first_batch_csv_gate import CsvGateway, candidates


class AutoReportTests(unittest.TestCase):
    def input_file(self, root, *, pending=False):
        request = live_request(3)
        payload = request.to_dict()
        if pending:
            payload["liveAcquire"]["materialFilterSort"] = {"sortField": "待用户确认"}
        path = root / "input.json"
        path.write_text(json.dumps(payload, ensure_ascii=False))
        return path

    def runtime(self, report, rpa):
        stack = ExitStack()
        stack.enter_context(patch.object(cli.RuntimeContext, "from_environment", return_value=SimpleNamespace(
            environ={}, require_live_connector=lambda: object())))
        stack.enter_context(patch.object(cli, "_LiveReportGateway", return_value=report))
        stack.enter_context(patch.object(cli, "RpaGateway", return_value=rpa))
        stack.enter_context(patch.object(cli, "resolve_advertiser_id", side_effect=lambda request, *args, **kwargs: request))
        stack.enter_context(patch.object(cli, "_new_run_id", return_value="run-auto"))
        return stack

    def test_acquire_ready_or_partial_delivers_html_and_keeps_acquisition_state(self):
        for partial in (False, True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                report = RecordingReportGateway(candidates(3))
                rpa = RecordingRpaGateway({"m1": "completed", "m2": "failed" if partial else "completed", "m3": "completed"})
                with self.runtime(report, rpa), patch.object(cli, "_verify", wraps=cli._verify) as verified:
                    result = cli._acquire(Namespace(input=self.input_file(root), output_root=root))
                    self.assertEqual(verified.call_count, 1)
                run = (root / "run-auto").resolve()
                self.assertEqual(result["status"], "partialFailed" if partial else "ready")
                self.assertEqual(result["workflowState"], "awaitingAnalysisInput")
                self.assertTrue(result["analysisAllowed"])
                for key, relative in (("reportPath", "overview/index.html"), ("summaryPath", "overview/summary-data.json"), ("handoffPath", "analysis-handoff.json")):
                    self.assertEqual(Path(result[key]), run / relative)
                    self.assertTrue(Path(result[key]).is_file())
                self.assertEqual(Path(result["outputPath"]), run / "facts/qianchuan-script-source-pack.json")
                self.assertEqual(report.calls, 1)
                self.assertEqual(len(rpa.submitted_material_ids), 3)
                self.assertFalse((run / "analysis").exists())
                checked = cli._verify(Namespace(path=run))
                self.assertIn("overview/index.html", checked["checkedFiles"])

    def test_continue_uses_saved_report_and_automatically_delivers_overview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = RecordingReportGateway(candidates(3))
            rpa = RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"})
            with self.runtime(report, rpa):
                pending = cli._acquire(Namespace(input=self.input_file(root, pending=True), output_root=root))
                self.assertEqual(pending["status"], "awaitingSelection")
                run = root / "run-auto"
                self.assertFalse((run / "analysis-handoff.json").exists())
                finished = cli._continue_acquire(Namespace(input=self.input_file(root), run_dir=run))
            self.assertEqual(finished["status"], "ready")
            self.assertEqual(finished["workflowState"], "awaitingAnalysisInput")
            self.assertTrue(Path(finished["reportPath"]).is_file())
            self.assertEqual(report.calls, 1)
            self.assertEqual(len(rpa.submitted_material_ids), 3)

    def test_verified_run_without_usable_text_still_reports_and_disables_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = RecordingReportGateway(candidates(3))
            rpa = CsvGateway({"m1": "missing_script", "m2": "missing_script", "m3": "missing_script"})
            with self.runtime(report, rpa):
                result = cli._acquire(Namespace(input=self.input_file(root), output_root=root))
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["analysisAllowed"])
            self.assertTrue(Path(result["reportPath"]).is_file())
            self.assertFalse((root / "run-auto/analysis").exists())

    def test_paused_or_pending_acquisition_does_not_render_or_create_handoff(self):
        for mode in ("invalid_csv", "unknown", "pending"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                report = RecordingReportGateway(candidates(3))
                class UnknownGateway(CsvGateway):
                    def poll(self, task_id):
                        raise RuntimeError("remote result still unknown")
                rpa = UnknownGateway() if mode == "unknown" else CsvGateway({"m1": "html", "m2": "html", "m3": "html"})
                with self.runtime(report, rpa), patch.object(cli, "_render_summary", side_effect=AssertionError("blocked run rendered")):
                    result = cli._acquire(Namespace(input=self.input_file(root, pending=mode == "pending"), output_root=root))
                self.assertEqual(result["status"], "awaitingSelection" if mode == "pending" else "rpaPaused")
                self.assertFalse((root / "run-auto/overview").exists())
                self.assertFalse((root / "run-auto/analysis-handoff.json").exists())
                self.assertNotIn("reportPath", result)

    def test_report_failure_preserves_facts_and_can_render_offline_without_new_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = RecordingReportGateway(candidates(3))
            rpa = RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"})
            with self.runtime(report, rpa), patch.object(cli, "render_summary", side_effect=OSError("temporary output write failure")):
                with self.assertRaisesRegex(cli.CliError, "render-summary") as caught:
                    cli._acquire(Namespace(input=self.input_file(root), output_root=root))
            self.assertEqual(caught.exception.error_code, "acquisition_report_failed")
            run = root / "run-auto"
            pack_path = run / "facts/qianchuan-script-source-pack.json"
            digest = hashlib.sha256(pack_path.read_bytes()).hexdigest()
            self.assertEqual(json.loads((run / "status.json").read_text())["state"], "ready")
            self.assertFalse((run / "analysis-handoff.json").exists())
            with patch.object(cli.RuntimeContext, "from_environment", side_effect=AssertionError("offline render used live context")):
                rendered = cli._render_summary(Namespace(run_dir=run))
            self.assertTrue(Path(rendered["reportPath"]).is_file())
            self.assertEqual(hashlib.sha256(pack_path.read_bytes()).hexdigest(), digest)
            self.assertEqual(report.calls, 1)
            self.assertEqual(len(rpa.submitted_material_ids), 3)


if __name__ == "__main__":
    unittest.main()
