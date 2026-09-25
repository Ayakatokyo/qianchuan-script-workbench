"""Read-only Qianchuan material-report client using the verified gateway contract."""

from __future__ import annotations

from dataclasses import replace
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from errors import ContractError
from qianchuan_script_acquisition_contracts import AcquisitionRequest


FUNCTION_CODE = "OCEANENGINE_UNI_PROMOTION_PLAN_DATA_REQUESTS_ZDY"
DATA_TOPIC = "OVERALL_ROI_LIVE_MATERIAL_VIDEO"
DEFAULT_DIMENSIONS = [
    "ecp_app_id", "roi2_material_type_v3", "roi2_material_video_play_info",
    "roi2_material_video_name", "roi2_material_video_type", "material_create_time_v2",
    "material_id", "anchor_id",
]
DEFAULT_METRICS = [
    "stat_cost_for_overall_roi2", "total_prepay_and_pay_settle_overall_roi2_1h",
    "total_cost_per_pay_order_settle_for_overall_roi2_1h", "total_order_settle_amount_for_roi2_1h",
    "stat_cost_for_roi2", "total_prepay_and_pay_settle_roi2_1h",
    "total_cost_per_pay_order_settle_for_roi2_1h", "total_order_settle_count_for_roi2_1h",
    "no_refund_ecom_coupon_amount_for_roi2", "total_order_settle_amount_rate_for_roi2_1h",
    "total_refund_order_count_for_roi2_1h", "total_refund_order_gmv_for_roi2_1h_rate",
    "total_refund_order_gmv_for_roi2_1h_all", "total_order_real_settle_amount_for_roi2_1h",
    "no_refund_ecom_platform_subsidy_amount_for_roi2", "total_order_settle_count_rate_for_roi2_1h",
    "total_pay_order_count_for_roi2", "total_pay_order_gmv_rate_for_roi2",
    "total_pay_order_gmv_include_coupon_for_roi2", "cost_rate_for_roi2",
    "total_prepay_and_pay_order_roi2", "total_pay_order_gmv_for_roi2",
    "total_ecom_platform_subsidy_amount_for_roi2", "basic_stat_cost_for_roi2_v2",
    "total_cost_per_pay_order_for_roi2", "total_pay_order_coupon_amount_for_roi2",
    "total_prepay_order_count_for_roi2", "total_prepay_order_gmv_for_roi2",
    "total_unfinished_estimate_order_gmv_for_roi2", "total_prepay_and_pay_settle_roi2_7d",
    "total_order_settle_amount_for_roi2_7d", "total_order_settle_count_for_roi2_7d",
    "total_cost_per_pay_order_settle_for_roi2_7d", "total_order_settle_amount_rate_for_roi2_7d",
    "total_order_settle_count_rate_for_roi2_7d", "total_prepay_and_pay_settle_roi2_14d",
    "total_order_settle_amount_for_roi2_14d", "total_order_settle_count_for_roi2_14d",
    "total_cost_per_pay_order_settle_for_roi2_14d", "total_order_settle_amount_rate_for_roi2_14d",
    "total_order_settle_count_rate_for_roi2_14d", "total_prepay_and_pay_settle_roi2_30d",
    "total_order_settle_amount_for_roi2_30d", "total_order_settle_count_for_roi2_30d",
    "total_cost_per_pay_order_settle_for_roi2_30d", "total_order_settle_amount_rate_for_roi2_30d",
    "total_order_settle_count_rate_for_roi2_30d", "total_prepay_and_pay_settle_roi2_90d",
    "total_order_settle_amount_for_roi2_90d", "total_order_settle_count_for_roi2_90d",
    "total_cost_per_pay_order_settle_for_roi2_90d", "total_order_settle_amount_rate_for_roi2_90d",
    "total_order_settle_count_rate_for_roi2_90d", "additional_delivery_stat_cost_for_roi2_assist",
    "additional_delivery_total_pay_order_count_for_roi2_assist",
    "additional_delivery_total_pay_order_gmv_include_coupon_for_roi2_assist",
    "additional_delivery_total_prepay_and_pay_order_roi2_assist",
    "additional_delivery_show_cnt_for_roi2_assist", "additional_delivery_ctr_for_roi2_assist",
    "additional_delivery_click_cnt_for_roi2_assist", "additional_delivery_convert_rate_for_roi2_assist",
    "additional_delivery_total_pay_order_gmv_for_roi2_assist",
    "additional_delivery_total_pay_order_coupon_amount_for_roi2_assist",
    "additional_delivery_total_ecom_platform_subsidy_amount_for_roi2_assist",
    "additional_delivery_total_unfinished_estimate_order_gmv_for_roi2_assist",
    "additional_delivery_pay_convert_cost_for_roi2_assist_v2",
    "additional_delivery_pay_convert_cnt_for_roi2_assist_v2",
    "additional_delivery_total_order_settle_amount_for_roi2_1h_assist",
    "additional_delivery_total_prepay_and_pay_settle_roi2_1h_assist",
    "additional_delivery_total_order_settle_count_for_roi2_1h_assist",
    "additional_delivery_convert_rate_for_roi2_1h_assist",
    "additional_delivery_total_cost_per_pay_order_settle_for_roi2_1h_assist",
    "additional_delivery_total_order_real_settle_amount_for_roi2_1h_assist",
    "additional_delivery_no_refund_ecom_coupon_amount_for_roi2_assist",
    "additional_delivery_no_refund_ecom_platform_subsidy_amount_for_roi2_assist",
    "additional_delivery_total_order_settle_amount_rate_for_roi2_1h_assist",
    "additional_delivery_total_order_settle_count_rate_for_roi2_1h_assist",
    "additional_delivery_total_refund_order_count_for_roi2_1h_assist",
    "additional_delivery_total_refund_order_gmv_for_roi2_1h_all_assist",
    "additional_delivery_total_refund_order_gmv_for_roi2_1h_rate_assist",
    "additional_delivery_total_prepay_and_pay_settle_roi2_7d_assist",
    "additional_delivery_total_order_settle_amount_for_roi2_7d_assist",
    "additional_delivery_total_order_settle_count_for_roi2_7d_assist",
    "additional_delivery_total_cost_per_pay_order_settle_for_roi2_7d_assist",
    "additional_delivery_total_order_settle_amount_rate_for_roi2_7d_assist",
    "additional_delivery_total_order_settle_count_rate_for_roi2_7d_assist",
    "live_show_count_for_roi2_v2", "live_cvr_rate_for_roi2_v2", "live_watch_count_for_roi2_v2",
    "live_convert_rate_for_roi2_v2", "total_cpc_for_roi2", "total_ecpm_for_roi2",
    "video_avg_watch_duration_for_roi2", "video_comment_count_for_roi2_v2",
    "video_follow_count_for_roi2", "video_like_count_for_roi2", "video_play_count_for_roi2_v2",
    "video_play_duration_2s_rate_for_roi2", "video_play_duration_3s_rate_for_roi2",
    "video_play_duration_5s_rate_for_roi2", "video_play_duration_10s_rate_for_roi2",
    "video_play_finish_rate_for_roi2_v2",
]
_SENSITIVE_KEY = re.compile(r"(?:authorization|cookie|session|secret|token)", re.I)
DEFAULT_ORDER_BY = [{"field": "stat_cost_for_roi2", "type": 2}]


