"""Regressions for diagnosis content returned under the requested material ID."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from test_batch3_acquisition_pipeline import RecordingReportGateway, RecordingRpaGateway, csv_files, live_request
from short_video_foundation.qianchuan_script_acquisition.contracts import AcquisitionRequest
from short_video_foundation.qianchuan_script_acquisition.pipeline import acquire_scripts
from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaTaskResult
from short_video_foundation.script_cli import CliError, _describe_acquire, _normalize_acquisition_payload, _preview_acquire, _verify
from qianchuan_script_acquisition_identity import content_evidence


def candidates(count=6):
    return [{"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i,
             "metrics": {"综合成本": str(20-i)}} for i in range(1, count+1)]


class MismatchingGateway(RecordingRpaGateway):
    def __init__(self, mismatches=2, count=6, mismatch_materials=("m2",)):
        super().__init__({f"m{i}": "completed" for i in range(1, count+1)})
        self.mismatches = mismatches
        self.mismatch_materials = mismatch_materials
        self.active = 0
        self.submissions = []
        self.lock = threading.Lock()
        self.first_batch = threading.Barrier(3)

    def submit(self, detail, rpa_shop, params):
        with self.lock:
            task_id = super().submit(detail, rpa_shop, params)
            self.active += 1
            self.submissions.append((*self._tasks[task_id], self.active))
        return task_id

    def poll(self, task_group_id):
        material_id, attempt = self._tasks[task_group_id]
        if attempt == 1 and material_id in {"m1", "m2", "m3"}:
            self.first_batch.wait(timeout=5)
        else:
            time.sleep(0.005)
        wrong = material_id in self.mismatch_materials and attempt <= self.mismatches
        record = {"recordType": "script_analysis", "materialId": material_id,
                  "materialName": "name-m1" if wrong else f"name-{material_id}",
                  "scriptInfo": {"formula": {"labels": ["结构"]},
                                 "text": "他人脚本" if wrong or material_id == "m1" else "匹配脚本"}}
        with self.lock:
            self.active -= 1
        return RpaTaskResult(task_group_id, "completed", files=csv_files((record,)))


class IdentityRecoveryTests(unittest.TestCase):
    def run_acquisition(self, directory, gateway, limit=None, count=6):
        request = live_request(count)
        if limit is not None:
            payload = request.to_dict()
            payload["liveAcquire"]["identityRetryLimit"] = limit
            request = AcquisitionRequest.from_dict(payload)
        output = Path(directory) / "run-identity"
        acquire_scripts(request, output, RecordingReportGateway(candidates(count)), gateway)
        return output, json.loads((output / "acquisition-results.json").read_text())

    def test_retry_limit_rejects_invalid_values_and_public_alias_reaches_preview(self):
        for value in (-1, 4, True, "2", 1.5):
            payload = live_request().to_dict()
            payload["liveAcquire"]["identityRetryLimit"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "identityRetryLimit"):
                AcquisitionRequest.from_dict(payload)
        normalized = _normalize_acquisition_payload({
            "schemaVersion": 1, "api_shop": "shop-A", "rpa_shop": "rpa-C",
            "date_range": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
            "identity_retry_limit": 0,
        })
        self.assertEqual(normalized["liveAcquire"].get("identityRetryLimit"), 0)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(normalized))
            self.assertEqual(_preview_acquire(Namespace(input=source))["identityRetryLimit"], 0)
        descriptor = next(item for item in _describe_acquire(Namespace())["requiredInputs"]
                          if item["path"] == "liveAcquire.identityRetryLimit")
        self.assertEqual((descriptor["default"], descriptor["minimum"], descriptor["maximum"]), (2, 0, 3))

    def test_mismatch_drains_then_prioritizes_serial_retries_and_keeps_all_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = MismatchingGateway()
            output, outcomes = self.run_acquisition(directory, gateway)
            retry = outcomes["materials"][1]
            self.assertEqual(retry["state"], "available")
            self.assertEqual(len(retry["attempts"]), 3)
            self.assertEqual(gateway.submissions[3:5], [("m2", 2, 1), ("m2", 3, 1)])
            self.assertTrue(all(active == 1 for _, _, active in gateway.submissions[3:]))
            self.assertEqual(outcomes["scheduler"]["effectiveConcurrency"], 1)
            self.assertEqual(outcomes["identityRetryLimit"], 2)
            for filename in ("status.json", "acquisition-receipt.json"):
                self.assertEqual(json.loads((output / filename).read_text())["identityRetryLimit"], 2)
            first, second, third = retry["attempts"]
            self.assertTrue(first["scriptContentPresent"])
            self.assertEqual(first["scriptContentSha256"], second["scriptContentSha256"])
            self.assertEqual(first["observedIdentitySha256"], second["observedIdentitySha256"])
            self.assertNotEqual(first["scriptContentSha256"], third["scriptContentSha256"])
            self.assertEqual(first["scriptContentSha256"], outcomes["materials"][0]["attempts"][0]["scriptContentSha256"])
            self.assertEqual(first["observedIdentitySha256"], outcomes["materials"][0]["attempts"][0]["observedIdentitySha256"])
            pack = json.loads((output / "facts/qianchuan-script-source-pack.json").read_text())
            script = pack["scripts"][1]
            self.assertEqual(script["rawText"], "匹配脚本")
            for attempt in retry["attempts"]:
                self.assertIn(attempt["attemptRecordPath"], script["sourceRefs"])
            self.assertNotIn(first["attemptRecordPath"], script["fieldSourceRefs"]["text"])
            self.assertNotIn(second["attemptRecordPath"], script["fieldSourceRefs"]["text"])
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_retry_budget_exhaustion_never_admits_wrong_text(self):
        for limit in (0, 1, 3):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                gateway = MismatchingGateway(mismatches=20)
                output, outcomes = self.run_acquisition(directory, gateway, limit)
                failed = outcomes["materials"][1]
                self.assertEqual(len(failed["attempts"]), 1 + limit)
                self.assertEqual(failed["errorCode"], "material_identity_mismatch")
                self.assertEqual(outcomes["status"], "partialFailed")
                script = json.loads((output / "facts/qianchuan-script-source-pack.json").read_text())["scripts"][1]
                self.assertEqual(script["rawText"], "")
                self.assertEqual(script["fieldSourceRefs"]["text"], [])
                self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_verify_rejects_forged_content_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            output, outcomes = self.run_acquisition(directory, MismatchingGateway())
            self.assertEqual(outcomes["materials"][1]["state"], "available")
            attempt = outcomes["materials"][1]["attempts"][0]
            attempt["scriptContentSha256"] = "0" * 64
            (output / attempt["attemptRecordPath"]).write_text(json.dumps(attempt))
            (output / "acquisition-results.json").write_text(json.dumps(outcomes))
            with self.assertRaisesRegex(CliError, "fingerprint"):
                _verify(Namespace(path=output))

    def test_verify_enforces_declared_budget_and_every_retry_predecessor(self):
        for mutation, message in (("budget", "attempt sequence"), ("predecessor", "preceding terminal mismatch"), ("identity", "identity audit")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                output, outcomes = self.run_acquisition(directory, MismatchingGateway())
                if mutation == "budget":
                    for name in ("status.json", "acquisition-receipt.json", "acquisition-results.json"):
                        value = json.loads((output / name).read_text())
                        value["identityRetryLimit"] = 1
                        (output / name).write_text(json.dumps(value))
                elif mutation == "predecessor":
                    outcomes["materials"][1]["attempts"][1]["identityState"] = "unverified"
                    (output / "acquisition-results.json").write_text(json.dumps(outcomes))
                else:
                    attempt = outcomes["materials"][1]["attempts"][0]
                    identity_path = output / attempt["identityAuditPath"]
                    identity = json.loads(identity_path.read_text())
                    identity["observed"]["materialName"] = ["forged-name"]
                    identity_path.write_text(json.dumps(identity))
                with self.assertRaisesRegex(CliError, message):
                    _verify(Namespace(path=output))

    def test_multiple_mismatches_are_recovered_without_overlapping_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = MismatchingGateway(mismatches=1, mismatch_materials=("m2", "m3"))
            output, outcomes = self.run_acquisition(directory, gateway)
            self.assertEqual(outcomes["status"], "ready")
            self.assertEqual(sorted(gateway.submissions[3:5]), [("m2", 2, 1), ("m3", 2, 1)])
            self.assertTrue(all(active == 1 for _, _, active in gateway.submissions[3:]))
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_unknown_recovery_task_stops_new_submissions_and_preserves_prior_evidence(self):
        class UnknownRetryGateway(MismatchingGateway):
            def poll(self, task_group_id):
                if self._tasks[task_group_id] == ("m2", 2):
                    raise RuntimeError("connection interrupted after submission")
                return super().poll(task_group_id)
        with tempfile.TemporaryDirectory() as directory:
            gateway = UnknownRetryGateway()
            output, outcomes = self.run_acquisition(directory, gateway)
            self.assertEqual(len(gateway.submissions), 4)
            self.assertEqual(outcomes["materials"][1]["state"], "submissionUnknown")
            self.assertTrue(all(item["state"] == "unsubmitted" for item in outcomes["materials"][3:]))
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_inflight_submission_keeps_its_original_mode_after_later_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run-identity"
            observed_path = output / "source-data/identity" / (hashlib.sha256(b"m4").hexdigest()[:16] + "-attempt-01.json")
            second_wave_dispatched = threading.Event()
            late_submit_returned = threading.Event()

            class SlowSubmitGateway(RecordingRpaGateway):
                def submit(self, detail, shop, params):
                    if params["material_id"] == "m6":
                        second_wave_dispatched.set()
                        deadline = time.monotonic() + 3
                        while not observed_path.exists() and time.monotonic() < deadline:
                            time.sleep(0.001)
                        if not observed_path.exists():
                            raise RuntimeError("mismatch result was never processed")
                    result = super().submit(detail, shop, params)
                    if params["material_id"] == "m6":
                        late_submit_returned.set()
                    return result

                def poll(self, task_group_id):
                    material_id, attempt = self._tasks[task_group_id]
                    if material_id == "m4" and attempt == 1:
                        second_wave_dispatched.wait(3)
                        record = {"recordType": "script_analysis", "materialId": "m4", "materialName": "name-m1", "scriptInfo": {"text": "错配"}}
                        return RpaTaskResult(task_group_id, "completed", files=csv_files((record,)))
                    if material_id == "m5":
                        late_submit_returned.wait(3)
                    return super().poll(task_group_id)

            gateway = SlowSubmitGateway({f"m{i}": "completed" for i in range(1, 8)})
            output, outcomes = self.run_acquisition(directory, gateway, count=7)
            late = next(event for event in outcomes["scheduler"]["events"] if event["materialId"] == "m6")
            self.assertFalse(late["identityRecovery"])
            self.assertEqual(outcomes["status"], "ready")
            self.assertEqual(gateway.submitted_material_ids[-2:], ["m4", "m7"])
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_empty_script_object_is_not_reported_as_returned_content(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"},
                script_infos={"m2": {"formula": {"labels": []}, "detail": {}, "text": " ", "data": []}})
            output, outcomes = self.run_acquisition(directory, gateway, count=3)
            self.assertFalse(outcomes["materials"][1]["attempts"][0].get("scriptContentPresent", True))

    def test_content_presence_requires_real_text_or_structure_without_formula_type_gate(self):
        for formula in (None, {}, [], "unexpected"):
            with self.subTest(formula=formula):
                evidence = content_evidence([{"recordType": "script_analysis", "scriptInfo": {
                    "formula": formula, "text": "实际正文",
                }}], {"observed": {}})
                self.assertTrue(evidence["scriptContentPresent"])
        evidence = content_evidence([{"recordType": "script_analysis", "scriptInfo": {
            "formula": {"labels": []}, "text": 123, "detail": {}, "data": [],
        }}], {"observed": {}})
        self.assertFalse(evidence["scriptContentPresent"])

    def test_verify_resolves_report_ids_with_the_selection_registry(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as directory:
                rows = candidates(3)
                for row in rows:
                    material_id = row.pop("materialId")
                    if nested:
                        row["dimensions"] = {"素材ID": {"Value": material_id}}
                    else:
                        row["素材ID"] = material_id
                output = Path(directory) / "run-alias"
                acquire_scripts(live_request(3), output, RecordingReportGateway(rows),
                                RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"}))
                self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")


if __name__ == "__main__":
    unittest.main()
