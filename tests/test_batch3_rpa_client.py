from pathlib import Path
import tempfile
import unittest

from short_video_foundation.qianchuan_script_acquisition.rpa_client import (
    RpaAuthorizationError,
    RpaTaskError,
    RpaTaskResult,
    RpaGateway,
    invoke_once,
    validate_business_params,
)
from qianchuan_script_acquisition_gate import FirstBatchCsvGate

VALID_PARAMS = {"material_id": "m1", "date_type": "CUSTOM", "custom_start_date": "2026-09-01", "custom_end_date": "2026-09-07"}


class FakeGateway:
    def __init__(self, accounts=None, statuses=None):
        self.accounts = accounts or []
        self.statuses = list(statuses or [])
        self.submissions = []
        self.poll_calls = []

    def connector_detail(self):
        return {
            "connectorCode": "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis",
            "platformCode": "RPA_DOUDIAN",
            "inParamJsonSchemaText": '{"type":"object","required":["material_id","date_type"],"properties":{"material_id":{"type":"string"},"date_type":{"type":"string"}}}',
        }

    def list_accounts(self, detail):
        return self.accounts

    def authorize(self, rpa_shop):
        ids = {str(item.get("shopId") or item.get("accountId")) for item in self.accounts}
        if str(rpa_shop) not in ids:
            raise RpaAuthorizationError("rpaShop is not authorized")

    def submit(self, detail, rpa_shop, params):
        self.authorize(rpa_shop)
        self.submissions.append(params["material_id"])
        return "task-1"

    def poll(self, task_group_id):
        self.poll_calls.append(task_group_id)
        status = self.statuses.pop(0) if self.statuses else "completed"
        if status == "failed":
            raise RpaTaskError("failed terminal RPA status")
        return RpaTaskResult(task_group_id, status, ({"fileUrl": "https://example.invalid/result.csv"},))


class Batch3RpaClientTests(unittest.TestCase):
    def gate(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return FirstBatchCsvGate(Path(directory.name), ["m1"])

    def test_rpa_shop_must_be_in_current_authorizations(self):
        gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}])
        with self.assertRaisesRegex(RpaAuthorizationError, "rpaShop"):
            gateway.authorize("rpa-denied")

    def test_schema_text_and_list_parameter_contracts(self):
        detail = {"inParamJsonSchemaText": '{"type":"object","required":["material_id"],"properties":{"material_id":{"type":"string"}}}'}
        self.assertEqual(validate_business_params(detail, {"material_id": "m1"})["material_id"], "m1")
        with self.assertRaisesRegex(ValueError, "Schema"):
            validate_business_params(detail, {"material_id": 1})
        list_detail = {"inParamList": [{"param": "material_id", "isRequired": True, "dataTypeEnum": "STRING"}]}
        validate_business_params(list_detail, {"material_id": "m1"})
        with self.assertRaisesRegex(ValueError, "required"):
            validate_business_params(list_detail, {})

    def test_invoke_once_submits_once_and_polling_keeps_existing_task(self):
        gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}], statuses=["pending", "running", "partial_success"])
        result = invoke_once(
            gateway,
            gateway.connector_detail(),
            "rpa-allowed",
            dict(VALID_PARAMS),
            clock=lambda: 0,
            sleep=lambda _seconds: None,
            timeout_sec=10,
            execution_gate=self.gate(),
        )
        self.assertEqual(result.status, "partial_success")
        self.assertEqual(gateway.submissions, ["m1"])
        self.assertEqual(gateway.poll_calls, ["task-1", "task-1", "task-1"])

    def test_failed_terminal_status_is_not_retried(self):
        gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}], statuses=["failed"])
        with self.assertRaises(RpaTaskError):
            invoke_once(gateway, gateway.connector_detail(), "rpa-allowed", dict(VALID_PARAMS), clock=lambda: 0, sleep=lambda _seconds: None, timeout_sec=10, execution_gate=self.gate())
        self.assertEqual(gateway.submissions, ["m1"])

    def test_direct_invocation_requires_gate_and_cannot_repeat_first_attempt(self):
        gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}])
        args = (gateway, gateway.connector_detail(), "rpa-allowed", dict(VALID_PARAMS))
        with self.assertRaisesRegex(ValueError, "首批 CSV 门禁"):
            invoke_once(*args)
        self.assertEqual(gateway.submissions, [])
        gate = self.gate()
        invoke_once(*args, execution_gate=gate)
        with self.assertRaisesRegex(RuntimeError, "already started"):
            invoke_once(*args, execution_gate=gate)
        self.assertEqual(gateway.submissions, ["m1"])

    def test_legacy_gateway_helper_also_requires_gate(self):
        from rpa_gateway import invoke_once as legacy_invoke_once
        gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}])
        with self.assertRaisesRegex(ValueError, "首批 CSV 门禁"):
            legacy_invoke_once(gateway, gateway.connector_detail(), "rpa-allowed", {"material_id": "m1", "date_type": "CUSTOM"})
        self.assertEqual(gateway.submissions, [])

    def test_low_level_submission_requires_complete_valid_custom_dates(self):
        for params in (
            {"material_id": "m1", "date_type": "CUSTOM"},
            {**VALID_PARAMS, "custom_end_date": "9999-12-31"},
            {**VALID_PARAMS, "date_type": "YESTERDAY"},
        ):
            with self.subTest(params=params):
                gateway = FakeGateway(accounts=[{"shopId": "rpa-allowed"}])
                with self.assertRaises(ValueError):
                    invoke_once(gateway, gateway.connector_detail(), "rpa-allowed", params, execution_gate=self.gate())
                self.assertEqual(gateway.submissions, [])

    def test_rpa_gateway_download_rejects_unsafe_filename_and_oversized_file(self):
        gateway = RpaGateway()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "filename"):
                gateway.download_csv({"fileName": "../secret.csv", "content": b"x"}, Path(directory) / "out.csv")
            with self.assertRaisesRegex(ValueError, "size"):
                gateway.download_csv({"fileName": "ok.csv", "content": b"12345"}, Path(directory) / "out.csv", max_bytes=4)


if __name__ == "__main__":
    unittest.main()
