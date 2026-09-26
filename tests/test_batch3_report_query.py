import json
from pathlib import Path
import tempfile
import unittest

from short_video_foundation.errors import ContractError
from short_video_foundation.qianchuan_script_acquisition.contracts import AcquisitionRequest
from short_video_foundation.qianchuan_script_acquisition.field_registry import FieldRegistry, load_field_registry
from short_video_foundation.qianchuan_script_acquisition.report_client import (
    DATA_TOPIC,
    DEFAULT_METRICS,
    FUNCTION_CODE,
    ReportClientError,
    RuntimeContext,
    fetch_material_report,
    report_business_params,
    resolve_advertiser_id,
)
from short_video_foundation.qianchuan_script_acquisition.selection import QueryError, select_materials, select_materials_with_audit


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "qianchuan-material-report-v1.json"


def live_request(**changes):
    payload = {
        "liveAcquire": {
            "apiShop": "shop-A",
            "advertiserId": "1770096415226951",
            "rpaShop": "rpa-C",
            "topN": 2,
            "materialFilterSort": {
                "sortField": "千次曝光成本",
                "direction": "desc",
                "filters": [],
            },
        },
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
    }
    payload["liveAcquire"]["materialFilterSort"].update(changes.pop("sort", {}))
    payload["liveAcquire"].update(changes)
    return AcquisitionRequest.from_dict(payload)


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, json=None, headers=None, cookies=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "cookies": cookies, "timeout": timeout})
        return self.response


class AuthorizationGateway:
    def __init__(self, accounts):
        self.accounts = accounts

    def connector_detail(self):
        return {"platformCode": "QC_DYNAMIC_PLATFORM"}

    def list_accounts(self, detail):
        assert detail["platformCode"] == "QC_DYNAMIC_PLATFORM"
        return self.accounts


