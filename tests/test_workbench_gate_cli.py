"""Paused acquisition is visible at the public CLI and cannot become a handoff."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import script_cli
from test_first_batch_csv_gate import CsvGateway, candidates
from test_batch3_acquisition_pipeline import RecordingReportGateway, live_request
from qianchuan_script_acquisition_pipeline import acquire_scripts


class WorkbenchGateCliTests(unittest.TestCase):
    def test_actual_acquisition_receipts_verify_pause_or_pass(self):
        for modes, status, code in (
            ({"m1": "json", "m2": "empty", "m3": "failed"}, "rpaPaused", 2),
            ({"m1": "valid", "m2": "unknown", "m3": "failed"}, "rpaPaused", 2),
            ({"m1": "valid", "m2": "failed", "m3": "failed"}, "partialFailed", 0),
        ):
            with self.subTest(status=status, modes=modes), tempfile.TemporaryDirectory() as root:
                run = Path(root) / "run-integration"
                acquire_scripts(live_request(6), run, RecordingReportGateway(candidates()), CsvGateway(modes))
                result_code, result = self.invoke("verify", "--path", str(run))
                self.assertEqual(result_code, code, result)
                self.assertEqual(result["status"], status)
                if status == "rpaPaused":
                    result_code, _ = self.invoke("render-summary", "--run-dir", str(run))
                    self.assertEqual(result_code, 1)
                    self.assertFalse((run / "analysis-handoff.json").exists())

    def paused_run(self, root):
        run = Path(root) / "run-paused"
        run.mkdir()
        gate = {
            "schemaVersion": 1, "runId": run.name,
            "connectorCode": "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis",
            "status": "blocked", "firstBatchMaterialIds": ["m1"],
            "completedMaterialIds": ["m1"], "validCsvMaterialIds": [], "unknownMaterialIds": [],
            "errorCode": "first_batch_no_valid_csv", "message": "当前入参可能有问题，已暂停后续所有 RPA。",
        }
        common = {"schemaVersion": 1, "runId": run.name}
        pause = {"errorCode": gate["errorCode"], "message": gate["message"], "gatePath": "first-batch-csv-gate.json"}
        files = {
            "first-batch-csv-gate.json": gate,
            "status.json": {**common, "state": "rpaPaused", **pause},
            "acquisition-results.json": {
                **common, "status": "rpaPaused", "firstBatchCsvGate": gate,
                "counts": {"requested": 1, "taskSubmissions": 0, "available": 0,
                           "submittedWithoutScript": 0, "failed": 1, "submissionUnknown": 0, "unsubmitted": 0},
                "materials": [{"materialId": "m1", "rank": 1, "state": "failed", "attempts": []}],
            },
            "acquisition-receipt.json": {
                **common, "status": "rpaPaused", **pause,
                "counts": {"requested": 1, "available": 0, "missing": 0, "failed": 1},
                "outputs": ["status.json", "acquisition-results.json", "first-batch-csv-gate.json"],
            },
        }
        for name, value in files.items():
            (run / name).write_text(json.dumps(value, ensure_ascii=False))
        return run

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = script_cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_verify_reports_pause_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.paused_run(root)
            code, result = self.invoke("verify", "--path", str(run))
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "rpaPaused")
            self.assertEqual(result["verification"], "paused")
            self.assertIn("入参可能有问题", result["message"])
            self.assertFalse((run / "analysis-handoff.json").exists())

    def test_verify_rejects_changed_gate_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.paused_run(root)
            path = run / "first-batch-csv-gate.json"
            gate = json.loads(path.read_text())
            gate["validCsvMaterialIds"] = ["m1"]
            path.write_text(json.dumps(gate))
            code, result = self.invoke("verify", "--path", str(run))
            self.assertEqual(code, 1)
            self.assertEqual(result["errorCode"], "csv_gate_mismatch")

    def test_interrupted_run_with_pending_gate_cannot_verify_as_success(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.paused_run(root)
            status = {"schemaVersion": 1, "runId": run.name, "state": "rpaProcessing"}
            (run / "status.json").write_text(json.dumps(status))
            gate_path = run / "first-batch-csv-gate.json"
            gate = json.loads(gate_path.read_text())
            gate.update(status="pending", completedMaterialIds=[], errorCode=None, message=None)
            gate_path.write_text(json.dumps(gate))
            (run / "acquisition-results.json").unlink()
            (run / "acquisition-receipt.json").unlink()
            code, result = self.invoke("verify", "--path", str(run))
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "rpaPaused")
            self.assertEqual(result["firstBatchCsvGate"]["status"], "pending")

    def test_continue_checks_pause_before_snapshot_or_authorization(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.paused_run(root)
            request = Path(root) / "request.json"
            request.write_text(json.dumps({
                "schemaVersion": 1,
                "period": {"startDate": "2026-09-01", "endDate": "2026-09-02"},
                "liveAcquire": {"apiShop": "api", "rpaShop": "rpa", "advertiserId": "1", "topN": 1},
            }))
            with patch.object(script_cli.RuntimeContext, "require_live_connector", side_effect=AssertionError("network must not start")):
                code, result = self.invoke("continue-acquire", "--input", str(request), "--run-dir", str(run))
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "rpaPaused")
            self.assertEqual(result["errorCode"], "first_batch_no_valid_csv")


if __name__ == "__main__":
    unittest.main()
