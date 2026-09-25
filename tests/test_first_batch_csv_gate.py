import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_batch3_acquisition_pipeline import RecordingReportGateway, RecordingRpaGateway, live_request
from qianchuan_script_acquisition_pipeline import acquire_scripts, continue_acquire_scripts
from qianchuan_script_acquisition_rpa_client import RpaTaskResult


def csv_file(records):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["recordType", "materialId", "materialName", "scriptInfo"], delimiter="\x01")
    writer.writeheader()
    for record in records:
        writer.writerow({**record, "scriptInfo": json.dumps(record.get("scriptInfo", {}), ensure_ascii=False)})
    return {"fileName": "details.csv", "content": stream.getvalue().encode()}


class CsvGateway(RecordingRpaGateway):
    def __init__(self, modes=None):
        super().__init__({f"m{i}": "completed" for i in range(1, 8)})
        self.modes = modes or {}

    def poll(self, task_id):
        material_id, _ = self._tasks[task_id]
        mode = self.modes.get(material_id, "valid")
        if mode == "failed":
            return RpaTaskResult(task_id, "failed")
        if mode == "unknown":
            raise TimeoutError("remote result unknown")
        record = {"recordType": "script_analysis", "materialId": material_id, "materialName": f"name-{material_id}", "scriptInfo": {"text": "脚本"}}
        if mode == "json":
            return RpaTaskResult(task_id, "completed", records=(record,))
        if mode == "wrong_id":
            record["materialId"] = "wrong"
        if mode == "wrong_name":
            record["materialName"] = "wrong"
        if mode == "no_business":
            record["recordType"] = "error"
        if mode == "empty_business":
            record.update(recordType="material_info", materialName="", scriptInfo={})
        if mode == "error_business":
            record.update(materialName="", scriptInfo={"error": "invalid input parameters"})
        if mode == "missing_script":
            record.update(recordType="material_info", scriptInfo={})
        file = csv_file([record])
        if mode == "html":
            file["content"] = b"<html>login required</html>"
        if mode == "header":
            file["content"] = b"recordType\x01materialId\n"
        if mode == "empty":
            file["content"] = b""
        if mode == "missing":
            return RpaTaskResult(task_id, "completed")
        if mode == "mixed":
            return RpaTaskResult(task_id, "completed", files=(file,), records=({**record, "materialId": "bad-json"},))
        if mode == "multiple_csv":
            return RpaTaskResult(task_id, "completed", files=({"fileName": "error.csv", "content": b"<html>error</html>"}, file))
        return RpaTaskResult(task_id, "completed", files=(file,))