from http_transport import ReportClientError, UrlLibResponse, UrllibTransport, RuntimeContext, build_runtime_transport


def resolve_advertiser_id(request: AcquisitionRequest, rpa_gateway: Any, transport: Any, *, environ: Mapping[str, str] | None = None) -> AcquisitionRequest:
    """Bind the selected RPA account to exactly one advertiser under the API shop."""
    live = request.live_acquire
    if live is None:
        raise ContractError("resolve_advertiser_id requires liveAcquire")
    try:
        detail = rpa_gateway.connector_detail()
        accounts = rpa_gateway.list_accounts(detail)
    except Exception as exc:
        raise ReportClientError("RPA authorization query failed") from exc
    if not isinstance(accounts, list):
        raise ReportClientError("RPA authorization response has no account list")
    matches = [account for account in accounts if isinstance(account, Mapping)
               and str(account.get("shop_id") or account.get("shopId") or account.get("accountId") or account.get("id") or "").strip() == live.rpa_shop]
    if len(matches) != 1:
        raise ReportClientError("selected RPA authorization does not resolve to one account")
    advertiser_id = str(matches[0].get("account") or "").strip()
    if not (advertiser_id.isascii() and advertiser_id.isdecimal()):
        raise ReportClientError("selected RPA account is not a numeric advertiser ID")
    if live.advertiser_id is not None and live.advertiser_id != advertiser_id:
        raise ReportClientError("supplied advertiser ID does not match the selected RPA account")
    context = RuntimeContext.from_environ(os.environ if environ is None else environ)
    try:
        response = transport.post(
            context.api_base + "/adg/v1/agent/api-platform/shops/advertisers",
            json={"authorization": context.authorization, "platform": "OCEANENGINE"},
            headers={"Content-Type": "application/json"},
            cookies={"YCSESSIONID": context.cookie_session},
            timeout=30,
        )
        body = _response_payload(response)
    except Exception as exc:
        raise ReportClientError("API advertiser authorization query failed") from exc
    if not isinstance(body, Mapping) or body.get("success") is not True or not isinstance(body.get("data"), list):
        raise ReportClientError("API advertiser authorization response is invalid")
    authorized = [row for row in body["data"] if isinstance(row, Mapping)
                  and str(row.get("shop_id") or "").strip() == live.api_shop
                  and str(row.get("advertiser_id") or "").strip() == advertiser_id]
    if len(authorized) != 1:
        raise ReportClientError("selected RPA account is not uniquely authorized under the API shop")
    return replace(request, live_acquire=replace(live, advertiser_id=advertiser_id))


