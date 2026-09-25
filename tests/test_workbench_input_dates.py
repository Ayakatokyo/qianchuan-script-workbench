"""Acquisition inputs must retain user scope and enforce the live date boundary."""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from date_policy import validate_period
from errors import ContractError
from qianchuan_script_acquisition_contracts import AcquisitionRequest, LiveAcquire
from qianchuan_script_acquisition_pipeline import acquire_scripts
from qianchuan_script_acquisition_report_client import fetch_material_report, resolve_advertiser_id
from script_cli import _normalize_acquisition_payload


class RecordingRemote:
    def __init__(self):
        self.calls = []

    def connector_detail(self):
        self.calls.append("detail")
        return {"platformCode": "RPA_JULIANG_QC"}

    def list_accounts(self, detail):
        self.calls.append("accounts")
        return [{"shop_id": "chosen-rpa", "account": "1234567"}]

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/shops/advertisers"):
            return {"success": True, "data": [{"shop_id": "chosen-api", "advertiser_id": "1234567"}]}
        return {"records": []}


class WorkbenchInputDatesTests(unittest.TestCase):
    def test_beijing_boundary_accepts_t_minus_two_without_changing_dates(self):
        class BoundaryClock:
            @classmethod
            def now(cls, tz=None):
                # UTC is still Sep 24, but acquisition's local day is Sep 25.
                utc_now = datetime(2026, 9, 24, 16, 1, tzinfo=timezone.utc)
                return utc_now.astimezone(tz) if tz is not None else utc_now

        with patch("date_policy.datetime", BoundaryClock):
            self.assertEqual(validate_period("2026-09-22", "2026-09-23"),
                             {"startDate": "2026-09-22", "endDate": "2026-09-23"})
            with self.assertRaisesRegex(ContractError, "2026-09-23"):
                validate_period("2026-09-24", "2026-09-24")

    def test_noncanonical_or_reversed_periods_are_rejected(self):
        for start, end in [("20260901", "20260903"), ("2026-W36-1", "2026-09-03"),
                           ("2026-02-30", "2026-03-02"), ("2026-09-03", "2026-09-01"),
                           (None, "2026-09-01"), ("2026-09-01", True)]:
            with self.subTest(start=start, end=end), self.assertRaises(ContractError):
                validate_period(start, end, today=date(2026, 9, 25))

    def test_standalone_date_check_returns_failure_without_normalized_input(self):
        script = Path(__file__).parents[1] / "scripts" / "date_policy.py"
        result = subprocess.run([sys.executable, str(script), "--start-date", "9999-12-31",
                                 "--end-date", "9999-12-31"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Asia/Shanghai", result.stderr)

    def test_live_intake_rejects_yesterday_today_and_future(self):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        for days in (-1, 0, 1):
            day = (today + timedelta(days=days)).isoformat()
            with self.subTest(day=day), self.assertRaisesRegex(ContractError, "Asia/Shanghai"):
                AcquisitionRequest.from_dict({
                    "period": {"startDate": day, "endDate": day},
                    "liveAcquire": {"apiShop": "chosen-api", "rpaShop": "chosen-rpa"},
                })

    def test_direct_report_rejects_illegal_date_before_remote_or_artifacts(self):
        request = AcquisitionRequest(period={"startDate": "9999-12-31", "endDate": "9999-12-31"},
                                     live_acquire=LiveAcquire("chosen-api", "chosen-rpa", "1234567"))
        remote = RecordingRemote()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "report"
            with self.assertRaisesRegex(ContractError, "Asia/Shanghai"):
                fetch_material_report(request, output_dir, remote, environ={
                    "ENV_BACKEND_HOST": "https://example.invalid", "YUCE_AUTHORIZATION": "test-secret",
                })
            self.assertFalse(output_dir.exists())
        self.assertEqual(remote.calls, [])

    def test_direct_authorization_rejects_illegal_date_before_remote(self):
        request = AcquisitionRequest(period={"startDate": "9999-12-31", "endDate": "9999-12-31"},
                                     live_acquire=LiveAcquire("chosen-api", "chosen-rpa"))
        remote = RecordingRemote()
        with self.assertRaisesRegex(ContractError, "Asia/Shanghai"):
            resolve_advertiser_id(request, remote, remote, environ={
                "ENV_BACKEND_HOST": "https://example.invalid", "YUCE_AUTHORIZATION": "test-secret",
            })
        self.assertEqual(remote.calls, [])

    def test_direct_acquisition_rejects_illegal_date_before_injected_report_gateway(self):
        request = AcquisitionRequest(period={"startDate": "9999-12-31", "endDate": "9999-12-31"},
                                     live_acquire=LiveAcquire("chosen-api", "chosen-rpa", "1234567"))
        calls = []
        def report_gateway(request):
            calls.append(request.period)
            return []
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "run"
            with self.assertRaisesRegex(ContractError, "Asia/Shanghai"):
                acquire_scripts(request, output_dir, report_gateway, RecordingRemote())
            self.assertFalse(output_dir.exists())
        self.assertEqual(calls, [])

    def test_offline_verified_run_does_not_apply_live_availability_date(self):
        request = AcquisitionRequest.from_dict({
            "period": {"startDate": "9999-12-31", "endDate": "9999-12-31"},
            "verifiedRun": {"sourceRun": "/local/verified-run"},
        })
        self.assertEqual(request.period["endDate"], "9999-12-31")

    def test_actual_form_values_preserve_both_account_domains_and_selection(self):
        normalized = _normalize_acquisition_payload({
            "api_shop": {"extra": {"shop_id": "chosen-api"}},
            "rpa_shop": {"extra": {"shop_id": "chosen-rpa"}, "account": "not-trusted"},
            "date_range": {"startDate": "2026-01-02", "endDate": "2026-01-04"},
            "top_n": 7,
            "material_filter_sort": {"sortField": "整体消耗", "direction": "asc", "filters": []},
        })
        request = AcquisitionRequest.from_dict(normalized)
        self.assertEqual(request.period, {"startDate": "2026-01-02", "endDate": "2026-01-04"})
        self.assertEqual(request.live_acquire.to_dict(), {
            "apiShop": "chosen-api", "rpaShop": "chosen-rpa", "topN": 7, "timeoutSec": 600,
            "materialFilterSort": {"sortField": "整体消耗", "direction": "asc", "filters": []},
        })
        remote = RecordingRemote()
        environment = {"ENV_BACKEND_HOST": "https://example.invalid", "YUCE_AUTHORIZATION": "test-secret"}
        resolved = resolve_advertiser_id(request, remote, remote, environ=environment)
        with tempfile.TemporaryDirectory() as directory:
            fetch_material_report(resolved, Path(directory), remote, environ=environment)
            snapshot = json.loads((Path(directory) / "resolved-query-spec.json").read_text())
        payload = remote.calls[-1][1]["json"]
        self.assertEqual(payload["shop_id"], "chosen-api")
        self.assertEqual(payload["business_params"]["advertiserId"], 1234567)
        self.assertEqual(payload["business_params"]["startTime"], "2026-01-02 00:00:00")
        self.assertEqual(payload["business_params"]["endTime"], "2026-01-04 23:59:59")
        self.assertEqual(snapshot["topN"], 7)
        self.assertEqual(snapshot["selectionRequest"], {"sortField": "整体消耗", "direction": "asc", "filters": []})

    def test_public_boolean_is_not_accepted_as_a_material_count(self):
        for value in (True, False, 0, -1, "7", 1.5):
            with self.subTest(value=value), self.assertRaises(ContractError):
                AcquisitionRequest.from_dict(_normalize_acquisition_payload({
                    "api_shop": "chosen-api", "rpa_shop": "chosen-rpa", "top_n": value,
                    "date_range": {"startDate": "2026-01-02", "endDate": "2026-01-04"},
                }))


if __name__ == "__main__":
    unittest.main()