class Batch3ReportQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_field_registry(ROOT / "config" / "asset-field-registry-v1.json")
        cls.rows = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_runtime_context_requires_all_credential_sources(self):
        with self.assertRaisesRegex(ReportClientError, "ENV_BACKEND_HOST"):
            RuntimeContext.from_environ({})
        context = RuntimeContext.from_environ({
            "ENV_BACKEND_HOST": "https://backend.example",
            "YUCE_AUTHORIZATION": "auth-secret",
            "YUCE_SESSION_ID": "agent-session",
            "YCSESSIONID": "cookie-secret",
        })
        self.assertEqual(context.api_base, "https://backend.example")
        self.assertEqual(context.agent_session, "agent-session")

    def test_advertiser_is_derived_from_rpa_account_and_checked_under_api_shop(self):
        request = live_request()
        request = AcquisitionRequest.from_dict({
            **request.to_dict(),
            "liveAcquire": {key: value for key, value in request.live_acquire.to_dict().items() if key != "advertiserId"},
        })
        account = {"shop_id": "rpa-C", "account": "1770096415226951"}
        authorization = {"shop_id": "shop-A", "advertiser_id": "1770096415226951"}
        transport = RecordingTransport({"success": True, "data": [authorization]})
        environment = {"ENV_BACKEND_HOST": "https://backend.example", "YUCE_AUTHORIZATION": "secret"}
        resolved = resolve_advertiser_id(request, AuthorizationGateway([account]), transport, environ=environment)
        self.assertEqual(resolved.live_acquire.advertiser_id, account["account"])
        self.assertEqual(request.live_acquire.advertiser_id, None)
        self.assertTrue(transport.calls[0]["url"].endswith("/shops/advertisers"))
        with self.assertRaises(ReportClientError):
            resolve_advertiser_id(live_request(advertiserId="123"), AuthorizationGateway([account]),
                                  RecordingTransport({"success": True, "data": [authorization]}), environ=environment)

        for accounts, authorized in [
            ([{**account, "account": "not-a-number"}], [authorization]),
            ([account, account], [authorization]),
            ([account], [{**authorization, "shop_id": "another-shop"}]),
            ([account], [authorization, authorization]),
        ]:
            with self.subTest(accounts=accounts, authorized=authorized):
                with self.assertRaises(ReportClientError):
                    resolve_advertiser_id(request, AuthorizationGateway(accounts),
                                          RecordingTransport({"success": True, "data": authorized}), environ=environment)

    def test_registry_resolves_chinese_label_and_decimal_filter(self):
        selected = select_materials(self.rows, live_request(sort={"filters": [{"field": "千次曝光成本", "operator": "gte", "value": "1.10"}]}), self.registry)
        self.assertEqual([item.material_id for item in selected], ["m-2", "m-1"])
        self.assertEqual(selected[0].metrics["total_ecpm_for_roi2"], "2.20")

    def test_all_requested_report_metrics_are_available_for_local_selection(self):
        registered = {entry["id"] for entry in self.registry.entries() if entry["kind"] == "metric"}
        self.assertEqual(registered, set(DEFAULT_METRICS))
        self.assertEqual(len(registered), 102)
        self.assertEqual(self.registry.require("净成交ROI")["id"], "total_prepay_and_pay_settle_roi2_1h")
        self.assertEqual(self.registry.require("千次曝光成本")["id"], "total_ecpm_for_roi2")

        rows = [
            {"materialId": "m-low", "metrics": {"stat_cost_for_roi2": {"Value": 12000}, "total_prepay_and_pay_settle_roi2_1h": {"Value": 1.1}}},
            {"materialId": "m-high", "metrics": {"stat_cost_for_roi2": {"Value": 15000}, "total_prepay_and_pay_settle_roi2_1h": {"Value": 2.3}}},
        ]
        request = live_request(topN=1, sort={"sortField": "净成交ROI", "direction": "desc", "filters": [
            {"field": "整体消耗", "operator": "gte", "value": 10000},
        ]})
        selected = select_materials(rows, request, self.registry)
        self.assertEqual([item.material_id for item in selected], ["m-high"])
        self.assertEqual(selected[0].metrics["total_prepay_and_pay_settle_roi2_1h"], "2.3")

    def test_overall_spend_and_composite_cost_have_distinct_field_ids_and_rankings(self):
        rows = [
            {"materialId": "m-overall", "metrics": {"stat_cost_for_roi2": "900", "stat_cost_for_overall_roi2": "1"}},
            {"materialId": "m-composite", "metrics": {"stat_cost_for_roi2": "1", "stat_cost_for_overall_roi2": "900"}},
        ]
        overall = select_materials(rows, live_request(topN=1, sort={"sortField": "整体消耗", "direction": "desc"}), self.registry)
        composite = select_materials(rows, live_request(topN=1, sort={"sortField": "综合成本", "direction": "desc"}), self.registry)

        self.assertEqual(self.registry.require("整体消耗")["id"], "stat_cost_for_roi2")
        self.assertEqual(self.registry.require("综合成本")["id"], "stat_cost_for_overall_roi2")
        self.assertEqual([item.material_id for item in overall], ["m-overall"])
        self.assertEqual([item.material_id for item in composite], ["m-composite"])

    def test_report_api_payload_does_not_depend_on_local_selection(self):
        first = live_request(sort={"sortField": "整体消耗", "direction": "asc", "filters": [{"field": "素材ID", "operator": "eq", "value": "m-1"}]})
        second = live_request(sort={"sortField": "综合成本", "direction": "desc", "filters": []})

        self.assertEqual(report_business_params(first), report_business_params(second))
        self.assertEqual(report_business_params(first)["business_params"]["orderBy"], [{"field": "stat_cost_for_roi2", "type": 2}])
        self.assertEqual(report_business_params(first)["business_params"]["filters"], [
            {"field": "ecp_app_id", "operator": 7, "values": ["1", "2"]},
            {"field": "roi2_material_type_v3", "operator": 7, "values": ["3"]},
        ])

    def test_fetch_api_request_is_identical_for_different_local_selections(self):
        first = live_request(topN=1, sort={"sortField": "整体消耗", "direction": "asc", "filters": []})
        second = live_request(topN=5, sort={"sortField": "综合成本", "direction": "desc", "filters": []})
        environments = {
            "ENV_BACKEND_HOST": "https://backend.example",
            "YUCE_AUTHORIZATION": "auth-secret",
            "YUCE_SESSION_ID": "agent-session",
            "YCSESSIONID": "cookie-secret",
        }
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_transport = RecordingTransport({"success": True, "data": {"records": self.rows}})
            second_transport = RecordingTransport({"success": True, "data": {"records": self.rows}})
            fetch_material_report(first, Path(first_dir), first_transport, environ=environments)
            fetch_material_report(second, Path(second_dir), second_transport, environ=environments)

            self.assertEqual(first_transport.calls[0]["json"], second_transport.calls[0]["json"])
            first_query = json.loads((Path(first_dir) / "resolved-query-spec.json").read_text(encoding="utf-8"))
            second_query = json.loads((Path(second_dir) / "resolved-query-spec.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first_query["selectionRequest"], second_query["selectionRequest"])

    def test_one_row_without_sort_value_is_excluded_with_a_reason(self):
        rows = [
            {"materialId": "m-valid", "metrics": {"stat_cost_for_roi2": "20"}},
            {"materialId": "m-missing", "metrics": {"stat_cost_for_roi2": {"Value": None, "ValueStr": "-"}}},
        ]
        selection = select_materials_with_audit(
            rows,
            live_request(topN=2, sort={"sortField": "整体消耗", "direction": "desc"}),
            self.registry,
        )

        self.assertEqual([item.material_id for item in selection.candidates], ["m-valid"])
        self.assertEqual(selection.to_dict()["excludedRows"], [{
            "rowNumber": 2,
            "materialId": "m-missing",
            "reason": "sort_value_invalid",
            "fieldId": "stat_cost_for_roi2",
        }])

    def test_zero_metric_value_is_not_replaced_by_display_placeholder(self):
        zero_row = {
            "materialId": "m-zero",
            "metrics": {
                "stat_cost_for_overall_roi2": {"Value": 0, "ValueStr": "-"},
            },
        }
        request = live_request(
            topN=1,
            sort={"sortField": "综合成本", "direction": "asc"},
        )

        selected = select_materials([zero_row], request, self.registry)

        self.assertEqual([item.material_id for item in selected], ["m-zero"])
        self.assertEqual(selected[0].metrics["stat_cost_for_overall_roi2"], "0")

    def test_none_metric_value_falls_back_to_display_value(self):
        row = {
            "materialId": "m-fallback",
            "metrics": {
                "stat_cost_for_overall_roi2": {"Value": None, "ValueStr": "12.3"},
            },
        }
        request = live_request(
            topN=1,
            sort={"sortField": "综合成本", "direction": "asc"},
        )

        selected = select_materials([row], request, self.registry)

        self.assertEqual(selected[0].metrics["stat_cost_for_overall_roi2"], "12.3")

    def test_none_metric_placeholder_remains_an_invalid_sort_value(self):
        row = {
            "materialId": "m-missing",
            "metrics": {
                "stat_cost_for_overall_roi2": {"Value": None, "ValueStr": "-"},
            },
        }
        request = live_request(
            topN=1,
            sort={"sortField": "综合成本", "direction": "asc"},
        )

        with self.assertRaisesRegex(QueryError, "all_matching_rows_have_unusable_sort_value"):
            select_materials([row], request, self.registry)

    def test_distinct_id_domains_are_forwarded_without_equality_check(self):
        request = live_request()
        selected = select_materials(self.rows, request, self.registry)
        self.assertGreater(len(selected), 0)
        self.assertEqual(request.live_acquire.rpa_shop, "rpa-C")
        self.assertNotEqual(request.live_acquire.api_shop, request.live_acquire.rpa_shop)

    def test_unknown_sort_field_fails_before_transport(self):
        request = live_request(sort={"sortField": "未注册指标"})
        with self.assertRaisesRegex(QueryError, "field registry"):
            select_materials(self.rows, request, self.registry)

    def test_ties_are_deterministic_and_material_id_breaks_desc_tie(self):
        rows = [dict(self.rows[1]), dict(self.rows[1])]
        rows[0]["materialId"] = "m-3"
        rows[0]["metrics"] = {"total_ecpm_for_roi2": "2.20"}
        selected = select_materials(rows, live_request(), self.registry)
        self.assertEqual([item.material_id for item in selected], ["m-3", "m-2"])

    def test_fetch_uses_observed_gateway_contract_and_redacts_receipt(self):
        transport = RecordingTransport({"success": True, "data": {"records": self.rows}})
        with tempfile.TemporaryDirectory() as directory:
            result = fetch_material_report(
                live_request(), Path(directory), transport,
                environ={
                    "ENV_BACKEND_HOST": "https://backend.example/",
                    "YUCE_AUTHORIZATION": "auth-secret",
                    "YUCE_SESSION_ID": "agent-session",
                    "YCSESSIONID": "cookie-secret",
                },
            )
            self.assertEqual(len(result), 3)
            request = transport.calls[0]
            self.assertEqual(request["json"]["function_code"], FUNCTION_CODE)
            self.assertEqual(request["json"]["business_params"]["dataTopic"], DATA_TOPIC)
            self.assertEqual(request["json"]["business_params"]["orderBy"], [{"field": "stat_cost_for_roi2", "type": 2}])
            receipt = (Path(directory) / "gateway-response.json").read_text(encoding="utf-8")
            self.assertNotIn("auth-secret", receipt)
            self.assertNotIn("cookie-secret", receipt)
            snapshot = json.loads((Path(directory) / "material-report-snapshot.json").read_text(encoding="utf-8"))
            self.assertTrue(snapshot["complete"])
            self.assertEqual(snapshot["recordCount"], 3)
            self.assertEqual(len(snapshot["rows"]), 3)

    def test_incomplete_report_markers_are_rejected_before_snapshot(self):
        transport = RecordingTransport({"success": True, "data": {"records": self.rows, "hasMore": True}})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ReportClientError, "paginated or truncated"):
                fetch_material_report(
                    live_request(),
                    Path(directory),
                    transport,
                    environ={
                        "ENV_BACKEND_HOST": "https://backend.example/",
                        "YUCE_AUTHORIZATION": "auth-secret",
                        "YUCE_SESSION_ID": "agent-session",
                        "YCSESSIONID": "cookie-secret",
                    },
                )
            self.assertFalse((Path(directory) / "material-report-snapshot.json").exists())

    def test_file_result_keeps_raw_csv_and_writes_structured_records(self):
        raw_csv = b'"{\"\"materialId\"\": \"\"m-file\"\"}"\n'

        class Response:
            def __init__(self, body):
                self.content = body

            def json(self):
                return json.loads(self.content.decode("utf-8"))

            def raise_for_status(self):
                return None

        class FileTransport:
            def post(self, _url, **_kwargs):
                return Response(json.dumps({
                    "success": True,
                    "data": {
                        "result_type": "files",
                        "result_content": {
                            "status": "COMPLETED",
                            "failedInstances": 0,
                            "files": [{"fileUrl": "https://files.example/material-report.csv?signature=secret"}],
                        },
                    },
                }).encode("utf-8"))

            def get(self, _url, **_kwargs):
                return Response(raw_csv)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            rows = fetch_material_report(
                live_request(), output_dir, FileTransport(),
                environ={
                    "ENV_BACKEND_HOST": "https://backend.example",
                    "YUCE_AUTHORIZATION": "auth-secret",
                    "YUCE_SESSION_ID": "agent-session",
                    "YCSESSIONID": "cookie-secret",
                },
            )
            self.assertEqual(rows, [{"materialId": "m-file"}])
            self.assertEqual((output_dir / "material-report.csv").read_bytes(), raw_csv)
            self.assertEqual(
                json.loads((output_dir / "material-report.csv.structured.json").read_text(encoding="utf-8")),
                [{"materialId": "m-file"}],
            )

    def test_fetch_validates_request_before_transport(self):
        transport = RecordingTransport({"records": []})
        request = AcquisitionRequest.from_dict({
            "verifiedRun": {"sourceRun": "/tmp/verified"},
            "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        })
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ContractError, "liveAcquire"):
                fetch_material_report(request, Path(directory), transport, environ={})
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