def _redact(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                result[key_text] = "[redacted]"
            elif key_text in {"fileUrl", "file_url", "downloadUrl", "download_url"} and isinstance(item, str):
                parsed = urlsplit(item)
                result[key_text] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            else:
                result[key_text] = _redact(item)
        return result
    return value


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _response_payload(response: Any) -> Mapping[str, Any] | list[dict[str, Any]]:
    if isinstance(response, (Mapping, list)):
        return response
    try:
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise ReportClientError("material report gateway returned invalid JSON") from exc


def _business_params(advertiser_id: str, start_date: str, end_date: str, _sort: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not str(advertiser_id).isdigit():
        raise ReportClientError("advertiser ID is invalid")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(start_date)) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(end_date)):
        raise ReportClientError("report dates must use YYYY-MM-DD")
    return {
        "advertiserId": int(advertiser_id),
        "startTime": str(start_date) + " 00:00:00",
        "endTime": str(end_date) + " 23:59:59",
        "dataTopic": DATA_TOPIC,
        "dimensions": list(DEFAULT_DIMENSIONS),
        "metrics": list(DEFAULT_METRICS),
        "filters": [{"field": "ecp_app_id", "operator": 7, "values": ["1", "2"]}, {"field": "roi2_material_type_v3", "operator": 7, "values": ["3"]}],
        # This fixed platform order preserves the observed report gateway contract.
        # User selection always runs locally after the full report snapshot is saved.
        "orderBy": [dict(DEFAULT_ORDER_BY[0])],
    }


def report_business_params(request: AcquisitionRequest) -> dict[str, Any]:
    if request.live_acquire is None:
        raise ContractError("report_business_params requires liveAcquire")
    live = request.live_acquire
    return {
        "shop_id": live.api_shop,
        "business_params": _business_params(live.advertiser_id, request.period["startDate"], request.period["endDate"]),
    }


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def report_query_fingerprint(request: AcquisitionRequest) -> str:
    return _canonical_sha256(report_business_params(request))


def acquisition_scope_fingerprint(request: AcquisitionRequest) -> str:
    if request.live_acquire is None:
        raise ContractError("acquisition_scope_fingerprint requires liveAcquire")
    return _canonical_sha256({
        "period": request.period,
        "apiShop": request.live_acquire.api_shop,
        "advertiserId": request.live_acquire.advertiser_id,
        "rpaShop": request.live_acquire.rpa_shop,
        "reportQueryFingerprint": report_query_fingerprint(request),
    })


