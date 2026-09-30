import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from short_video_foundation.qianchuan_script_acquisition.contracts import AcquisitionRequest
from short_video_foundation.qianchuan_script_acquisition.pipeline import acquire_scripts, continue_acquire_scripts
from short_video_foundation.qianchuan_script_acquisition.report_client import ReportClientError
from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaTaskResult


def csv_files(records):
    """Successful test tasks return the actual transport format, not only JSON."""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["recordType", "materialId", "materialName", "scriptInfo"], delimiter="\x01")
    writer.writeheader()
    for record in records:
        writer.writerow({**record, "scriptInfo": json.dumps(record.get("scriptInfo", {}), ensure_ascii=False)})
    return ({"fileName": "details.csv", "content": stream.getvalue().encode()},)


def live_request(top_n=3):
    return AcquisitionRequest.from_dict({
        "liveAcquire": {
            "apiShop": "shop-A",
            "advertiserId": "1770096415226951",
            "rpaShop": "rpa-C",
            "topN": top_n,
            "materialFilterSort": {"sortField": "综合成本", "direction": "desc", "filters": []},
        },
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
    })


class RecordingReportGateway:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    def fetch_material_report(self, request, output_dir):
        self.calls += 1
        return self.candidates


class RecordingRpaGateway:
    def __init__(self, outcomes, script_infos=None):
        self.outcomes = outcomes
        self.script_infos = script_infos or {}
        self.submitted_material_ids = []
        self._tasks = {}
        self._submission_counts = {}
        self.connector_calls = 0

    def connector_detail(self):
        self.connector_calls += 1
        return {
            "connectorCode": "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis",
            "platformCode": "RPA_DOUDIAN",
            "inParamJsonSchemaText": '{"type":"object","required":["material_id","date_type"],"properties":{"material_id":{"type":"string"},"date_type":{"type":"string"},"custom_start_date":{"type":"string"},"custom_end_date":{"type":"string"}}}',
        }

    def authorize(self, rpa_shop):
        self.authorized = rpa_shop

    def submit(self, detail, rpa_shop, params):
        material_id = params["material_id"]
        self.submitted_material_ids.append(material_id)
        attempt = self._submission_counts.get(material_id, 0) + 1
        self._submission_counts[material_id] = attempt
        task_id = f"task-{material_id}-{attempt}"
        self._tasks[task_id] = (material_id, attempt)
        return task_id

    def poll(self, task_group_id):
        material_id, attempt = self._tasks[task_group_id]
        outcome = self.outcomes[material_id]
        if isinstance(outcome, list):
            outcome = outcome[min(attempt - 1, len(outcome) - 1)]
        if outcome == "failed":
            return RpaTaskResult(task_group_id, "failed")
        records = ({
            "recordType": "script_analysis",
            "materialId": material_id,
            "materialName": f"name-{material_id}",
            "scriptInfo": self.script_infos.get(material_id, {"text": "共享参考脚本" if material_id != "m1" else "参考脚本一"}),
        },)
        return RpaTaskResult(task_group_id, outcome, files=csv_files(records), records=records)


