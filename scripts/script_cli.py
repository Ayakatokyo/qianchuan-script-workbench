"""Resumable CLI for Batch 3 Qianchuan script workflows."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Mapping

from qianchuan_script_acquisition_contracts import AcquisitionRequest
from qianchuan_script_acquisition_identity import RETURNED_ID_POLICY, audit_identity, content_evidence
from qianchuan_script_acquisition_csv_parser import RpaCsvError, parse_diagnosis_csv
from qianchuan_script_acquisition_gate import RpaPausedError, assert_detail_rpa_not_paused
from qianchuan_script_acquisition_field_registry import QueryError, load_field_registry, _value_at
from qianchuan_script_acquisition_pipeline import (
    OUTCOMES_FILENAME,
    REPORT_SNAPSHOT_PATH,
    SELECTION_FILENAME,
    SELECTION_PENDING_FILENAME,
    acquire_scripts,
    continue_acquire_scripts,
    inspect_pending_report,
    _record_payload,
)
from qianchuan_script_acquisition_report_client import (
    ReportClientError,
    RuntimeContext as ReportRuntimeContext,
    build_runtime_transport,
    fetch_material_report,
    report_business_params,
    resolve_advertiser_id,
)
from qianchuan_script_acquisition_rpa_client import RpaGateway
from qianchuan_script_acquisition_verified_run import import_verified_run
from qianchuan_script_acquisition_receipt import atomic_json
from script_creation_contracts import validate_payload
from script_creation_session import prepare_generation, prepare_rewrite, publish_generation, publish_rewrite
from workbench_analysis import prepare_analysis, publish_analysis, verify_analysis
from workbench_reporting import WorkbenchError, render_summary, verify_handoff


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SKILL_ROOT = Path(__file__).resolve().parents[1]

_ALL_COMMANDS = {"describe-acquire", "preview-acquire", "acquire", "continue-acquire", "import-run", "render-summary", "prepare-analysis", "publish-analysis", "prepare-generation", "publish-generation", "prepare-rewrite", "publish-rewrite", "verify"}
_ALLOWED_COMMANDS = set(globals().get("_ALLOWED_COMMANDS", _ALL_COMMANDS))


class CliError(ValueError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class RuntimeContext:
    """Resolve live connector configuration without exposing secret values."""

    environ: dict[str, str]

    @classmethod
    def from_environment(cls) -> "RuntimeContext":
        return cls(dict(os.environ))

    def require_live_connector(self) -> Any:
        try:
            ReportRuntimeContext.from_environ(self.environ)
        except ReportClientError as exc:
            raise CliError("runtime_unavailable", str(exc)) from exc
        return build_runtime_transport()


def validate_identity(value: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise ValueError("invalid_id")
    return value


def run_path(output_root: Path, run_id: str) -> Path:
    return Path(output_root).resolve() / validate_identity(run_id)


def analysis_path(output_root: Path, run_id: str, analysis_id: str) -> Path:
    return run_path(output_root, run_id) / "analysis" / validate_identity(analysis_id)


def _external_root(value: Path | None) -> Path:
    # The workspace root is the caller's cwd; run data must never live in the Skill package.
    root = Path(value or (Path.cwd() / "千川素材脚本数据")).expanduser().resolve()
    try:
        root.relative_to(_SKILL_ROOT)
    except ValueError:
        return root
    raise CliError("output_root_inside_skill", "run output must be outside the Skill installation directory")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliError("invalid_json", f"unable to read JSON input: {Path(path).name}") from exc
    if not isinstance(payload, dict):
        raise CliError("invalid_json", "JSON input must be an object")
    return payload


def _reserve(path: Path, error_code: str, identity_label: str) -> None:
    if path.exists():
        raise CliError(error_code, f"{identity_label} already exists")


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def _new_analysis_id() -> str:
    return f"analysis-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _request_analysis_id(payload: Mapping[str, Any], override: str | None) -> str:
    request_value = str(payload.get("analysisId") or "")
    request_id = validate_identity(request_value) if request_value else (validate_identity(override) if override else _new_analysis_id())
    if override is not None and request_value and validate_identity(override) != request_id:
        raise CliError("analysis_id_mismatch", "--analysis-id does not match request.json")
    return request_id


def _request_run_id(payload: Mapping[str, Any]) -> str:
    if not payload.get("runId"):
        return _new_run_id()
    try:
        return validate_identity(str(payload.get("runId") or ""))
    except ValueError as exc:
        raise CliError("invalid_id", "request.json has an invalid runId") from exc


def _status(path: Path) -> str | None:
    status_path = Path(path) / "status.json"
    if not status_path.is_file():
        return None
    payload = _read_json(status_path)
    return str(payload.get("state") or payload.get("status") or "") or None


def _acquisition_reply(output_dir: Path, result: Path) -> dict[str, Any]:
    reply = {"status": _status(output_dir) or "ready", "runId": output_dir.name, "outputPath": str(result)}
    if reply["status"] == "rpaPaused":
        status = _read_json(output_dir / "status.json")
        reply.update({key: status[key] for key in ("errorCode", "message", "gatePath")})
        reply["firstBatchCsvGate"] = _read_json(output_dir / "first-batch-csv-gate.json")
    return reply


def _normalize_acquisition_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def selected_shop_id(value: Any) -> Any:
        if isinstance(value, Mapping):
            extra = value.get("extra")
            if isinstance(extra, Mapping):
                shop_id = extra.get("shop_id")
                return str(shop_id) if shop_id is not None else None
        return value

    if payload.get("liveAcquire") is not None:
        if not isinstance(payload["liveAcquire"], Mapping):
            return payload
        live = dict(payload["liveAcquire"])
        for key in ("apiShop", "rpaShop"):
            if key in live:
                live[key] = selected_shop_id(live[key])
        return {**payload, "liveAcquire": live}
    if payload.get("verifiedRun") is not None:
        return payload
    public_to_internal = {
        "api_shop": "apiShop", "advertiser_id": "advertiserId", "rpa_shop": "rpaShop",
        "top_n": "topN", "material_filter_sort": "materialFilterSort",
        "identity_retry_limit": "identityRetryLimit",
    }
    live = {internal: payload[key] for key, internal in public_to_internal.items() if key in payload}
    for key in ("apiShop", "rpaShop"):
        if key in live:
            live[key] = selected_shop_id(live[key])
    normalized = {key: value for key, value in payload.items() if key not in public_to_internal and key != "date_range"}
    if "period" not in normalized and payload.get("date_range") is not None:
        normalized["period"] = payload["date_range"]
    normalized["liveAcquire"] = live
    return normalized


def _field_registry():
    candidates = (
        _SKILL_ROOT / "config" / "asset-field-registry-v1.json",
        Path(__file__).resolve().parents[3] / "config" / "asset-field-registry-v1.json",
    )
    for path in candidates:
        if path.is_file():
            return load_field_registry(path)
    raise CliError("field_registry_unavailable", "Qianchuan field registry is missing from the Skill package")


def _describe_acquire(_args: argparse.Namespace) -> dict[str, Any]:
    registry = _field_registry()
    default_query = registry.resolve_query(None)
    sortable = [
        {
            "fieldId": entry["id"],
            "label": entry["label"],
            "sourceKey": entry.get("sourceKey"),
            "operators": list(entry["operators"]),
        }
        for entry in registry.entries()
        if entry.get("kind") == "metric" and entry.get("sortable") is True
    ]
    return {
        "schemaVersion": 1,
        "status": "ready",
        "requiredInputs": [
            {"path": "period.startDate", "type": "date", "required": True, "maxPolicy": "t_plus_2", "timezone": "Asia/Shanghai"},
            {"path": "period.endDate", "type": "date", "required": True, "maxPolicy": "t_plus_2", "timezone": "Asia/Shanghai"},
            {"path": "liveAcquire.apiShop", "type": "string", "required": True},
            {"path": "liveAcquire.rpaShop", "type": "string", "required": True},
            {"path": "liveAcquire.topN", "type": "integer", "required": False, "default": 10, "minimum": 1},
            {"path": "liveAcquire.identityRetryLimit", "type": "integer", "required": False, "default": 2, "minimum": 0, "maximum": 3},
            {
                "path": "liveAcquire.materialFilterSort",
                "type": "object",
                "required": False,
                "shape": {"sortField": "registered field label or ID", "direction": ["asc", "desc"], "filters": []},
            },
        ],
        "defaultSort": {
            "fieldId": default_query.sort_entry["id"],
            "label": default_query.sort_entry["label"],
            "direction": default_query.direction,
        },
        "sortableFields": sortable,
        "sorting": {
            "primary": "registered metric value",
            "tieBreaker": "materialId",
            "tieBreakerDirection": "same as direction",
            "maxConcurrentRpaTasks": 3,
        },
        "fieldContracts": [
            {"label": "整体消耗", "fieldId": "stat_cost_for_roi2"},
            {"label": "综合成本", "fieldId": "stat_cost_for_overall_roi2"},
        ],
        "reportOrderBy": {"fieldId": "stat_cost_for_roi2", "direction": "desc", "userSelectionApplied": False},
        "previewCommand": "preview-acquire --input <json-file>",
        "derivedInputMapping": {
            "api_shop": "liveAcquire.apiShop", "rpa_shop": "liveAcquire.rpaShop",
            "date_range": "period", "top_n": "liveAcquire.topN",
            "material_filter_sort": "liveAcquire.materialFilterSort",
            "identity_retry_limit": "liveAcquire.identityRetryLimit",
        },
        "firstBatchCsvGate": {"maxBatchSize": 3, "requiresActualCsv": True, "noValidCsv": "rpaPaused", "unknownResult": "rpaPaused"},
        "externalCalls": False,
    }


def _preview_acquire(args: argparse.Namespace) -> dict[str, Any]:
    payload = _normalize_acquisition_payload(_read_json(args.input))
    validate_payload(payload, "qianchuan-script-acquisition-input.schema.json")
    request = AcquisitionRequest.from_dict(payload)
    if request.live_acquire is None:
        raise CliError("preview_requires_live_acquire", "preview-acquire requires liveAcquire input")
    registry = _field_registry()
    raw_spec = request.live_acquire.material_filter_sort or {}
    # Validate the fixed report contract and account/date formats independently
    # of the user's local material selection expression.
    try:
        # Preview is offline; a placeholder validates fixed report parameters without claiming authorization.
        preview_live = replace(request.live_acquire, advertiser_id=request.live_acquire.advertiser_id or "0")
        report_params = report_business_params(replace(request, live_acquire=preview_live))
    except ReportClientError as exc:
        raise CliError("invalid_report_request", str(exc)) from exc
    try:
        query = registry.resolve_query(request.live_acquire.material_filter_sort)
    except QueryError as exc:
        available_fields = [
            {"fieldId": entry["id"], "label": entry["label"]}
            for entry in registry.entries()
            if entry.get("kind") == "metric" and entry.get("sortable") is True
        ]
        return {
            "schemaVersion": 1,
            "status": "awaitingSelection",
            "mode": "liveAcquire",
            "canAcquireReport": True,
            "selection": {
                "errorCode": "selection_requires_confirmation",
                "message": str(exc),
                "requested": raw_spec,
                "availableSortFields": available_fields,
                "resumeCommand": "continue-acquire --input <corrected-json> --run-dir <awaiting-selection-run>",
            },
            "period": request.period,
            "reportRequest": {
                "dataTopic": report_params["business_params"]["dataTopic"],
                "fixedFilters": report_params["business_params"]["filters"],
                "fixedOrderBy": report_params["business_params"]["orderBy"],
                "selectionAffectsPayload": False,
            },
            "maxConcurrentRpaTasks": 3,
            "identityRetryLimit": request.live_acquire.identity_retry_limit,
            "externalCalls": False,
        }
    resolved_filters = []
    for entry, operator, value in query.filters:
        if isinstance(value, tuple):
            value = list(value)
        elif hasattr(value, "as_tuple"):
            value = str(value)
        resolved_filters.append({"fieldId": entry["id"], "label": entry["label"], "operator": operator, "value": value})
    return {
        "schemaVersion": 1,
        "status": "ready",
        "mode": "liveAcquire",
        "inputsPresent": {
            "apiShop": bool(request.live_acquire.api_shop),
            "rpaShop": bool(request.live_acquire.rpa_shop),
            "period": bool(request.period.get("startDate") and request.period.get("endDate")),
            "topN": request.live_acquire.top_n,
            "materialFilterSort": bool(raw_spec),
        },
        "period": request.period,
        "sorting": {
            "requestedField": raw_spec.get("sortField") or raw_spec.get("field") or query.sort_entry["label"],
            "fieldId": query.sort_entry["id"],
            "label": query.sort_entry["label"],
            "direction": query.direction,
            "tieBreaker": {"field": "materialId", "direction": query.direction},
            "filters": resolved_filters,
        },
        "reportRequest": {
            "dataTopic": report_params["business_params"]["dataTopic"],
            "fixedFilters": report_params["business_params"]["filters"],
            "fixedOrderBy": report_params["business_params"]["orderBy"],
            "selectionAffectsPayload": False,
        },
        "maxConcurrentRpaTasks": 3,
        "identityRetryLimit": request.live_acquire.identity_retry_limit,
        "externalCalls": False,
    }


class _LiveReportGateway:
    def __init__(self, transport: Any, environ: Mapping[str, str]):
        self.transport = transport
        self.environ = dict(environ)

    def fetch_material_report(self, request: AcquisitionRequest, output_dir: Path) -> list[dict[str, Any]]:
        return fetch_material_report(request, output_dir, self.transport, environ=self.environ)


def _acquire(args: argparse.Namespace) -> dict[str, Any]:
    payload = _read_json(args.input)
    payload = _normalize_acquisition_payload(payload)
    validate_payload(payload, "qianchuan-script-acquisition-input.schema.json")
    request = AcquisitionRequest.from_dict(payload)
    output_root = _external_root(args.output_root)
    run_id = _new_run_id()
    output_dir = run_path(output_root, run_id)
    _reserve(output_dir, "run_id_exists", "runId")
    if request.verified_run is not None:
        result = import_verified_run(Path(request.verified_run.source_run), output_dir)
        return {"status": _status(output_dir) or "ready", "runId": run_id, "outputPath": str(result)}
    context = RuntimeContext.from_environment()
    transport = context.require_live_connector()
    registry_path = _SKILL_ROOT / "config" / "asset-field-registry-v1.json"
    report_gateway = _LiveReportGateway(transport, context.environ)
    rpa_gateway = RpaGateway(transport=transport, environ=context.environ)
    try:
        request = resolve_advertiser_id(request, rpa_gateway, transport, environ=context.environ)
    except ReportClientError as exc:
        raise CliError("advertiser_authorization_failed", str(exc)) from exc
    result = acquire_scripts(request, output_dir, report_gateway, rpa_gateway, registry=load_field_registry(registry_path))
    return _acquisition_reply(output_dir, result)


def _external_run_dir(value: Path) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(_SKILL_ROOT)
    except ValueError:
        pass
    else:
        raise CliError("output_root_inside_skill", "run output must be outside the Skill installation directory")
    try:
        validate_identity(path.name)
    except ValueError as exc:
        raise CliError("invalid_id", "run directory has an invalid runId") from exc
    if not path.is_dir():
        raise CliError("run_not_found", "awaiting-selection run directory does not exist")
    return path


def _continue_acquire(args: argparse.Namespace) -> dict[str, Any]:
    payload = _normalize_acquisition_payload(_read_json(args.input))
    validate_payload(payload, "qianchuan-script-acquisition-input.schema.json")
    request = AcquisitionRequest.from_dict(payload)
    if request.live_acquire is None:
        raise CliError("continue_requires_live_acquire", "continue-acquire requires liveAcquire input")
    output_dir = _external_run_dir(args.run_dir)
    assert_detail_rpa_not_paused(output_dir)
    if request.live_acquire.advertiser_id is None:
        try:
            query = _read_json(output_dir / "source-data" / "resolved-query-spec.json")
            advertiser_id = query["reportQuery"]["business_params"]["advertiserId"]
            if isinstance(advertiser_id, bool) or not isinstance(advertiser_id, int) or advertiser_id < 0:
                raise ValueError("invalid resolved advertiser ID")
            request = replace(request, live_acquire=replace(request.live_acquire, advertiser_id=str(advertiser_id)))
        except (CliError, KeyError, TypeError, ValueError) as exc:
            raise CliError("report_snapshot_invalid", "resolved advertiser ID is missing from the report snapshot") from exc
    registry = _field_registry()
    try:
        rows, receipt = inspect_pending_report(request, output_dir)
    except ReportClientError as exc:
        raise CliError("report_snapshot_invalid", str(exc)) from exc
    try:
        registry.resolve_query(request.live_acquire.material_filter_sort)
    except QueryError as exc:
        available_fields = [
            {"fieldId": entry["id"], "label": entry["label"]}
            for entry in registry.entries()
            if entry.get("kind") == "metric" and entry.get("sortable") is True
        ]
        return {
            "status": "awaitingSelection",
            "runId": output_dir.name,
            "outputPath": str(output_dir / receipt["snapshotPath"]),
            "reportRowCount": len(rows),
            "reportSnapshotSha256": receipt["snapshotSha256"],
            "selection": {
                "errorCode": "selection_requires_confirmation",
                "message": str(exc),
                "availableSortFields": available_fields,
                "externalCalls": False,
            },
        }
    context = RuntimeContext.from_environment()
    transport = context.require_live_connector()
    rpa_gateway = RpaGateway(transport=transport, environ=context.environ)
    result = continue_acquire_scripts(request, output_dir, rpa_gateway, registry=registry)
    return {
        **_acquisition_reply(output_dir, result),
        "reportRowCount": len(rows),
        "reportSnapshotSha256": receipt["snapshotSha256"],
    }


def _import_run(args: argparse.Namespace) -> dict[str, Any]:
    source_run = Path(args.source_run).expanduser().resolve()
    run_id = validate_identity(source_run.name)
    output_root = _external_root(args.output_root)
    output_dir = run_path(output_root, run_id)
    _reserve(output_dir, "run_id_exists", "runId")
    result = import_verified_run(source_run, output_dir)
    return {"status": _status(output_dir) or "ready", "runId": run_id, "outputPath": str(result)}


def _render_summary(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir).expanduser().resolve()
    verification = _verify(argparse.Namespace(path=run_dir))
    if verification.get("verification") != "passed":
        raise CliError("source_run_unverified", "source run failed verification; summary was not created")
    try:
        return render_summary(run_dir)
    except WorkbenchError as exc:
        raise CliError(exc.error_code, str(exc)) from exc


def _prepare_analysis(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir).expanduser().resolve()
    verification = _verify(argparse.Namespace(path=run_dir))
    if verification.get("verification") != "passed":
        raise CliError("source_run_unverified", "source run failed verification; analysis was not prepared")
    try:
        return prepare_analysis(run_dir, args.plan, allow_partial=args.allow_partial)
    except WorkbenchError as exc:
        raise CliError(exc.error_code, str(exc)) from exc


def _publish_analysis(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return publish_analysis(args.analysis_root, args.result)
    except WorkbenchError as exc:
        raise CliError(exc.error_code, str(exc)) from exc


def _verify_workbench_operation(analysis_dir: Path, status: Mapping[str, Any]) -> dict[str, Any]:
    try:
        checked = verify_analysis(analysis_dir)
    except WorkbenchError as exc:
        raise CliError(exc.error_code, str(exc)) from exc
    return {"status": status["state"], "operation": "analysis", "verification": "passed", "checkedFiles": checked, "runId": status["runId"], "analysisId": status["analysisId"], "outputPath": str(analysis_dir)}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require_handoff_source(source_pack: Path, run_id: str, *, allow_partial: bool) -> str:
    source_pack = Path(source_pack).expanduser().resolve()
    run_dir = source_pack.parent.parent.resolve()
    try:
        handoff, pack, verified_pack_path = verify_handoff(run_dir)
    except WorkbenchError as exc:
        raise CliError(exc.error_code, str(exc)) from exc
    if verified_pack_path != source_pack or pack.get("runId") != run_id:
        raise CliError("source_pack_mismatch", "generation and rewrite must use the source pack bound by this run's handoff")
    if handoff.get("acquisitionState") == "partialFailed" and not allow_partial:
        raise CliError("partial_run_requires_opt_in", "partialFailed facts require explicit --allow-partial")
    if not handoff.get("analysisAllowed"):
        raise CliError("no_usable_script", "the source pack contains no usable script text")
    return _sha256_file(run_dir / "analysis-handoff.json")


def _mark_workbench_operation(analysis_dir: Path, operation: str, handoff_sha: str, *, allow_partial: bool = False) -> None:
    status_path = Path(analysis_dir) / "status.json"
    status = _read_json(status_path)
    status["operation"] = operation
    status["sourceHandoffSha256"] = handoff_sha
    status["allowPartial"] = allow_partial
    atomic_json(status_path, status)


def _prepare_generation(args: argparse.Namespace) -> dict[str, Any]:
    request_payload = _read_json(args.request)
    if args.brand_profile is not None:
        raise CliError("brand_profile_out_of_scope", "brand-specific generation is outside this general Qianchuan workbench")
    if args.source_pack is not None:
        request_payload.setdefault("runId", _read_json(args.source_pack)["runId"])
        request_payload["sourcePack"] = "facts/qianchuan-script-source-pack.json"
    else:
        raise CliError("missing_source_pack", "--source-pack is required for a platform source request")
    run_id = _request_run_id(request_payload)
    analysis_id = _request_analysis_id(request_payload, args.analysis_id)
    request_payload = {**request_payload, "runId": run_id, "analysisId": analysis_id}
    validate_payload(request_payload, "script-generation-request.schema.json")
    source_pack_path = Path(args.source_pack).expanduser().resolve()
    source_run_dir = source_pack_path.parent.parent.resolve()
    output_root = _external_root(args.output_root or source_run_dir.parent)
    if run_path(output_root, run_id) != source_run_dir:
        raise CliError("output_run_mismatch", "analysis output must remain under the source pack's run directory")
    handoff_sha = _require_handoff_source(args.source_pack, run_id, allow_partial=args.allow_partial)
    analysis_dir = analysis_path(output_root, run_id, analysis_id)
    _reserve(analysis_dir, "analysis_id_exists", "analysisId")
    prompt = prepare_generation(args.request, args.source_pack, analysis_dir, None, run_id=run_id, analysis_id=analysis_id)
    atomic_json(analysis_dir / "request.json", request_payload)
    _mark_workbench_operation(analysis_dir, "generation", handoff_sha, allow_partial=args.allow_partial)
    return {"status": _status(analysis_dir) or "prepared", "operation": "generation", "runId": run_id, "analysisId": analysis_id, "outputPath": str(analysis_dir), "promptPath": str(prompt)}


def _prepare_rewrite(args: argparse.Namespace) -> dict[str, Any]:
    request_payload = _read_json(args.request)
    request_payload.setdefault("runId", _read_json(args.source_pack)["runId"])
    request_payload["sourcePack"] = "facts/qianchuan-script-source-pack.json"
    run_id = _request_run_id(request_payload)
    analysis_id = _request_analysis_id(request_payload, args.analysis_id)
    request_payload = {**request_payload, "runId": run_id, "analysisId": analysis_id}
    validate_payload(request_payload, "script-rewrite-request.schema.json")
    source_pack_path = Path(args.source_pack).expanduser().resolve()
    source_run_dir = source_pack_path.parent.parent.resolve()
    output_root = _external_root(args.output_root or source_run_dir.parent)
    if run_path(output_root, run_id) != source_run_dir:
        raise CliError("output_run_mismatch", "analysis output must remain under the source pack's run directory")
    handoff_sha = _require_handoff_source(args.source_pack, run_id, allow_partial=args.allow_partial)
    analysis_dir = analysis_path(output_root, run_id, analysis_id)
    _reserve(analysis_dir, "analysis_id_exists", "analysisId")
    prompt = prepare_rewrite(args.request, args.source_pack, analysis_dir, run_id=run_id, analysis_id=analysis_id)
    atomic_json(analysis_dir / "request.json", request_payload)
    _mark_workbench_operation(analysis_dir, "rewrite", handoff_sha, allow_partial=args.allow_partial)
    return {"status": _status(analysis_dir) or "prepared", "operation": "rewrite", "runId": run_id, "analysisId": analysis_id, "outputPath": str(analysis_dir), "promptPath": str(prompt)}


def _analysis_identity(analysis_dir: Path) -> tuple[str, str]:
    request = _read_json(analysis_dir / "request.json")
    return _request_run_id(request), _request_analysis_id(request, None)


def _publish_generation(args: argparse.Namespace) -> dict[str, Any]:
    analysis_dir = Path(args.analysis_root).expanduser().resolve()
    run_id, analysis_id = _analysis_identity(analysis_dir)
    operation_status = _read_json(analysis_dir / "status.json")
    handoff_sha = _require_handoff_source(analysis_dir.parent.parent / "facts" / "qianchuan-script-source-pack.json", run_id, allow_partial=bool(operation_status.get("allowPartial")))
    result = publish_generation(args.draft, analysis_dir)
    _mark_workbench_operation(analysis_dir, "generation", handoff_sha, allow_partial=bool(operation_status.get("allowPartial")))
    return {"status": _status(analysis_dir) or "completed", "operation": "generation", "runId": run_id, "analysisId": analysis_id, "outputPath": str(result)}


def _publish_rewrite(args: argparse.Namespace) -> dict[str, Any]:
    analysis_dir = Path(args.analysis_root).expanduser().resolve()
    run_id, analysis_id = _analysis_identity(analysis_dir)
    operation_status = _read_json(analysis_dir / "status.json")
    handoff_sha = _require_handoff_source(analysis_dir.parent.parent / "facts" / "qianchuan-script-source-pack.json", run_id, allow_partial=bool(operation_status.get("allowPartial")))
    result = publish_rewrite(args.draft, analysis_dir)
    _mark_workbench_operation(analysis_dir, "rewrite", handoff_sha, allow_partial=bool(operation_status.get("allowPartial")))
    return {"status": _status(analysis_dir) or "completed", "operation": "rewrite", "runId": run_id, "analysisId": analysis_id, "outputPath": str(result)}


def _verify_csv_gate(path: Path, outcomes: dict[str, Any]) -> dict[str, Any]:
    gate = _read_json(path / "first-batch-csv-gate.json")
    validate_payload(gate, "first-batch-csv-gate.schema.json")
    members = set(gate["firstBatchMaterialIds"])
    completed = set(gate["completedMaterialIds"])
    valid = set(gate["validCsvMaterialIds"])
    unknown = set(gate["unknownMaterialIds"])
    if (
        gate["runId"] != path.name or outcomes.get("firstBatchCsvGate") != gate
        or not completed <= members or not valid <= completed or not unknown <= members
        or completed & unknown
        or (gate["status"] in {"passed", "blocked"} and (completed != members or unknown))
        or (gate["status"] == "passed" and not valid)
        or (gate["status"] == "blocked" and (valid or gate["errorCode"] != "first_batch_no_valid_csv"))
    ):
        raise CliError("csv_gate_mismatch", "first-batch CSV evidence is inconsistent")
    return gate


def _verify_retry_limit(*evidence: Mapping[str, Any]) -> int:
    if not any("identityRetryLimit" in item for item in evidence):
        return 1  # Historical runs allowed exactly one additional attempt.
    limits = [item.get("identityRetryLimit") for item in evidence]
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3 for value in limits) or len(set(limits)) != 1:
        raise CliError("retry_policy_mismatch", "identity retry limit differs across acquisition evidence")
    return limits[0]


def _verify_paused_acquisition(path: Path, status: dict[str, Any]) -> dict[str, Any]:
    outcomes = _read_json(path / OUTCOMES_FILENAME)
    receipt = _read_json(path / "acquisition-receipt.json")
    validate_payload(outcomes, "acquisition-results.schema.json")
    validate_payload(receipt, "script-acquisition-receipt.schema.json")
    _verify_retry_limit(status, outcomes, receipt)
    gate = _verify_csv_gate(path, outcomes)
    if (
        gate["status"] not in {"pending", "blocked", "unconfirmed"}
        or any(item.get("runId") != path.name for item in (status, outcomes, receipt))
        or any(item.get("status") != "rpaPaused" for item in (outcomes, receipt))
        or any(item.get("gatePath") != "first-batch-csv-gate.json" for item in (status, receipt))
        or any(item.get("errorCode") != gate["errorCode"] or item.get("message") != gate["message"] for item in (status, receipt))
    ):
        raise CliError("csv_gate_mismatch", "paused state and first-batch receipts differ")
    for name in receipt["outputs"]:
        output = (path / name).resolve()
        if not output.is_relative_to(path) or not output.is_file():
            raise CliError("missing_output", "paused acquisition evidence is missing or outside the run")
    return {
        **_acquisition_reply(path, path), "verification": "paused",
        "checkedFiles": ["status.json", OUTCOMES_FILENAME, "acquisition-receipt.json", "first-batch-csv-gate.json"],
    }


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.path).expanduser().resolve()
    status = _read_json(path / "status.json")
    if status.get("operation") == "analysis":
        return _verify_workbench_operation(path, status)
    validate_payload(status, "script-run-status.schema.json")
    if status["state"] == "rpaPaused":
        return _verify_paused_acquisition(path, status)
    if status["state"] not in {"ready", "partialFailed"}:
        assert_detail_rpa_not_paused(path)
    checked = ["status.json"]
    if status.get("operation") in {"generation", "rewrite"}:
        run_dir = path.parent.parent.resolve()
        handoff_path = run_dir / "analysis-handoff.json"
        if not handoff_path.is_file() or _sha256_file(handoff_path) != status.get("sourceHandoffSha256"):
            raise CliError("handoff_hash_mismatch", "script analysis is not bound to the current phase-one handoff")
        try:
            handoff, _pack, _source_pack = verify_handoff(run_dir)
        except WorkbenchError as exc:
            raise CliError(exc.error_code, str(exc)) from exc
        if handoff.get("acquisitionState") == "partialFailed" and not status.get("allowPartial"):
            raise CliError("partial_run_requires_opt_in", "partialFailed analysis lacks explicit opt-in")
        checked.append("../../analysis-handoff.json")
    if status.get("analysisId"):
        request = _read_json(path / "request.json")
        kind = "rewrite" if "originalText" in request else "generation"
        if f"prepare-{kind}" not in _ALLOWED_COMMANDS:
            raise CliError("wrong_skill", "analysis belongs to another Skill")
        validate_payload(request, f"script-{kind}-request.schema.json")
        checked.append("request.json")
        if status["state"] in {"completed", "draftOnly"} and (path / "receipt.json").exists():
            receipt = _read_json(path / "receipt.json")
            validate_payload(receipt, "script-analysis-receipt.schema.json")
            filename = "rewritten-script.json" if kind == "rewrite" else "generated-scripts.json"
            draft = _read_json(path / filename)
            validate_payload(draft, "rewritten-script.schema.json" if kind == "rewrite" else "generated-scripts.schema.json")
            from script_creation_session import _validate_session_binding
            _validate_session_binding(draft, path)
            from script_creation_validation import validate_generation_draft, validate_rewrite_draft, audit_brand_storyboard
            customer_facts = _read_json(path / "customer-facts.json")
            references = _read_json(path / "reference-selection.json")
            if kind == "rewrite":
                validate_rewrite_draft(draft, request, customer_facts, references)
            else:
                validate_generation_draft(draft, customer_facts, references, allow_unreferenced=(path / "brand-profile.json").is_file())
                if (path / "brand-profile.json").exists():
                    audit_brand_storyboard(draft, request, _read_json(path / "brand-profile.json"))
            if receipt["inputHashes"] != draft["inputHashes"]:
                raise CliError("receipt_mismatch", "receipt input hashes differ from result")
            for key in ("runId", "analysisId"):
                if receipt[key] != status[key] or draft[key] != status[key]:
                    raise CliError("identity_mismatch", "analysis output identities differ")
            if receipt["status"] != status["state"] or draft["status"] != status["state"]:
                raise CliError("status_mismatch", "analysis output states differ")
            checked.extend(["receipt.json", filename])
            for item in receipt["outputs"]:
                output = (path / item).resolve()
                if not output.is_relative_to(path) or not output.is_file():
                    raise CliError("missing_output", "analysis output is absent or outside its directory")
        elif status["state"] == "completed" or (path / "generated-scripts.json").exists() or (path / "rewritten-script.json").exists():
            raise CliError("missing_receipt", "completed analysis has no receipt")
    elif status["state"] == "awaitingSelection":
        receipt = _read_json(path / "acquisition-receipt.json")
        report_receipt = _read_json(path / "report-query-receipt.json")
        pending = _read_json(path / "selection-pending.json")
        validate_payload(receipt, "script-acquisition-receipt.schema.json")
        _verify_retry_limit(status, receipt)
        validate_payload(report_receipt, "qianchuan-report-query-receipt.schema.json")
        validate_payload(pending, "qianchuan-selection-pending.schema.json")
        snapshot_path = (path / report_receipt["snapshotPath"]).resolve()
        if not snapshot_path.is_relative_to(path) or not snapshot_path.is_file():
            raise CliError("missing_report_snapshot", "saved material report snapshot is absent")
        snapshot = _read_json(snapshot_path)
        validate_payload(snapshot, "qianchuan-material-report-snapshot.schema.json")
        rows_digest = hashlib.sha256(json.dumps(
            snapshot["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        snapshot_digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        if (
            status["runId"] != report_receipt["runId"]
            or status["runId"] != receipt["runId"]
            or status["runId"] != pending["runId"]
            or len(snapshot["rows"]) != snapshot["recordCount"]
            or rows_digest != snapshot["rowsSha256"]
            or snapshot_digest != report_receipt["snapshotSha256"]
            or snapshot_digest != status.get("reportSnapshotSha256")
            or snapshot_digest != pending["reportSnapshotSha256"]
            or snapshot["rowsSha256"] != report_receipt["rowsSha256"]
            or snapshot["recordCount"] != report_receipt["recordCount"]
            or snapshot["queryFingerprint"] != report_receipt["queryFingerprint"]
            or snapshot["scopeFingerprint"] != report_receipt["scopeFingerprint"]
            or pending["reportSnapshot"] != report_receipt["snapshotPath"]
            or pending["reportRowCount"] != snapshot["recordCount"]
            or receipt["status"] != "awaitingSelection"
            or receipt["counts"] != {"requested": 0, "available": 0, "missing": 0, "failed": 0}
        ):
            raise CliError("report_snapshot_mismatch", "awaiting-selection report evidence differs")
        if (path / OUTCOMES_FILENAME).exists() or (path / "facts/qianchuan-script-source-pack.json").exists():
            raise CliError("unexpected_acquisition_output", "awaiting-selection run already has RPA or source-pack output")
        for folder_name in ("attempts", "tasks"):
            folder = path / "source-data" / folder_name
            if folder.is_dir() and any(item.is_file() for item in folder.rglob("*")):
                raise CliError("unexpected_rpa_evidence", "awaiting-selection run already contains RPA evidence")
        for item in receipt["outputs"]:
            output_path = (path / item).resolve()
            if not output_path.is_relative_to(path) or not output_path.is_file():
                raise CliError("missing_output", "acquisition output is absent or outside its run directory")
        checked.extend([
            "acquisition-receipt.json",
            "report-query-receipt.json",
            SELECTION_PENDING_FILENAME,
            REPORT_SNAPSHOT_PATH,
        ])
        if SELECTION_FILENAME in receipt["outputs"]:
            selection_audit = _read_json(path / SELECTION_FILENAME)
            validate_payload(selection_audit, "qianchuan-material-selection-audit.schema.json")
            if (
                selection_audit["status"] != "awaitingSelection"
                or not selection_audit["systemicError"]
                or selection_audit["selectedCount"] != 0
                or selection_audit["reportSnapshotSha256"] != snapshot_digest
                or selection_audit["reportRowCount"] != snapshot["recordCount"]
            ):
                raise CliError("selection_audit_mismatch", "pending selection audit differs from the saved report")
            checked.append(SELECTION_FILENAME)
    elif status["state"] in {"ready", "partialFailed"}:
        pack = _read_json(path / "facts/qianchuan-script-source-pack.json")
        receipt = _read_json(path / "acquisition-receipt.json")
        validate_payload(pack, "qianchuan-script-source-pack.schema.json")
        validate_payload(receipt, "script-acquisition-receipt.schema.json")
        if any(value != status["runId"] for value in (pack["runId"], receipt["runId"])):
            raise CliError("identity_mismatch", "acquisition output identities differ")
        if receipt["status"] not in {status["state"], "completed" if status["state"] == "ready" else status["state"]}:
            raise CliError("status_mismatch", "acquisition receipt state differs")
        report_receipt = _read_json(path / "report-query-receipt.json")
        selection_audit = _read_json(path / SELECTION_FILENAME)
        validate_payload(report_receipt, "qianchuan-report-query-receipt.schema.json")
        validate_payload(selection_audit, "qianchuan-material-selection-audit.schema.json")
        snapshot_path = (path / report_receipt["snapshotPath"]).resolve()
        if not snapshot_path.is_relative_to(path) or not snapshot_path.is_file():
            raise CliError("missing_report_snapshot", "saved material report snapshot is absent")
        snapshot = _read_json(snapshot_path)
        validate_payload(snapshot, "qianchuan-material-report-snapshot.schema.json")
        snapshot_digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        rows_digest = hashlib.sha256(json.dumps(
            snapshot["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if (
            report_receipt["runId"] != status["runId"]
            or snapshot_digest != report_receipt["snapshotSha256"]
            or snapshot_digest != status.get("reportSnapshotSha256")
            or snapshot["rowsSha256"] != rows_digest
            or snapshot["rowsSha256"] != report_receipt["rowsSha256"]
            or snapshot["recordCount"] != len(snapshot["rows"])
            or snapshot["recordCount"] != report_receipt["recordCount"]
            or selection_audit["reportSnapshotSha256"] != snapshot_digest
            or selection_audit["reportRowCount"] != snapshot["recordCount"]
        ):
            raise CliError("report_snapshot_mismatch", "report or selection evidence differs")
        from qianchuan_script_acquisition_fact_pack import normalize_text
        counts = {"requested": len(pack["materials"]), "available": 0, "missing": 0, "failed": 0}
        content_counts = {key: {"available": 0, "missing": 0} for key in ("formulaLabels", "detailLabels", "structuredData", "transcript")}
        material_ids = [item["materialId"] for item in pack["materials"]]
        if len(set(material_ids)) != len(material_ids) or [item["materialId"] for item in pack["scripts"]] != material_ids:
            raise CliError("identity_mismatch", "source material/script mapping differs")
        if selection_audit["selectedMaterialIds"] != material_ids or selection_audit["selectedCount"] != len(material_ids):
            raise CliError("selection_mismatch", "selected materials differ from the selection audit")
        for script in pack["scripts"]:
            counts["available" if script["parseStatus"] == "parsed" else script["parseStatus"]] += 1
            for key in content_counts:
                content_counts[key]["available" if (script.get("completeness") or {}).get(key, False) else "missing"] += 1
            for field, text in (("rawTextSha256", script["rawText"]), ("normalizedTextSha256", normalize_text(script["rawText"]))):
                if hashlib.sha256(text.encode()).hexdigest() != script[field]:
                    raise CliError("hash_mismatch", "source script hash differs")
        if any(value != counts for value in (pack["availability"], status.get("availability"), receipt["counts"])):
            raise CliError("count_mismatch", "source availability counts differ")
        if pack.get("contentAvailability") is not None and pack["contentAvailability"] != content_counts:
            raise CliError("count_mismatch", "source content availability counts differ")

        outcome_file = path / OUTCOMES_FILENAME
        expected_partial = counts["failed"] > 0
        if outcome_file.is_file():
            outcomes = _read_json(outcome_file)
            validate_payload(outcomes, "acquisition-results.schema.json")
            identity_retry_limit = _verify_retry_limit(status, outcomes, receipt)
            has_content_evidence = "identityRetryLimit" in outcomes
            material_id_entry = _field_registry().require("material_id")
            report_rows = {str(_value_at(row, material_id_entry) or "").strip(): row for row in snapshot["rows"]}
            if OUTCOMES_FILENAME not in receipt["outputs"]:
                raise CliError("missing_outcome_receipt", "acquisition results are not listed in the receipt")
            if outcomes["runId"] != status["runId"] or outcomes["status"] != status["state"]:
                raise CliError("identity_mismatch", "acquisition results identity or state differs")
            if "firstBatchCsvGate" in outcomes or (path / "first-batch-csv-gate.json").exists():
                gate = _verify_csv_gate(path, outcomes)
                if gate["status"] != "passed":
                    raise CliError("csv_gate_mismatch", "acquisition is not allowed past the first-batch CSV gate")
                checked.append("first-batch-csv-gate.json")
            if len(outcomes["materials"]) != len(pack["materials"]):
                raise CliError("count_mismatch", "acquisition material count differs")
            state_counts = {key: 0 for key in ("available", "submittedWithoutScript", "failed", "submissionUnknown", "unsubmitted")}
            task_submissions = 0
            script_by_id = {item["materialId"]: item for item in pack["scripts"]}

            def checked_artifact(relative: str) -> Path:
                artifact = (path / relative).resolve()
                if not artifact.is_relative_to(path) or not artifact.is_file():
                    raise CliError("missing_evidence", "acquisition evidence is absent or outside its run directory")
                return artifact

            for material, outcome in zip(pack["materials"], outcomes["materials"]):
                material_id = material["materialId"]
                if outcome["materialId"] != material_id or outcome["rank"] != material["rank"]:
                    raise CliError("identity_mismatch", "acquisition outcome material order differs")
                state_counts[outcome["state"]] += 1
                script = script_by_id[material_id]
                expected_parse_status = {
                    "available": "parsed",
                    "submittedWithoutScript": "missing",
                    "failed": "failed",
                    "submissionUnknown": "failed",
                    "unsubmitted": "missing",
                }[outcome["state"]]
                if script["parseStatus"] != expected_parse_status:
                    raise CliError("status_mismatch", "source script status differs from acquisition outcome")
                attempts = outcome["attempts"]
                if len(attempts) > 1 + identity_retry_limit or [item["attempt"] for item in attempts] != list(range(1, len(attempts) + 1)):
                    raise CliError("attempt_mismatch", "acquisition attempt sequence is invalid")
                if outcome["state"] == "unsubmitted" and attempts:
                    raise CliError("attempt_mismatch", "unsubmitted material has attempt evidence")
                material_evidence_refs: list[str] = []
                attempt_evidence_refs: dict[int, set[str]] = {}
                for first in attempts[:-1]:
                    if not (
                        first["identityState"] == "mismatch"
                        and first["taskState"] == "completed"
                        and first["taskGroupId"]
                        and first["payloadSha256"]
                        and first["identityAuditPath"]
                    ):
                        raise CliError("unsafe_retry", "retry lacks preceding terminal mismatch evidence")
                for attempt in attempts:
                    csv_records = []
                    this_attempt_refs = set(
                        [attempt["attemptRecordPath"]]
                        + ([attempt["taskRecordPath"]] if attempt.get("taskRecordPath") else [])
                        + [item["path"] for item in attempt["payloadFiles"]]
                        + ([attempt["identityAuditPath"]] if attempt.get("identityAuditPath") else [])
                    )
                    attempt_evidence_refs[attempt["attempt"]] = this_attempt_refs
                    material_evidence_refs.extend(sorted(this_attempt_refs))
                    attempt_file = checked_artifact(attempt["attemptRecordPath"])
                    if _read_json(attempt_file) != attempt:
                        raise CliError("attempt_mismatch", "attempt record differs from acquisition results")
                    if attempt["taskGroupId"]:
                        task_submissions += 1
                        task_file = checked_artifact(attempt["taskRecordPath"])
                        task = _read_json(task_file)
                        if any(task.get(key) != attempt.get(key) for key in ("materialId", "attempt", "taskGroupId")):
                            raise CliError("identity_mismatch", "persisted RPA task identity differs")
                    elif attempt["taskRecordPath"] is not None:
                        raise CliError("identity_mismatch", "task record exists without a task ID")
                    for payload_file in attempt["payloadFiles"]:
                        payload_path = checked_artifact(payload_file["path"])
                        if hashlib.sha256(payload_path.read_bytes()).hexdigest() != payload_file["sha256"]:
                            raise CliError("hash_mismatch", "raw RPA payload hash differs")
                        if payload_file["kind"] == "records-json":
                            try:
                                normalized_records = json.loads(payload_path.read_text(encoding="utf-8"))
                                validate_payload(normalized_records, "qianchuan-script-attempt-records.schema.json")
                            except Exception as exc:
                                raise CliError("invalid_records_json", "normalized RPA records JSON is invalid") from exc
                        elif has_content_evidence and payload_file["kind"] == "csv":
                            try:
                                csv_records.extend(_record_payload(record) for record in parse_diagnosis_csv(payload_path))
                            except RpaCsvError:
                                # Acquisition keeps malformed attachments as evidence
                                # while admitting a separate valid CSV if one exists.
                                pass
                    combined = hashlib.sha256(json.dumps(
                        [{"path": item["path"], "sha256": item["sha256"]} for item in attempt["payloadFiles"]],
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    ).encode("utf-8")).hexdigest() if attempt["payloadFiles"] else None
                    if combined != attempt["payloadSha256"]:
                        raise CliError("hash_mismatch", "combined RPA payload hash differs")
                    if attempt["identityAuditPath"]:
                        identity_file = checked_artifact(attempt["identityAuditPath"])
                        identity = _read_json(identity_file)
                        if (
                            identity.get("materialId") != material_id
                            or identity.get("state") != attempt["identityState"]
                            or identity.get("mismatchedFields") != attempt["mismatchedFields"]
                        ):
                            raise CliError("identity_mismatch", "identity audit differs from attempt record")
                        if has_content_evidence:
                            expected_row = report_rows.get(material_id)
                            if expected_row is None:
                                raise CliError("identity_mismatch", "identity audit material is absent from report snapshot")
                            policy = identity.get("identityPolicy")
                            if policy not in (None, RETURNED_ID_POLICY):
                                raise CliError("identity_mismatch", "unknown identity policy in persisted audit")
                            # Reproduce the archived policy, including its exact
                            # observed fields, so older fingerprints remain valid.
                            recomputed_identity = audit_identity({**expected_row, "materialId": material_id}, csv_records,
                                                                 include_returned_id=policy == RETURNED_ID_POLICY)
                            if identity != recomputed_identity:
                                raise CliError("identity_mismatch", "identity audit differs from report and returned CSV")
                            fingerprints = content_evidence(csv_records, recomputed_identity)
                            if any(attempt.get(key) != value for key, value in fingerprints.items()):
                                raise CliError("content_fingerprint_mismatch", "returned content fingerprint differs from CSV evidence")
                    elif attempt["identityState"] is not None:
                        raise CliError("identity_mismatch", "identity state has no persisted audit")
                    elif has_content_evidence and any(attempt.get(key) != value for key, value in {
                        "scriptContentPresent": False, "scriptContentSha256": None, "observedIdentitySha256": None,
                    }.items()):
                        raise CliError("content_fingerprint_mismatch", "content fingerprint exists without an identity audit")
                if not set(material_evidence_refs).issubset(set(script["sourceRefs"])):
                    raise CliError("missing_evidence_reference", "source script does not reference all acquisition attempt evidence")
                if "scheduler" in outcomes and (script.get("materialFile") or script.get("parseStatus") == "parsed"):
                    material_fact_ref = script.get("materialFile")
                    material_fact_hash = script.get("materialFileSha256")
                    if not material_fact_ref or not material_fact_hash:
                        raise CliError("missing_material_fact", "script with content has no independent material fact")
                    material_fact_path = checked_artifact(material_fact_ref)
                    if hashlib.sha256(material_fact_path.read_bytes()).hexdigest() != material_fact_hash:
                        raise CliError("hash_mismatch", "independent material fact hash differs")
                    material_fact = _read_json(material_fact_path)
                    validate_payload(material_fact, "qianchuan-script-material-fact.schema.json")
                    selected_attempt = material_fact.get("selectedAttempt")
                    if (
                        material_fact.get("identityState") != "matched"
                        or not isinstance(selected_attempt, int)
                        or selected_attempt not in attempt_evidence_refs
                        or attempts[selected_attempt - 1].get("identityState") != "matched"
                    ):
                        raise CliError("identity_mismatch", "material content is not bound to a matched attempt")
                    if any(material_fact.get(key) != expected for key, expected in {
                        "runId": pack["runId"], "materialId": material_id, "rank": material["rank"],
                        "scriptId": script["scriptId"], "rawText": script["rawText"],
                        "rawTextSha256": script["rawTextSha256"],
                        "normalizedTextSha256": script["normalizedTextSha256"],
                        "parseStatus": script["parseStatus"], "identityState": "matched",
                        "formula": script.get("formula"), "detail": script.get("detail"),
                        "data": script.get("data"), "text": script.get("text"),
                        "completeness": script.get("completeness"),
                        "fieldSourceRefs": script.get("fieldSourceRefs"),
                    }.items()):
                        raise CliError("material_fact_mismatch", "independent material fact differs from source pack")
                    if not set(script["sourceRefs"]).issubset(set(material_fact.get("sourceRefs") or [])):
                        raise CliError("missing_evidence_reference", "independent material fact omits source evidence")
                    for field, refs in (material_fact.get("fieldSourceRefs") or {}).items():
                        if not set(refs).issubset(attempt_evidence_refs[selected_attempt]):
                            raise CliError("field_evidence_mismatch", f"{field} content cites evidence outside its matched attempt")
                    checked.append(material_fact_ref)
            recomputed = {
                "requested": len(outcomes["materials"]),
                "taskSubmissions": task_submissions,
                **state_counts,
            }
            if outcomes["counts"] != recomputed:
                raise CliError("count_mismatch", "acquisition outcome counts differ")
            if sum(state_counts.values()) != recomputed["requested"]:
                raise CliError("count_mismatch", "acquisition outcome states do not partition requested materials")
            if counts["available"] != state_counts["available"]:
                raise CliError("count_mismatch", "source available count differs from acquisition outcomes")
            if counts["missing"] != state_counts["submittedWithoutScript"] + state_counts["unsubmitted"]:
                raise CliError("count_mismatch", "legacy missing count differs from detailed outcomes")
            if counts["failed"] != state_counts["failed"] + state_counts["submissionUnknown"]:
                raise CliError("count_mismatch", "legacy failed count differs from detailed outcomes")
            scheduler = outcomes.get("scheduler")
            if scheduler is not None:
                if scheduler.get("maxConcurrency") != 3 or scheduler.get("submittedTaskCount") != task_submissions:
                    raise CliError("scheduler_mismatch", "scheduler receipt differs from RPA task submissions")
                if any(item.get("inFlight", 0) > 3 for item in scheduler.get("events", [])):
                    raise CliError("scheduler_mismatch", "scheduler exceeded the three task limit")
                if not scheduler.get("underfillReason"):
                    raise CliError("scheduler_mismatch", "scheduler receipt omits the underfill reason")
                if has_content_evidence:
                    mismatch_seen = any(attempt.get("identityState") == "mismatch" for item in outcomes["materials"] for attempt in item["attempts"])
                    if scheduler.get("effectiveConcurrency") != (1 if mismatch_seen else 3):
                        raise CliError("scheduler_mismatch", "identity recovery concurrency differs from mismatch evidence")
                    recovery_started = False
                    for event in scheduler["events"]:
                        if event.get("attempt", 1) > 1 and not event.get("identityRecovery"):
                            raise CliError("scheduler_mismatch", "identity retry was not isolated")
                        if recovery_started and not event.get("identityRecovery"):
                            raise CliError("scheduler_mismatch", "scheduler left serial identity recovery")
                        recovery_started = recovery_started or bool(event.get("identityRecovery"))
                        if recovery_started and event["inFlight"] != 1:
                            raise CliError("scheduler_mismatch", "identity recovery submitted overlapping tasks")
            expected_partial = any(state_counts[key] for key in ("failed", "submissionUnknown", "unsubmitted"))
            checked.append(OUTCOMES_FILENAME)
        if expected_partial != (status["state"] == "partialFailed"):
            raise CliError("status_mismatch", "source state differs from failure count")
        checked.extend([
            "facts/qianchuan-script-source-pack.json",
            "acquisition-receipt.json",
            "report-query-receipt.json",
            REPORT_SNAPSHOT_PATH,
            SELECTION_FILENAME,
        ])
        for item in receipt["outputs"]:
            if item in {"status.json", "facts/qianchuan-script-source-pack.json", "acquisition-receipt.json"}:
                continue
            output_path = (path / item).resolve()
            if not output_path.is_relative_to(path) or not output_path.is_file():
                raise CliError("missing_output", "acquisition output is absent or outside its run directory")
        if (path / "analysis-handoff.json").is_file():
            try:
                verify_handoff(path)
            except WorkbenchError as exc:
                raise CliError(exc.error_code, str(exc)) from exc
            checked.extend(["overview/summary-data.json", "overview/report.md", "overview/receipt.json", "analysis-handoff.json"])
    result: dict[str, Any] = {"status": str(status.get("state") or status.get("status") or "unknown"), "outputPath": str(path)}
    result["verification"] = "passed"
    result["checkedFiles"] = checked
    if status.get("runId"):
        result["runId"] = status["runId"]
    if status.get("analysisId"):
        result["analysisId"] = status["analysisId"]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="short-video-script")
    commands = parser.add_subparsers(dest="command", required=True)

    if "describe-acquire" in _ALLOWED_COMMANDS:
        commands.add_parser("describe-acquire", help="print machine-readable acquisition inputs and registered sort fields")

    if "preview-acquire" in _ALLOWED_COMMANDS:
        preview = commands.add_parser("preview-acquire", help="validate acquisition input and resolve sorting without external calls")
        preview.add_argument("--input", required=True, type=Path)

    if "acquire" in _ALLOWED_COMMANDS:
        acquire = commands.add_parser("acquire", help="acquire Qianchuan reference scripts under 千川素材脚本数据/ by default")
        acquire.add_argument("--input", required=True, type=Path)
        acquire.add_argument("--output-root", type=Path)

    if "continue-acquire" in _ALLOWED_COMMANDS:
        continuation = commands.add_parser(
            "continue-acquire",
            help="resume local material selection from an existing report snapshot",
        )
        continuation.add_argument("--input", required=True, type=Path)
        continuation.add_argument("--run-dir", required=True, type=Path)

    if "import-run" in _ALLOWED_COMMANDS:
        imported = commands.add_parser("import-run")
        imported.add_argument("--source-run", required=True, type=Path)
        imported.add_argument("--output-root", type=Path)

    if "render-summary" in _ALLOWED_COMMANDS:
        summary = commands.add_parser("render-summary", help="verify an existing run and write its phase-one report and handoff")
        summary.add_argument("--run-dir", required=True, type=Path)

    if "prepare-analysis" in _ALLOWED_COMMANDS:
        analysis = commands.add_parser("prepare-analysis", help="validate a retrieval plan and prepare a read-only fact slice for model analysis")
        analysis.add_argument("--run-dir", required=True, type=Path)
        analysis.add_argument("--plan", required=True, type=Path)
        analysis.add_argument("--allow-partial", action="store_true", help="allow explicit analysis of verified facts from a partialFailed run")

    if "publish-analysis" in _ALLOWED_COMMANDS:
        publish = commands.add_parser("publish-analysis", help="validate and publish an evidence-bound model analysis result")
        publish.add_argument("--analysis-root", required=True, type=Path)
        publish.add_argument("--result", required=True, type=Path)

    if "prepare-generation" in _ALLOWED_COMMANDS:
        generation = commands.add_parser("prepare-generation")
        generation.add_argument("--request", required=True, type=Path)
        generation.add_argument("--source-pack", required=True, type=Path)
        generation.add_argument("--output-root", type=Path)
        generation.add_argument("--analysis-id")
        generation.add_argument("--allow-partial", action="store_true", help="allow explicit generation from verified facts in a partialFailed run")
        generation.add_argument("--brand-profile", type=Path, help=argparse.SUPPRESS)

    if "publish-generation" in _ALLOWED_COMMANDS:
        publish_generation_parser = commands.add_parser("publish-generation")
        publish_generation_parser.add_argument("--draft", required=True, type=Path)
        publish_generation_parser.add_argument("--analysis-root", required=True, type=Path)

    if "prepare-rewrite" in _ALLOWED_COMMANDS:
        rewrite = commands.add_parser("prepare-rewrite")
        rewrite.add_argument("--request", required=True, type=Path)
        rewrite.add_argument("--source-pack", required=True, type=Path)
        rewrite.add_argument("--output-root", type=Path)
        rewrite.add_argument("--analysis-id")
        rewrite.add_argument("--allow-partial", action="store_true", help="allow explicit rewriting from verified facts in a partialFailed run")

    if "publish-rewrite" in _ALLOWED_COMMANDS:
        publish_rewrite_parser = commands.add_parser("publish-rewrite")
        publish_rewrite_parser.add_argument("--draft", required=True, type=Path)
        publish_rewrite_parser.add_argument("--analysis-root", required=True, type=Path)

    if "verify" in _ALLOWED_COMMANDS:
        verify = commands.add_parser("verify")
        verify.add_argument("--path", required=True, type=Path)

    return parser


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    handlers = {
        "describe-acquire": _describe_acquire,
        "preview-acquire": _preview_acquire,
        "acquire": _acquire,
        "continue-acquire": _continue_acquire,
        "import-run": _import_run,
        "render-summary": _render_summary,
        "prepare-analysis": _prepare_analysis,
        "publish-analysis": _publish_analysis,
        "prepare-generation": _prepare_generation,
        "publish-generation": _publish_generation,
        "prepare-rewrite": _prepare_rewrite,
        "publish-rewrite": _publish_rewrite,
        "verify": _verify,
    }
    return handlers[args.command](args)


def _safe_error(exc: Exception) -> str:
    if type(exc).__name__ == "ValidationError":
        return "input does not match the required schema"
    message = str(exc)
    message = re.sub(r"(?i)(token|secret|password|authorization)\s*[:=]\s*[^,;\s]+", r"\1=[redacted]", message)
    return re.sub(r"(?i)(['\"](?:token|secret|password|authorization)['\"]\s*:\s*['\"])[^'\"]+(['\"])", r"\1[redacted]\2", message)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _dispatch(args)
        print(json.dumps(payload, ensure_ascii=False))
        return 2 if payload.get("status") == "rpaPaused" else 0
    except RpaPausedError as exc:
        print(json.dumps({"status": "rpaPaused", "errorCode": exc.error_code,
                          "message": _safe_error(exc), "firstBatchCsvGate": exc.gate}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "errorCode": getattr(exc, "error_code", type(exc).__name__), "error": _safe_error(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RuntimeContext", "analysis_path", "build_parser", "main", "run_path", "validate_identity"]
