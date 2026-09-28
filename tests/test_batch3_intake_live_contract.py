import json
from pathlib import Path
import re
import tempfile
import unittest

from short_video_foundation.qianchuan_script_acquisition.contracts import AcquisitionRequest
from short_video_foundation.qianchuan_script_acquisition.pipeline import acquire_scripts
from short_video_foundation.qianchuan_script_acquisition.report_client import fetch_material_report
from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaGateway, RpaTaskResult
from short_video_foundation.qianchuan_script_acquisition.selection import select_materials
from short_video_foundation.qianchuan_script_acquisition.field_registry import load_field_registry
from short_video_foundation.script_cli import _normalize_acquisition_payload, build_parser, validate_identity


ROOT = Path(__file__).parents[1]
SKILL_NAMES = ('qianchuan-script-workbench',)
PUBLIC_FIELDS = [
    "api_shop",
    "rpa_shop",
    "date_range",
    "top_n",
    "material_filter_sort",
]
FORBIDDEN_PUBLIC_FIELDS = {
    "source_mode",
    "source_run",
    "output_root",
    "analysis_id",
    "highlight_mode",
    "highlight_rules",
    "customer_facts",
    "fact_evidence",
    "business_method",
    "target_audience",
    "duration",
    "cta",
    "primary_test_variable",
    "original_text",
    "strength",
    "immutable_items",
    "delete_items",
}


def live_request() -> AcquisitionRequest:
    return AcquisitionRequest.from_dict({
        "liveAcquire": {
            "apiShop": "api-shop",
            "advertiserId": "1",
            "rpaShop": "rpa-account",
            "topN": 10,
            "materialFilterSort": {},
        },
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
    })


def report_record(material_id: str = "material-1") -> dict:
    return {
        "dimensions": {
            "material_id": {"Value": material_id, "ValueStr": material_id},
            "roi2_material_video_name": {"Value": "参考素材", "ValueStr": "参考素材"},
        },
        "metrics": {
            "stat_cost_for_overall_roi2": {"Value": 12, "ValueStr": "12"},
            "total_ecpm_for_roi2": {"Value": 8, "ValueStr": "8"},
        },
    }


class SequenceResponse:
    def __init__(self, payload):
        self.payload = payload
        self.content = b""

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1024 * 1024):
        del chunk_size
        yield self.content


class DynamicContractTransport:
    def __init__(self):
        self.calls = []
        self.statuses = [
            {"status": "pending"},
            {"status": "completed", "payload": [{"recordType": "script_analysis", "materialId": "m-1", "scriptInfo": {"text": "参考脚本"}}]},
        ]

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/adg/v1/agent/invoke"):
            return SequenceResponse({"success": True, "data": {"result_type": "payload", "result_content": {"payload": [report_record()]}}})
        if url.endswith("/dcConnector/v3/listByConnectorCode"):
            return SequenceResponse({
                "success": True,
                "data": [{
                    "connectorCode": "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis",
                    "platformCode": "QC_DYNAMIC_PLATFORM",
                    "inParamJsonSchemaText": json.dumps({
                        "type": "object",
                        "required": ["material_id", "date_type"],
                        "properties": {"material_id": {"type": "string"}, "date_type": {"type": "string"}},
                        "additionalProperties": True,
                    }),
                }],
            })
        if url.endswith("/adg/v1/agent/rpa/authorizations/query"):
            return SequenceResponse({"success": True, "data": [{"platform": "QC_DYNAMIC_PLATFORM", "accountId": "rpa-account"}]})
        if url.endswith("/adg/v1/agent/fetch/tasks"):
            return SequenceResponse({"success": True, "data": {"task_group_id": "task-1"}})
        if url.endswith("/adg/v1/agent/fetch/tasks/status"):
            return SequenceResponse({"success": True, "data": self.statuses.pop(0)})
        raise AssertionError(f"unexpected endpoint: {url}")


class FileOnlyRpaGateway:
    def __init__(self, content: bytes):
        self.content = content
        self.submits = 0

    def connector_detail(self):
        return {"inParamJsonSchemaText": json.dumps({"type": "object", "required": ["material_id"], "properties": {"material_id": {"type": "string"}}})}

    def authorize(self, _rpa_shop):
        return {"accountId": "rpa-account"}

    def submit(self, _detail, _rpa_shop, _params):
        self.submits += 1
        return "task-1"

    def poll(self, _task_group_id):
        from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaTaskResult
        return RpaTaskResult("task-1", "completed", files=({"fileName": "diagnosis.csv", "content": self.content},))

    def download_csv(self, result, target):
        from short_video_foundation.qianchuan_script_acquisition.rpa_client import RpaGateway
        return RpaGateway().download_csv(result, target)