def write_material_report_snapshot(rows: list[dict[str, Any]], request: AcquisitionRequest, output_dir: Path) -> tuple[Path, str]:
    if request.live_acquire is None:
        raise ContractError("write_material_report_snapshot requires liveAcquire")
    rows = _validate_records(rows)
    payload = {
        "schemaVersion": 1,
        "complete": True,
        "recordCount": len(rows),
        "rowsSha256": _canonical_sha256(rows),
        "queryFingerprint": report_query_fingerprint(request),
        "scopeFingerprint": acquisition_scope_fingerprint(request),
        "rows": rows,
    }
    path = Path(output_dir) / "material-report-snapshot.json"
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if current != payload:
            raise ReportClientError("material report snapshot already exists with different content")
    else:
        _atomic_json(path, payload)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load_material_report_snapshot(path: Path, request: AcquisitionRequest) -> tuple[list[dict[str, Any]], str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportClientError("material report snapshot is unreadable") from exc
    if not isinstance(payload, Mapping) or payload.get("schemaVersion") != 1 or payload.get("complete") is not True:
        raise ReportClientError("material report snapshot is not marked complete")
    rows = _validate_records(payload.get("rows"))
    if payload.get("recordCount") != len(rows) or payload.get("rowsSha256") != _canonical_sha256(rows):
        raise ReportClientError("material report snapshot integrity check failed")
    if payload.get("queryFingerprint") != report_query_fingerprint(request):
        raise ReportClientError("material report snapshot does not match the report query")
    if payload.get("scopeFingerprint") != acquisition_scope_fingerprint(request):
        raise ReportClientError("material report snapshot does not match the acquisition scope")
    resolved_path = Path(path)
    return rows, hashlib.sha256(resolved_path.read_bytes()).hexdigest()


def _validate_records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ReportClientError("material report payload must be a record list")
    return [dict(record) for record in records]


def _records_from_file_result(content: Any, transport: Any, context: RuntimeContext, output_dir: Path) -> list[dict[str, Any]]:
    if not isinstance(content, Mapping) or content.get("status") != "COMPLETED" or content.get("failedInstances", 0) != 0:
        raise ReportClientError("material report files task did not complete")
    files = content.get("files")
    if not isinstance(files, list) or not files or not isinstance(files[0], Mapping):
        raise ReportClientError("material report files response has no result file")
    file_url = files[0].get("fileUrl") or files[0].get("file_url")
    if not isinstance(file_url, str) or not file_url.strip():
        raise ReportClientError("material report result file URL is missing")
    filename = Path(urlsplit(file_url).path).name or "material-report.csv"
    if filename in {".", ".."} or Path(filename).name != filename or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename):
        raise ReportClientError("material report result filename is unsafe")
    response = transport.get(file_url, cookies={"YCSESSIONID": context.cookie_session}, timeout=3600)
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    raw = response.content if hasattr(response, "content") else b"".join(response.iter_content(chunk_size=1024 * 1024))
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw:
        raise ReportClientError("material report result file is empty")
    records = []
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
        for row_number, row in enumerate(reader, start=1):
            if len(row) != 1:
                raise ReportClientError(f"material report result file row {row_number} is not single-column JSON")
            record = json.loads(row[0])
            if not isinstance(record, dict):
                raise ReportClientError(f"material report result file row {row_number} is not an object")
            records.append(record)
    except (UnicodeError, csv.Error, json.JSONDecodeError) as exc:
        raise ReportClientError("material report result file could not be structured") from exc
    raw_path = Path(output_dir) / filename
    _atomic_bytes(raw_path, raw)
    _atomic_json(raw_path.with_suffix(raw_path.suffix + ".structured.json"), records)
    return _validate_records(records)