def candidates(count=6):
    return [{"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i, "metrics": {"综合成本": str(20-i)}} for i in range(1, count+1)]


class FirstBatchCsvGateTests(unittest.TestCase):
    def test_derived_gate_rejects_invalid_or_oversized_first_batch(self):
        from qianchuan_script_acquisition_gate import FirstBatchCsvGate
        for material_ids in ([], ["m1"] * 2, ["m1", "m2", "m3", "m4"], [""], [None]):
            with self.subTest(material_ids=material_ids), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "1 至 3"):
                    FirstBatchCsvGate(Path(directory), material_ids)
                self.assertFalse((Path(directory) / "first-batch-csv-gate.json").exists())

    def test_interrupted_pending_gate_cannot_be_reopened_or_cleared_by_new_input(self):
        from qianchuan_script_acquisition_gate import FirstBatchCsvGate, RpaPausedError
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            FirstBatchCsvGate(output, ["m1", "m2", "m3"])
            before = (output / "first-batch-csv-gate.json").read_bytes()
            gateway = CsvGateway()
            with self.assertRaises(RpaPausedError):
                self.run_acquire(output, gateway)
            self.assertEqual(gateway.submitted_material_ids, [])
            self.assertEqual((output / "first-batch-csv-gate.json").read_bytes(), before)

    def run_acquire(self, output, gateway, count=6):
        return acquire_scripts(live_request(count), output, RecordingReportGateway(candidates(count)), gateway)

    def gate(self, output):
        return json.loads((output / "first-batch-csv-gate.json").read_text())

    def test_zero_valid_csv_blocks_later_submissions_and_retries(self):
        for mode in ("failed", "json", "html", "header", "empty", "missing", "wrong_id", "wrong_name", "no_business", "empty_business", "error_business"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                gateway = CsvGateway({f"m{i}": mode for i in range(1, 4)})
                self.run_acquire(output, gateway)
                self.assertCountEqual(gateway.submitted_material_ids, ["m1", "m2", "m3"])
                gate = self.gate(output)
                self.assertEqual(gate["status"], "blocked")
                self.assertEqual(gate["errorCode"], "first_batch_no_valid_csv")
                self.assertIn("当前入参可能有问题", gate["message"])
                self.assertFalse((output / "facts/qianchuan-script-source-pack.json").exists())
                self.assertEqual(json.loads((output / "status.json").read_text())["state"], "rpaPaused")
                self.assertEqual(json.loads((output / "acquisition-receipt.json").read_text())["status"], "rpaPaused")

    def test_first_batch_is_persisted_before_any_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            outer = self
            class Gateway(CsvGateway):
                def submit(self, detail, shop, params):
                    gate = outer.gate(output)
                    outer.assertEqual(gate["firstBatchMaterialIds"], ["m1", "m2", "m3"])
                    return super().submit(detail, shop, params)
            self.run_acquire(output, Gateway())
            self.assertEqual(self.gate(output)["status"], "passed")

    def test_partial_success_waits_for_entire_first_batch(self):
        release = threading.Event()
        first_finished = threading.Event()
        fourth_submitted = threading.Event()
        class Gateway(CsvGateway):
            def poll(self, task_id):
                mid, _ = self._tasks[task_id]
                if mid in {"m2", "m3"}:
                    release.wait(3)
                result = super().poll(task_id)
                if mid == "m1":
                    first_finished.set()
                return result
            def submit(self, detail, shop, params):
                if params["material_id"] == "m4":
                    fourth_submitted.set()
                return super().submit(detail, shop, params)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            gateway = Gateway({"m2": "failed", "m3": "failed"})
            errors = []
            def work():
                try:
                    self.run_acquire(output, gateway)
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=work)
            worker.start()
            try:
                self.assertTrue(first_finished.wait(3))
                self.assertFalse(fourth_submitted.wait(.15))
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(errors)
            self.assertFalse(worker.is_alive())
            self.assertCountEqual(gateway.submitted_material_ids, [f"m{i}" for i in range(1, 7)])
            self.assertEqual(self.gate(output)["status"], "passed")

    def test_unknown_first_result_stays_paused_even_with_one_valid_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            gateway = CsvGateway({"m2": "unknown", "m3": "failed"})
            self.run_acquire(output, gateway)
            self.assertCountEqual(gateway.submitted_material_ids, ["m1", "m2", "m3"])
            gate = self.gate(output)
            self.assertEqual(gate["status"], "unconfirmed")
            self.assertEqual(gate["validCsvMaterialIds"], ["m1"])
            self.assertNotIn("入参可能有问题", gate["message"])

    def test_valid_csv_survives_fact_write_failure_and_missing_script(self):
        import qianchuan_script_acquisition_pipeline as pipeline
        original = pipeline.atomic_json
        def fail_script_write(path, payload):
            if "facts/scripts" in Path(path).as_posix():
                raise OSError("local storage failed")
            return original(path, payload)
        for mode in ("valid", "missing_script", "mixed", "multiple_csv"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                gateway = CsvGateway({"m1": mode, "m2": "failed", "m3": "failed"})
                with patch.object(pipeline, "atomic_json", side_effect=fail_script_write):
                    self.run_acquire(output, gateway)
                self.assertEqual(self.gate(output)["status"], "passed")
                self.assertEqual(len(gateway.submitted_material_ids), 6)

    def test_short_first_batch_and_reentry_never_clear_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            gateway = CsvGateway({"m1": "failed"})
            self.run_acquire(output, gateway, count=1)
            before = (output / "first-batch-csv-gate.json").read_bytes()
            report = RecordingReportGateway(candidates())
            for count in (1, 6):
                with self.assertRaisesRegex(Exception, "当前入参可能有问题"):
                    acquire_scripts(live_request(count), output, report, gateway)
                with self.assertRaisesRegex(Exception, "当前入参可能有问题"):
                    continue_acquire_scripts(live_request(count), output, gateway)
            self.assertEqual(report.calls, 0)
            self.assertEqual(gateway.submitted_material_ids, ["m1"])
            self.assertEqual((output / "first-batch-csv-gate.json").read_bytes(), before)

    def test_downloaded_valid_csv_is_remembered_before_attempt_metadata_write(self):
        import qianchuan_script_acquisition_pipeline as pipeline
        original = pipeline._update_attempt
        def fail_csv_receipt(path, **changes):
            if any(item.get("kind") == "csv" for item in changes.get("payloadFiles", [])):
                raise OSError("local CSV receipt write failed")
            return original(path, **changes)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            gateway = CsvGateway()
            with patch.object(pipeline, "_update_attempt", side_effect=fail_csv_receipt):
                self.run_acquire(output, gateway)
            self.assertEqual(self.gate(output)["status"], "passed")
            self.assertEqual(self.gate(output)["validCsvMaterialIds"], ["m1", "m2", "m3"])
            self.assertEqual(len(gateway.submitted_material_ids), 6)


if __name__ == "__main__":
    unittest.main()