class IntakeAndLiveContractTests(unittest.TestCase):
    def test_public_form_is_exactly_the_five_qianchuan_acquisition_fields(self):
        for name in SKILL_NAMES:
            if name == "yijiazhiyan-information-flow-script-generation":
                continue
            root = ROOT
            metadata_text = (root / "metadata.yaml").read_text(encoding="utf-8")
            blocks = re.findall(r"(?ms)^  - key: ([a-z0-9_]+)\n(.*?)(?=^  - key: |\Z)", metadata_text)
            self.assertEqual([key for key, _ in blocks], PUBLIC_FIELDS, name)
            self.assertIn("required: false", blocks[-1][1], name)
            self.assertIn("default: 10", blocks[3][1], name)
            self.assertTrue(all("required: true" in body for _, body in blocks[:4]), name)
            self.assertTrue(set(key for key, _ in blocks).isdisjoint(FORBIDDEN_PUBLIC_FIELDS))

            skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
            frontmatter = skill_text.split("---", 2)[1]
            self.assertIn("\ndescription: 适用于", frontmatter, name)
            self.assertIn("\nargument_hint: ", frontmatter, name)
            self.assertNotIn("pre_input:", frontmatter, name)
            references = [field for field in PUBLIC_FIELDS if f"__field:{field}__" in metadata_text]
            self.assertEqual(references, PUBLIC_FIELDS, name)
            for field in PUBLIC_FIELDS:
                self.assertEqual(metadata_text.count(f"__field:{field}__"), 1, name)
            self.assertFalse(any(f"__field:{field}__" in metadata_text for field in FORBIDDEN_PUBLIC_FIELDS), name)
            self.assertIn("千川广告主ID：__field:rpa_shop__", metadata_text, name)
            self.assertIn("例如筛选“整体消耗”>=10000，再按“净成交ROI”降序", metadata_text, name)
            self.assertNotIn("（RPA 授权）", metadata_text, name)
            self.assertNotIn("广告主数字 ID 会从授权项自动核验", metadata_text, name)

    def test_selected_authorization_objects_use_their_distinct_shop_ids(self):
        payload = _normalize_acquisition_payload({
            "api_shop": {"extra": {"shop_id": "api-shop"}},
            "rpa_shop": {"extra": {"shop_id": "rpa-authorization"}},
            "date_range": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        })
        self.assertEqual(payload["liveAcquire"]["apiShop"], "api-shop")
        self.assertEqual(payload["liveAcquire"]["rpaShop"], "rpa-authorization")
        self.assertNotIn("advertiserId", payload["liveAcquire"])


    def test_report_query_matches_qianchuan_gateway_contract_and_normalizes_rows(self):
        transport = DynamicContractTransport()
        with tempfile.TemporaryDirectory() as directory:
            rows = fetch_material_report(live_request(), Path(directory), transport, environ={
                "ENV_BACKEND_HOST": "https://gateway.example",
                "YUCE_AUTHORIZATION": "auth-secret",
                "YUCE_SESSION_ID": "agent-session",
            })
        request = transport.calls[0][1]
        self.assertTrue(transport.calls[0][0].endswith("/adg/v1/agent/invoke"))
        body = request["json"]
        self.assertEqual(body["shop_id"], "api-shop")
        self.assertEqual(body["business_params"]["advertiserId"], 1)
        self.assertEqual(body["business_params"]["dataTopic"], "OVERALL_ROI_LIVE_MATERIAL_VIDEO")
        self.assertGreaterEqual(len(body["business_params"]["dimensions"]), 8)
        self.assertGreaterEqual(len(body["business_params"]["metrics"]), 100)
        self.assertEqual(request["cookies"], {"YCSESSIONID": "auth-secret"})
        self.assertEqual(rows, [report_record()])

    def test_actual_report_rows_can_be_selected_by_registered_metric(self):
        registry = load_field_registry(ROOT / "config" / "asset-field-registry-v1.json")
        selected = select_materials([report_record("101"), report_record("102")], live_request(), registry)
        self.assertEqual([item.material_id for item in selected], ["102", "101"])

    def test_dynamic_rpa_uses_detail_authorization_async_tasks_and_single_submit(self):
        transport = DynamicContractTransport()
        gateway = RpaGateway(transport=transport, environ={
            "ENV_BACKEND_HOST": "https://gateway.example",
            "YUCE_AUTHORIZATION": "auth-secret",
            "YUCE_SESSION_ID": "agent-session",
        })
        detail = gateway.connector_detail()
        self.assertEqual(detail["platformCode"], "QC_DYNAMIC_PLATFORM")
        self.assertEqual(gateway.authorize("rpa-account")["accountId"], "rpa-account")
        task_id = gateway.submit(detail, "rpa-account", {"material_id": "m-1", "date_type": "CUSTOM"})
        result = gateway.poll(task_id)
        self.assertEqual(result.status, "pending")
        result = gateway.poll(task_id)
        self.assertEqual(result.status, "completed")
        endpoints = [url for url, _ in transport.calls]
        self.assertIn("https://gateway.example/dcConnector/v3/listByConnectorCode", endpoints)
        self.assertIn("https://gateway.example/adg/v1/agent/rpa/authorizations/query", endpoints)
        self.assertEqual(endpoints.count("https://gateway.example/adg/v1/agent/fetch/tasks"), 1)
        self.assertEqual(endpoints.count("https://gateway.example/adg/v1/agent/fetch/tasks/status"), 2)
        submit = next(kwargs["json"] for url, kwargs in transport.calls if url.endswith("/adg/v1/agent/fetch/tasks"))
        self.assertEqual(submit["function_code"], "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis")
        self.assertEqual(submit["data_source_type"], "rpa")
        self.assertEqual(submit["platform"], "QC_DYNAMIC_PLATFORM")
        self.assertEqual(submit["shop_id"], "rpa-account")

    def test_file_result_is_downloaded_and_parsed_before_source_pack(self):
        fixture = ('recordType\x01materialId\x01materialName\x01scriptInfo\n'
                   '\x02script_analysis\x01m-1\x01sample-name\x01{"text":"原始参考脚本"}\n').encode()
        report = [{"materialId": "m-1", "materialName": "sample-name", "rank": 1, "metrics": {"综合成本": "1", "千次曝光成本": "1"}, "sourceRefs": ["report:m-1"]}]

        class Report:
            def fetch_material_report(self, _request, _output_dir):
                return report

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = acquire_scripts(live_request(), output, Report(), FileOnlyRpaGateway(fixture))
            payload = json.loads(result.read_text(encoding="utf-8"))
            csv_path = next((output / "source-data" / "rpa").glob("*.csv"))
            records_path = csv_path.with_suffix(".records.json")
            self.assertTrue(records_path.is_file())
            records = json.loads(records_path.read_text(encoding="utf-8"))
            self.assertEqual(records[0]["scriptInfo"]["text"], "原始参考脚本")
            attempt = json.loads(next((output / "source-data" / "attempts").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual([item["kind"] for item in attempt["payloadFiles"]], ["csv", "records-json"])
            from argparse import Namespace
            from short_video_foundation.script_cli import _verify
            self.assertEqual(_verify(Namespace(path=output))["verification"], "passed")
        self.assertEqual(payload["availability"], {"requested": 1, "available": 1, "missing": 0, "failed": 0})
        self.assertEqual(payload["scripts"][0]["rawText"], "原始参考脚本")

    def test_cli_uses_default_run_root_and_generates_safe_identities(self):
        args = build_parser().parse_args(["acquire", "--input", "request.json"])
        self.assertIsNone(args.output_root)
        from short_video_foundation.script_cli import _external_root, _request_analysis_id, _request_run_id
        with tempfile.TemporaryDirectory() as directory:
            from unittest.mock import patch
            with patch("pathlib.Path.cwd", return_value=Path(directory)):
                self.assertEqual(_external_root(None), Path(directory).resolve() / "千川素材脚本数据")
        run_id = _request_run_id({})
        analysis_id = _request_analysis_id({}, None)
        self.assertEqual(validate_identity(run_id), run_id)
        self.assertEqual(validate_identity(analysis_id), analysis_id)
        self.assertNotEqual(run_id, analysis_id)

    def test_public_date_range_is_normalized_into_internal_period(self):
        normalized = _normalize_acquisition_payload({
            "api_shop": "api-shop",
            "advertiser_id": "1",
            "rpa_shop": "rpa-account",
            "date_range": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
            "top_n": 10,
            "material_filter_sort": {},
        })
        self.assertEqual(normalized["period"], {"startDate": "2026-09-01", "endDate": "2026-09-07"})
        self.assertNotIn("date_range", normalized)
        self.assertEqual(AcquisitionRequest.from_dict(normalized).period, normalized["period"])


if __name__ == "__main__":
    unittest.main()