def _records_from_result(payload: Mapping[str, Any] | list[dict[str, Any]], *, transport: Any = None, context: RuntimeContext | None = None, output_dir: Path | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _validate_records(payload)
    if payload.get("success") is False:
        raise ReportClientError("material report gateway returned failure")
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("records", "rows", "result"):
            if isinstance(data.get(key), list):
                return _validate_records(data[key])
        result_type = data.get("result_type")
        content = data.get("result_content")
        if result_type == "files":
            if transport is None or context is None or output_dir is None:
                raise ReportClientError("material report file result requires a configured transport")
            return _records_from_file_result(content, transport, context, output_dir)
        if result_type == "payload" and isinstance(content, Mapping):
            content = content.get("payload")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ReportClientError("material report payload is not valid JSON") from exc
        if isinstance(content, Mapping) and isinstance(content.get("payload"), list):
            content = content["payload"]
        if isinstance(content, list):
            return _validate_records(content)
    for key in ("records", "rows"):
        if isinstance(payload.get(key), list):
            return _validate_records(payload[key])
    raise ReportClientError("material report gateway returned no material records")


def _validate_report_completeness(payload: Any, record_count: int) -> None:
    """Reject explicit paging/truncation signals before ranking any records."""
    if not isinstance(payload, Mapping):
        return
    for key in ("data", "result", "result_content", "payload"):
        value = payload.get(key)
        if not isinstance(value, Mapping):
            continue
        if value.get("isComplete") is False or value.get("complete") is False:
            raise ReportClientError("material report result is explicitly incomplete")
        if any(value.get(flag) is True for flag in ("hasMore", "has_more", "hasNextPage", "has_next_page", "isTruncated", "truncated")):
            raise ReportClientError("material report result is paginated or truncated")
        for count_key in ("totalCount", "total_count", "totalRecords", "total_records", "expectedRecordCount"):
            expected = value.get(count_key)
            if isinstance(expected, int) and not isinstance(expected, bool) and expected != record_count:
                raise ReportClientError("material report record count does not match the declared total")
        _validate_report_completeness(value, record_count)


def fetch_material_report(request: AcquisitionRequest, output_dir: Path, transport: Any, *, environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    if request.live_acquire is None:
        raise ContractError("fetch_material_report requires liveAcquire")
    context = RuntimeContext.from_environ(os.environ if environ is None else environ)
    live = request.live_acquire
    business_params = _business_params(live.advertiser_id, request.period["startDate"], request.period["endDate"])
    payload = {
        "authorization": context.authorization,
        "agent_session_id": context.agent_session,
        "data_source_type": "api",
        "platform": "OCEANENGINE",
        "function_code": FUNCTION_CODE,
        "response_content_type": "fetch",
        "business_params": business_params,
        "shop_id": live.api_shop,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "resolved-query-spec.json", _redact({
        "reportQuery": {"business_params": business_params, "shop_id": live.api_shop},
        "selectionRequest": live.material_filter_sort,
        "topN": live.top_n,
    }))
    try:
        response = transport.post(context.api_base + "/adg/v1/agent/invoke", json=payload, headers={"Content-Type": "application/json"}, cookies={"YCSESSIONID": context.cookie_session}, timeout=3600)
        result = _response_payload(response)
        rows = _records_from_result(result, transport=transport, context=context, output_dir=output_dir)
        _validate_report_completeness(result, len(rows))
    except ReportClientError:
        _atomic_json(output_dir / "status.json", {"state": "failed", "errorCode": "report_failed"})
        raise
    except Exception as exc:
        _atomic_json(output_dir / "status.json", {"state": "failed", "errorCode": "transport_failed"})
        raise ReportClientError("material report request failed") from exc
    _atomic_json(output_dir / "gateway-response.json", _redact(result))
    _atomic_json(output_dir / "field-manifest.json", {"dataTopic": DATA_TOPIC, "dimensions": DEFAULT_DIMENSIONS, "metrics": DEFAULT_METRICS, "filters": business_params["filters"], "orderBy": business_params["orderBy"], "recordCount": len(rows)})
    write_material_report_snapshot(rows, request, output_dir)
    _atomic_json(output_dir / "status.json", {"state": "completed", "recordCount": len(rows)})
    return rows


__all__ = ["DATA_TOPIC", "DEFAULT_DIMENSIONS", "DEFAULT_METRICS", "DEFAULT_ORDER_BY", "FUNCTION_CODE", "ReportClientError", "RuntimeContext", "UrllibTransport", "acquisition_scope_fingerprint", "build_runtime_transport", "fetch_material_report", "load_material_report_snapshot", "report_business_params", "report_query_fingerprint", "write_material_report_snapshot"]