class WaveRecordingRpaGateway:
    """A deterministic in-process gateway that exposes wave boundaries."""

    def __init__(self, outcomes, delays=None, wave_size=3):
        self.outcomes = outcomes
        self.delays = delays or {}
        self.wave_size = wave_size
        self.submitted_material_ids = []
        self.terminal_material_ids = []
        self.max_active = 0
        self.active = 0
        self.later_wave_started_after_prior_terminal = True
        self._lock = threading.Lock()
        self._tasks = {}

    def connector_detail(self):
        return {
            "connectorCode": "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis",
            "platformCode": "RPA_DOUDIAN",
            "inParamJsonSchemaText": '{"type":"object","required":["material_id","date_type"],"properties":{"material_id":{"type":"string"},"date_type":{"type":"string"},"custom_start_date":{"type":"string"},"custom_end_date":{"type":"string"}}}',
        }

    def authorize(self, _rpa_shop):
        return None

    def submit(self, _detail, _rpa_shop, params):
        material_id = params["material_id"]
        with self._lock:
            self.submitted_material_ids.append(material_id)
            wave = (len(self.submitted_material_ids) - 1) // self.wave_size
            if wave > 0 and len(self.terminal_material_ids) < wave * self.wave_size:
                self.later_wave_started_after_prior_terminal = False
            task_id = f"task-{material_id}"
            self._tasks[task_id] = (material_id, wave)
            return task_id

    def poll(self, task_group_id):
        material_id, wave = self._tasks[task_group_id]
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            delay = self.delays.get(material_id, 0.02)
            if delay:
                time.sleep(delay)
            with self._lock:
                self.terminal_material_ids.append(material_id)
            if self.outcomes[material_id] == "failed":
                return RpaTaskResult(task_group_id, "failed")
            records = ({
                    "recordType": "script_analysis",
                    "materialId": material_id,
                    "materialName": f"name-{material_id}",
                    "scriptInfo": {"text": f"脚本-{material_id}"},
                },)
            return RpaTaskResult(task_group_id, self.outcomes[material_id], files=csv_files(records), records=records)
        finally:
            with self._lock:
                self.active -= 1


