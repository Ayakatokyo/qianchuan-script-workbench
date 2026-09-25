"""Returned page IDs remain independent from request IDs echoed by the connector."""
from argparse import Namespace
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_batch3_acquisition_pipeline import RecordingReportGateway, RecordingRpaGateway, live_request
from qianchuan_script_acquisition_identity import audit_identity, content_evidence
from short_video_foundation.qianchuan_script_acquisition.pipeline import acquire_scripts
from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaTaskResult
from short_video_foundation.script_cli import CliError, _verify


class ReturnedIdGateway(RecordingRpaGateway):
    def poll(self, task_group_id):
        material_id, _ = self._tasks[task_group_id]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=["recordType", "materialId", "materialIdTag", "materialName", "scriptInfo"], delimiter="\x01")
        writer.writeheader()
        writer.writerow({"recordType": "script_analysis", "materialId": material_id,
                         "materialIdTag": f"ID：{getattr(self, 'returned_ids', {}).get(material_id, material_id)}", "materialName": f"name-{material_id}",
                         "scriptInfo": json.dumps({"text": f"正文-{material_id}"})})
        return RpaTaskResult(task_group_id, "completed", files=({"fileName": "details.csv", "content": stream.getvalue().encode()},))


class ReturnedMaterialIdTests(unittest.TestCase):
    def test_returned_id_conflict_rejects_otherwise_identical_metadata(self):
        material = {"materialId": "101", "materialName": "相同名称", "createTime": "2026-09-01", "videoDuration": "71"}
        for tag in ("102", "ID：102", " ID： 102 "):
            with self.subTest(tag=tag):
                result = audit_identity(material, [{**material, "materialIdTag": tag}])
                self.assertEqual(result["state"], "mismatch")
                self.assertEqual(result["mismatchedFields"], ["materialIdTag"])
                self.assertEqual(result["expected"]["materialIdTag"], "101")
                self.assertEqual(result["observed"]["materialIdTag"], ["102"])
                self.assertEqual(result["identityPolicy"], "metadata_and_returned_id_v2")

    def test_explicit_returned_id_verifies_without_metadata_and_unknown_format_is_not_guessed(self):
        for tag, state in (("101", "matched"), ("ID：101", "matched"), (None, "unverified"),
                           ("other:101", "unverified"), ("ID：101 extra", "unverified"), ("ID：１２３", "unverified")):
            with self.subTest(tag=tag):
                result = audit_identity({"materialId": "101"}, [{"materialId": "101", "materialIdTag": tag}])
                self.assertEqual(result["state"], state)
        missing = audit_identity({"materialId": "101", "materialName": "name"}, [{"materialId": "101", "materialName": "name"}])
        self.assertEqual(missing["state"], "matched")

    def make_run(self, directory, returned_ids=None):
        output = Path(directory)
        rows = [{"materialId": str(i), "materialName": f"name-{i}", "metrics": {"综合成本": str(200-i)}} for i in (101, 102, 103)]
        gateway = ReturnedIdGateway({str(i): "completed" for i in (101, 102, 103)})
        gateway.returned_ids = returned_ids or {}
        acquire_scripts(live_request(), output, RecordingReportGateway(rows), gateway)
        return output, json.loads((output / "acquisition-results.json").read_text())

    def test_returned_id_conflict_follows_strict_recovery_and_never_admits_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output, outcomes = self.make_run(directory, {"102": "101"})
            rejected = outcomes["materials"][1]
            self.assertEqual(rejected["state"], "failed")
            self.assertEqual(len(rejected["attempts"]), 3)
            self.assertTrue(all(attempt["mismatchedFields"] == ["materialIdTag"] for attempt in rejected["attempts"]))
            pack = json.loads((output / "facts/qianchuan-script-source-pack.json").read_text())
            self.assertEqual(pack["scripts"][1]["rawText"], "")
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_verify_supports_legacy_fingerprints_without_reinterpreting_archived_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            output, outcomes = self.make_run(directory)
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")
            for material in outcomes["materials"]:
                for attempt in material["attempts"]:
                    identity_file = output / attempt["identityAuditPath"]
                    identity = json.loads(identity_file.read_text())
                    identity.pop("identityPolicy", None)
                    identity.pop("returnedMaterialIdTags", None)
                    identity["expected"].pop("materialIdTag", None)
                    identity["observed"].pop("materialIdTag", None)
                    identity["comparedFields"] = [key for key in identity["comparedFields"] if key != "materialIdTag"]
                    identity_file.write_text(json.dumps(identity))
                    # Old acquisition already stored content fingerprints, but its
                    # observed identity digest did not contain materialIdTag.
                    attempt["observedIdentitySha256"] = content_evidence([], identity)["observedIdentitySha256"]
                    (output / attempt["attemptRecordPath"]).write_text(json.dumps(attempt))
            (output / "acquisition-results.json").write_text(json.dumps(outcomes))
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_verify_rejects_unknown_identity_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            output, outcomes = self.make_run(directory)
            path = output / outcomes["materials"][0]["attempts"][0]["identityAuditPath"]
            value = json.loads(path.read_text())
            value["identityPolicy"] = "future_unrecognized_policy"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(CliError, "unknown identity policy"):
                _verify(Namespace(path=output))