class Batch3AcquisitionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"materialId": "m1", "materialName": "name-m1", "rank": 1, "metrics": {"综合成本": "10"}, "sourceRefs": ["report:m1"]},
            {"materialId": "m2", "materialName": "name-m2", "rank": 2, "metrics": {"综合成本": "9"}, "sourceRefs": ["report:m2"]},
            {"materialId": "m3", "materialName": "name-m3", "rank": 3, "metrics": {"综合成本": "8"}, "sourceRefs": ["report:m3"]},
        ]

    def test_blank_selection_uses_overall_spend_for_rpa_targets(self):
        rows = copy.deepcopy(self.candidates[:2])
        rows[0]["metrics"].update({"整体消耗": "5", "整体千次展现费用": "100"})
        rows[1]["metrics"].update({"整体消耗": "20", "整体千次展现费用": "1"})
        for mode in ("omitted", "empty", "null"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                live = {"apiShop": "shop-A", "advertiserId": "1770096415226951",
                        "rpaShop": "rpa-C", "topN": 1}
                if mode != "omitted":
                    live["materialFilterSort"] = {} if mode == "empty" else None
                request = AcquisitionRequest.from_dict({"liveAcquire": live,
                    "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"}})
                rpa = RecordingRpaGateway({"m2": "completed"})
                output = Path(directory)
                acquire_scripts(request, output, RecordingReportGateway(rows), rpa)
                selection = json.loads((output / "material-selection.json").read_text())
                self.assertEqual(selection["ranking"]["fieldId"], "stat_cost_for_roi2")
                self.assertEqual(selection["ranking"]["direction"], "desc")
                self.assertEqual(selection["filters"], [])
                self.assertEqual(rpa.submitted_material_ids, ["m2"])

    def test_successful_acquisition_preserves_hashes_and_deduplicates_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rpa = RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"})
            result = acquire_scripts(live_request(3), output, RecordingReportGateway(self.candidates), rpa)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["availability"], {"requested": 3, "available": 3, "missing": 0, "failed": 0})
            self.assertEqual(payload["deduplication"]["uniqueScriptCount"], 2)
            self.assertEqual(payload["scripts"][0]["rawTextSha256"].__len__(), 64)
            self.assertEqual(payload["scripts"][0]["rawTextSha256"], payload["scripts"][0]["rawTextSha256"].lower())
            fact_ref = payload["scripts"][0]["materialFile"]
            self.assertTrue((output / fact_ref).is_file())
            self.assertEqual(len(payload["scripts"][0]["materialFileSha256"]), 64)
            fact = json.loads((output / fact_ref).read_text(encoding="utf-8"))
            self.assertEqual((fact["materialId"], fact["identityState"]), (payload["scripts"][0]["materialId"], "matched"))
            self.assertEqual(json.loads((output / "acquisition-results.json").read_text(encoding="utf-8"))["scheduler"]["maxConcurrency"], 3)
            self.assertFalse(any(path.suffix in {".mp4", ".jpg", ".png"} for path in output.rglob("*") if path.is_file()))
            self.assertEqual(json.loads((output / "status.json").read_text(encoding="utf-8"))["state"], "ready")
            from argparse import Namespace
            from short_video_foundation.script_cli import CliError, _verify
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")
            fact_path = output / fact_ref
            fact_path.write_text(fact_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(CliError, "hash"):
                _verify(Namespace(path=output))

    def test_aigc_sentinel_is_audited_without_detail_rpa_submission(self):
        candidates = [
            {"materialId": "101", "materialName": "name-101", "metrics": {"综合成本": "100"}},
            {"materialId": "-2", "materialName": "AIGC动态创意视频素材集合", "metrics": {"综合成本": "90"}},
            {"materialId": "102", "materialName": "name-102", "metrics": {"综合成本": "80"}},
            {"materialId": "103", "materialName": "name-103", "metrics": {"综合成本": "70"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rpa = RecordingRpaGateway({mid: "completed" for mid in ("101", "102", "103")})
            acquire_scripts(live_request(3), output, RecordingReportGateway(candidates), rpa)
            selection = json.loads((output / "material-selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["selectedMaterialIds"], ["101", "102", "103"])
            self.assertEqual(selection["excludedRows"], [
                {"rowNumber": 2, "reason": "material_id_unavailable", "fieldId": "material_id", "materialId": "-2"}
            ])
            self.assertEqual(rpa.submitted_material_ids, ["101", "102", "103"])
            self.assertEqual(json.loads((output / "status.json").read_text(encoding="utf-8"))["state"], "ready")

    def test_formula_fields_are_separate_and_missing_content_is_explicit(self):
        infos = {
            "m1": {"formula": {"labels": ["痛点", "解决方案"]}, "detail": {"labels": ["特写"]}, "data": [{"key": "value"}], "text": "完整口播正文"},
            "m2": {"formula": None, "detail": None, "data": [], "text": "只有口播正文"},
            "m3": {"formula": {"labels": ["反差"]}, "detail": None, "data": None, "text": None},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = acquire_scripts(
                live_request(3), output, RecordingReportGateway(self.candidates),
                RecordingRpaGateway({"m1": "completed", "m2": "completed", "m3": "completed"}, infos),
            )
            pack = json.loads(result.read_text(encoding="utf-8"))
            first, second, third = pack["scripts"]
            self.assertEqual(first["formula"], infos["m1"]["formula"])
            self.assertEqual(first["text"], "完整口播正文")
            self.assertNotIn("痛点", first["rawText"])
            self.assertTrue(first["completeness"]["formulaLabels"])
            self.assertIsNone(second["formula"])
            self.assertFalse(second["completeness"]["formulaLabels"])
            self.assertEqual(second["text"], "只有口播正文")
            self.assertEqual(third["parseStatus"], "missing")
            self.assertEqual(third["formula"], infos["m3"]["formula"])
            self.assertFalse(third["completeness"]["transcript"])
            self.assertEqual(pack["contentAvailability"], {
                "formulaLabels": {"available": 2, "missing": 1},
                "detailLabels": {"available": 1, "missing": 2},
                "structuredData": {"available": 1, "missing": 2},
                "transcript": {"available": 2, "missing": 1},
            })
            from argparse import Namespace
            from short_video_foundation.script_cli import _verify
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

    def test_terminal_single_material_failure_does_not_stop_later_waves(self):
        candidates = self.candidates + [
            {"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i, "metrics": {"综合成本": str(11 - i)}, "sourceRefs": [f"report:m{i}"]}
            for i in range(4, 7)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rpa = RecordingRpaGateway({f"m{i}": "failed" if i == 2 else "completed" for i in range(1, 7)})
            result = acquire_scripts(live_request(6), output, RecordingReportGateway(candidates), rpa)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertCountEqual(rpa.submitted_material_ids, [f"m{i}" for i in range(1, 7)])
            self.assertEqual(payload["availability"]["failed"], 1)
            self.assertEqual(payload["availability"]["available"], 5)
            self.assertEqual(json.loads((output / "status.json").read_text(encoding="utf-8"))["state"], "partialFailed")

    def test_rpa_runs_in_waves_of_at_most_three(self):
        candidates = self.candidates + [
            {"materialId": "m4", "materialName": "name-m4", "rank": 4, "metrics": {"综合成本": "7"}, "sourceRefs": ["report:m4"]},
            {"materialId": "m5", "materialName": "name-m5", "rank": 5, "metrics": {"综合成本": "6"}, "sourceRefs": ["report:m5"]},
            {"materialId": "m6", "materialName": "name-m6", "rank": 6, "metrics": {"综合成本": "5"}, "sourceRefs": ["report:m6"]},
        ]
        outcomes = {material["materialId"]: "completed" for material in candidates}
        rpa = WaveRecordingRpaGateway(outcomes)

        with tempfile.TemporaryDirectory() as directory:
            result = acquire_scripts(live_request(6), Path(directory), RecordingReportGateway(candidates), rpa)
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(rpa.max_active, 3)
        self.assertCountEqual(rpa.submitted_material_ids, ["m1", "m2", "m3", "m4", "m5", "m6"])
        self.assertEqual(set(rpa.terminal_material_ids), {"m1", "m2", "m3", "m4", "m5", "m6"})
        self.assertEqual(payload["availability"]["available"], 6)

    def test_top10_stays_within_three_active_tasks_and_records_underfill_reason(self):
        candidates = [
            {"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i, "metrics": {"综合成本": str(20 - i)}, "sourceRefs": [f"report:m{i}"]}
            for i in range(1, 11)
        ]
        rpa = WaveRecordingRpaGateway({item["materialId"]: "completed" for item in candidates})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            acquire_scripts(live_request(10), output, RecordingReportGateway(candidates), rpa)
            receipt = json.loads((output / "acquisition-results.json").read_text(encoding="utf-8"))["scheduler"]
        self.assertEqual(rpa.max_active, 3)
        self.assertEqual(receipt["maxConcurrency"], 3)
        self.assertEqual(receipt["submittedTaskCount"], 10)
        self.assertTrue(all(item["inFlight"] <= 3 for item in receipt["events"]))
        self.assertEqual(receipt["underfillReason"], "remaining_queue_exhausted")

    def test_completed_material_fact_is_readable_before_other_tasks_finish(self):
        release_slow = threading.Event()
        fourth_submitted = threading.Event()

        class RollingGateway(RecordingRpaGateway):
            def __init__(self, outcomes):
                super().__init__(outcomes)
                self.terminal = set()

            def submit(self, detail, rpa_shop, params):
                task_id = super().submit(detail, rpa_shop, params)
                if params["material_id"] == "m4":
                    fourth_submitted.set()
                return task_id

            def poll(self, task_id):
                material_id, _attempt = self._tasks[task_id]
                if material_id in {"m2", "m3"}:
                    release_slow.wait(timeout=3)
                result = super().poll(task_id)
                self.terminal.add(material_id)
                return result

        candidates = self.candidates + [
            {"materialId": "m4", "materialName": "name-m4", "rank": 4, "metrics": {"综合成本": "7"}, "sourceRefs": ["report:m4"]},
        ]
        output = Path(tempfile.mkdtemp(prefix="batch3-rolling-fact-"))
        gateway = RollingGateway({f"m{i}": "completed" for i in range(1, 5)})
        worker = threading.Thread(
            target=lambda: acquire_scripts(live_request(4), output, RecordingReportGateway(candidates), gateway),
            daemon=True,
        )
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while not list((output / "facts" / "scripts").glob("*.json")) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(fourth_submitted.is_set())
            fact = next((output / "facts" / "scripts").glob("*.json"))
            self.assertEqual(json.loads(fact.read_text(encoding="utf-8"))["materialId"], "m1")
            self.assertTrue({"m2", "m3"}.isdisjoint(gateway.terminal))
        finally:
            release_slow.set()
            worker.join(timeout=5)
            import shutil
            shutil.rmtree(output, ignore_errors=True)
        self.assertFalse(worker.is_alive())

    def test_failed_wave_finishes_inflight_tasks_and_continues_next_wave(self):
        candidates = self.candidates + [
            {"materialId": "m4", "materialName": "name-m4", "rank": 4, "metrics": {"综合成本": "7"}, "sourceRefs": ["report:m4"]},
            {"materialId": "m5", "materialName": "name-m5", "rank": 5, "metrics": {"综合成本": "6"}, "sourceRefs": ["report:m5"]},
            {"materialId": "m6", "materialName": "name-m6", "rank": 6, "metrics": {"综合成本": "5"}, "sourceRefs": ["report:m6"]},
        ]
        outcomes = {"m1": "completed", "m2": "failed", "m3": "completed", "m4": "completed", "m5": "completed", "m6": "completed"}
        rpa = WaveRecordingRpaGateway(outcomes)

        with tempfile.TemporaryDirectory() as directory:
            result = acquire_scripts(live_request(6), Path(directory), RecordingReportGateway(candidates), rpa)
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertCountEqual(rpa.submitted_material_ids, ["m1", "m2", "m3", "m4", "m5", "m6"])
        self.assertEqual(set(rpa.terminal_material_ids), {"m1", "m2", "m3", "m4", "m5", "m6"})
        self.assertEqual(payload["availability"], {"requested": 6, "available": 5, "missing": 0, "failed": 1})

    def test_concurrent_completion_keeps_ranked_output_order(self):
        candidates = self.candidates + [
            {"materialId": "m4", "materialName": "name-m4", "rank": 4, "metrics": {"综合成本": "7"}, "sourceRefs": ["report:m4"]},
        ]
        outcomes = {material["materialId"]: "completed" for material in candidates}
        rpa = WaveRecordingRpaGateway(outcomes, delays={"m1": 0.25, "m2": 0.02, "m3": 0.01, "m4": 0.01})

        with tempfile.TemporaryDirectory() as directory:
            result = acquire_scripts(live_request(4), Path(directory), RecordingReportGateway(candidates), rpa)
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual([item["materialId"] for item in payload["materials"]], ["m1", "m2", "m3", "m4"])
        self.assertEqual([item["materialId"] for item in payload["scripts"]], ["m1", "m2", "m3", "m4"])

    def test_same_run_resume_does_not_submit_again_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rpa = RecordingRpaGateway({"m1": "completed"})
            first = acquire_scripts(live_request(1), output, RecordingReportGateway(self.candidates[:1]), rpa)
            original = first.read_bytes()
            second = acquire_scripts(live_request(1), output, RecordingReportGateway(self.candidates[:1]), rpa)
            self.assertEqual(first, second)
            self.assertEqual(original, second.read_bytes())
            self.assertEqual(rpa.submitted_material_ids, ["m1"])

    def test_unknown_selection_saves_full_report_then_continues_without_refetch(self):
        unresolved = AcquisitionRequest.from_dict({
            "liveAcquire": {
                "apiShop": "shop-A",
                "advertiserId": "1770096415226951",
                "rpaShop": "rpa-C",
                "topN": 1,
                "materialFilterSort": {"sortField": "尚未注册的口径", "direction": "desc", "filters": []},
            },
            "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        })
        report = RecordingReportGateway(self.candidates)
        rpa = RecordingRpaGateway({"m1": "completed"})

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run-pending"
            result = acquire_scripts(unresolved, output, report, rpa)
            status = json.loads((output / "status.json").read_text(encoding="utf-8"))
            snapshot = json.loads(result.read_text(encoding="utf-8"))
            pending = json.loads((output / "selection-pending.json").read_text(encoding="utf-8"))

            self.assertEqual(status["state"], "awaitingSelection")
            self.assertTrue(snapshot["complete"])
            self.assertEqual(snapshot["recordCount"], len(self.candidates))
            self.assertEqual(pending["reportRowCount"], len(self.candidates))
            self.assertEqual(report.calls, 1)
            self.assertEqual(rpa.connector_calls, 0)
            self.assertEqual(rpa.submitted_material_ids, [])
            from argparse import Namespace
            from short_video_foundation.script_cli import _verify
            self.assertEqual(_verify(Namespace(path=output))["status"], "awaitingSelection")
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")

            continued = continue_acquire_scripts(live_request(top_n=1), output, rpa)
            pack = json.loads(continued.read_text(encoding="utf-8"))
            selection = json.loads((output / "material-selection.json").read_text(encoding="utf-8"))

            self.assertEqual(report.calls, 1)
            self.assertEqual(rpa.submitted_material_ids, ["m1"])
            self.assertEqual(selection["ranking"]["fieldId"], "stat_cost_for_overall_roi2")
            self.assertEqual([item["materialId"] for item in pack["materials"]], ["m1"])
            self.assertTrue((output / "selection-resolution.json").is_file())

    def test_report_snapshot_scope_and_hash_are_required_for_continuation(self):
        unresolved = AcquisitionRequest.from_dict({
            "liveAcquire": {
                "apiShop": "shop-A",
                "advertiserId": "1770096415226951",
                "rpaShop": "rpa-C",
                "topN": 1,
                "materialFilterSort": {"sortField": "未知口径", "direction": "desc", "filters": []},
            },
            "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        })
        rpa = RecordingRpaGateway({"m1": "completed"})

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run-pending"
            acquire_scripts(unresolved, output, RecordingReportGateway(self.candidates), rpa)
            changed_scope = unresolved.to_dict()
            changed_scope["liveAcquire"]["rpaShop"] = "rpa-different"
            with self.assertRaisesRegex(ReportClientError, "acquisition scope"):
                continue_acquire_scripts(AcquisitionRequest.from_dict(changed_scope), output, rpa)
            self.assertEqual(rpa.connector_calls, 0)
            self.assertEqual(rpa.submitted_material_ids, [])

            pending_path = output / "selection-pending.json"
            original_pending = pending_path.read_bytes()
            pending = json.loads(original_pending)
            pending["reportSnapshotSha256"] = "0" * 64
            pending_path.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ReportClientError, "selection-pending receipt"):
                continue_acquire_scripts(live_request(top_n=1), output, rpa)
            pending_path.write_bytes(original_pending)

            rpa_evidence = output / "source-data" / "rpa" / "stale-records.json"
            rpa_evidence.parent.mkdir(parents=True, exist_ok=True)
            rpa_evidence.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ReportClientError, "RPA evidence already exists"):
                continue_acquire_scripts(live_request(top_n=1), output, rpa)
            rpa_evidence.unlink()

            snapshot_path = output / "source-data" / "material-report-snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["rows"].pop()
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(ReportClientError):
                continue_acquire_scripts(live_request(top_n=1), output, rpa)
            self.assertEqual(rpa.connector_calls, 0)
            self.assertEqual(rpa.submitted_material_ids, [])

    def test_all_unusable_rank_values_wait_after_saving_report_without_rpa(self):
        report = RecordingReportGateway([
            {"materialId": "m1", "metrics": {"综合成本": "-"}},
            {"materialId": "m2", "metrics": {"综合成本": None}},
        ])
        rpa = RecordingRpaGateway({})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run-pending"
            snapshot_path = acquire_scripts(live_request(top_n=2), output, report, rpa)
            status = json.loads((output / "status.json").read_text(encoding="utf-8"))
            pending = json.loads((output / "selection-pending.json").read_text(encoding="utf-8"))
            selection = json.loads((output / "material-selection.json").read_text(encoding="utf-8"))

            self.assertTrue(snapshot_path.is_file())
            self.assertEqual(report.calls, 1)
            self.assertEqual(status["state"], "awaitingSelection")
            self.assertEqual(pending["errorCode"], "selection_metric_unavailable")
            self.assertEqual(selection["systemicError"], "all_matching_rows_have_unusable_sort_value")
            self.assertEqual(len(selection["excludedRows"]), 2)
            self.assertEqual(rpa.connector_calls, 0)
            self.assertEqual(rpa.submitted_material_ids, [])
            from argparse import Namespace
            from short_video_foundation.script_cli import _verify
            verification = _verify(Namespace(path=output))
            self.assertEqual(verification["status"], "awaitingSelection")
            self.assertIn("material-selection.json", verification["checkedFiles"])

    def test_identity_mismatch_retries_once_with_immutable_evidence_then_continues(self):
        class WrongFirstAttemptGateway(RecordingRpaGateway):
            def poll(self, task_group_id):
                result = super().poll(task_group_id)
                material_id, attempt = self._tasks[task_group_id]
                if material_id == "m2" and attempt == 1:
                    record = dict(result.records[0])
                    record["materialName"] = "name-m1"
                    record["scriptInfo"] = {"formula": {"labels": ["错配公式"]}, "text": "错配正文"}
                    return RpaTaskResult(task_group_id, "completed", files=csv_files((record,)), records=(record,))
                if material_id == "m2" and attempt == 2:
                    record = dict(result.records[0])
                    record["scriptInfo"] = {"formula": {"labels": ["匹配公式"]}, "detail": {"labels": ["开场"]}, "data": [], "text": "共享参考脚本"}
                    return RpaTaskResult(task_group_id, "completed", files=csv_files((record,)), records=(record,))
                return result

        candidates = self.candidates + [
            {"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i, "metrics": {"综合成本": str(11 - i)}, "sourceRefs": [f"report:m{i}"]}
            for i in range(4, 7)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            gateway = WrongFirstAttemptGateway({f"m{i}": "completed" for i in range(1, 7)})
            result = acquire_scripts(live_request(6), output, RecordingReportGateway(candidates), gateway)
            pack = json.loads(result.read_text(encoding="utf-8"))
            outcomes = json.loads((output / "acquisition-results.json").read_text(encoding="utf-8"))
            material_outcome = outcomes["materials"][1]
            first, second = material_outcome["attempts"]

            self.assertEqual(gateway.submitted_material_ids.count("m2"), 2)
            self.assertEqual(material_outcome["state"], "available")
            self.assertEqual((first["identityState"], second["identityState"]), ("mismatch", "matched"))
            self.assertNotEqual(first["taskGroupId"], second["taskGroupId"])
            self.assertEqual(len(first["payloadSha256"]), 64)
            self.assertEqual(len(second["payloadSha256"]), 64)
            self.assertNotEqual(first["payloadSha256"], second["payloadSha256"])
            self.assertNotEqual(first["payloadFiles"][0]["path"], second["payloadFiles"][0]["path"])
            self.assertEqual(pack["availability"], {"requested": 6, "available": 6, "missing": 0, "failed": 0})
            self.assertEqual([item["materialId"] for item in pack["materials"]], [f"m{i}" for i in range(1, 7)])
            m2_fact = json.loads((output / pack["scripts"][1]["materialFile"]).read_text(encoding="utf-8"))
            self.assertEqual(m2_fact["selectedAttempt"], 2)
            self.assertEqual(m2_fact["formula"], {"labels": ["匹配公式"]})
            self.assertNotIn("错配公式", json.dumps(pack["scripts"][1], ensure_ascii=False))
            self.assertFalse(set(m2_fact["fieldSourceRefs"]["formula"]) & {
                first["attemptRecordPath"], first["identityAuditPath"], *[item["path"] for item in first["payloadFiles"]]
            })
            self.assertIn(first["attemptRecordPath"], pack["scripts"][1]["sourceRefs"])
            self.assertEqual(outcomes["counts"]["taskSubmissions"], 7)
            self.assertEqual(json.loads((output / "status.json").read_text(encoding="utf-8"))["state"], "ready")
            from short_video_foundation.script_cli import CliError, _verify
            from argparse import Namespace
            m2_fact["fieldSourceRefs"]["formula"] = [second["payloadFiles"][0]["path"], first["payloadFiles"][0]["path"]]
            fact_path = output / pack["scripts"][1]["materialFile"]
            fact_path.write_text(json.dumps(m2_fact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            pack["scripts"][1]["fieldSourceRefs"]["formula"] = list(m2_fact["fieldSourceRefs"]["formula"])
            pack["scripts"][1]["materialFileSha256"] = hashlib.sha256(fact_path.read_bytes()).hexdigest()
            result.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CliError, "outside its matched attempt"):
                _verify(Namespace(path=output))
            identity_path = output / first["identityAuditPath"]
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity["mismatchedFields"] = []
            identity_path.write_text(json.dumps(identity), encoding="utf-8")
            with self.assertRaisesRegex(CliError, "identity audit"):
                _verify(Namespace(path=output))
            identity["mismatchedFields"] = first["mismatchedFields"]
            identity_path.write_text(json.dumps(identity), encoding="utf-8")

    def test_unknown_submit_outcome_splits_missing_failed_and_unsubmitted(self):
        class MissingAndUnknownGateway(RecordingRpaGateway):
            def submit(self, detail, rpa_shop, params):
                material_id = params["material_id"]
                if material_id == "m4":
                    self.submitted_material_ids.append(material_id)
                    raise TimeoutError("synthetic submit timeout")
                return super().submit(detail, rpa_shop, params)

            def poll(self, task_group_id):
                material_id, _attempt = self._tasks[task_group_id]
                if material_id == "m3":
                    records = ({
                        "recordType": "material_detail", "materialId": "m3", "materialName": "name-m3",
                    },)
                    return RpaTaskResult(task_group_id, "completed", files=csv_files(records), records=records)
                return super().poll(task_group_id)

        candidates = [
            {"materialId": f"m{i}", "materialName": f"name-m{i}", "rank": i, "metrics": {"综合成本": str(11 - i)}, "sourceRefs": [f"report:m{i}"]}
            for i in range(1, 10)
        ]
        gateway = MissingAndUnknownGateway({f"m{i}": "completed" for i in range(1, 10)})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = acquire_scripts(live_request(9), output, RecordingReportGateway(candidates), gateway)
            pack = json.loads(result.read_text(encoding="utf-8"))
            outcomes = json.loads((output / "acquisition-results.json").read_text(encoding="utf-8"))

            self.assertCountEqual(gateway.submitted_material_ids, ["m1", "m2", "m3", "m4", "m5", "m6"])
            self.assertEqual(outcomes["counts"], {
                "requested": 9, "taskSubmissions": 5, "available": 4,
                "submittedWithoutScript": 1, "failed": 0, "submissionUnknown": 1, "unsubmitted": 3,
            })
            self.assertEqual(pack["availability"], {"requested": 9, "available": 4, "missing": 4, "failed": 1})
            self.assertEqual(outcomes["materials"][2]["state"], "submittedWithoutScript")
            self.assertEqual(outcomes["materials"][3]["state"], "submissionUnknown")
            self.assertTrue(all(item["state"] == "unsubmitted" for item in outcomes["materials"][6:]))
            self.assertTrue(outcomes["scheduler"]["hardStopObserved"])
            self.assertEqual(outcomes["scheduler"]["underfillReason"], "hard_stop")
            self.assertTrue(all(item["inFlight"] <= 3 for item in outcomes["scheduler"]["events"]))
            from short_video_foundation.script_cli import _verify
            from argparse import Namespace
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")


if __name__ == "__main__":
    unittest.main()
