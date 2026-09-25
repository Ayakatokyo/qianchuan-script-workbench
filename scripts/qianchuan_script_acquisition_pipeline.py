"""Wave-coordinated, evidence-preserving Qianchuan script acquisition."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from threading import Lock
from typing import Any

from qianchuan_script_acquisition_identity import audit_identity
from qianchuan_script_acquisition_contracts import AcquisitionRequest
from qianchuan_script_acquisition_fact_pack import build_source_pack, extract_script_content, normalize_text, script_completeness
from qianchuan_script_acquisition_field_registry import FieldRegistry, load_field_registry
from qianchuan_script_acquisition_csv_parser import parse_diagnosis_csv
from qianchuan_script_acquisition_receipt import atomic_json, write_receipt, write_status
from qianchuan_script_acquisition_report_client import (
    ReportClientError,
    acquisition_scope_fingerprint,
    load_material_report_snapshot,
    report_query_fingerprint,
    write_material_report_snapshot,
)
from qianchuan_script_acquisition_rpa_client import (
    RpaAuthorizationError,
    RpaClientError,
    RpaContractError,
    RpaGateway,
    RpaTaskError,
    RpaTaskResult,
    invoke_once,
)
from qianchuan_script_acquisition_selection import MaterialSelection, QueryError, select_materials_with_audit

RPA_MAX_CONCURRENCY = 3
OUTCOMES_FILENAME = "acquisition-results.json"
REPORT_SNAPSHOT_PATH = "source-data/material-report-snapshot.json"
REPORT_RECEIPT_FILENAME = "report-query-receipt.json"
SELECTION_FILENAME = "material-selection.json"
SELECTION_PENDING_FILENAME = "selection-pending.json"


def _default_registry() -> FieldRegistry:
    script_path = Path(__file__).resolve()
    candidates = (
        script_path.parents[1] / "config" / "asset-field-registry-v1.json",
        script_path.parents[3] / "config" / "asset-field-registry-v1.json",
    )
    for path in candidates:
        if path.is_file():
            return load_field_registry(path)
    raise FileNotFoundError("Qianchuan field registry is missing from the Skill package")


def _report_snapshot_info(output_dir: Path) -> tuple[dict[str, Any], str]:
    snapshot_path = Path(output_dir) / REPORT_SNAPSHOT_PATH
    if not snapshot_path.is_file():
        raise ReportClientError("complete material report snapshot is missing")
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReportClientError("material report snapshot must be an object")
    digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    return payload, digest


def _write_report_query_receipt(output_dir: Path, request: AcquisitionRequest) -> dict[str, Any]:
    snapshot, digest = _report_snapshot_info(output_dir)
    payload = {
        "schemaVersion": 1,
        "runId": Path(output_dir).name,
        "status": "completed",
        "snapshotPath": REPORT_SNAPSHOT_PATH,
        "snapshotSha256": digest,
        "rowsSha256": snapshot["rowsSha256"],
        "recordCount": snapshot["recordCount"],
        "queryFingerprint": report_query_fingerprint(request),
        "scopeFingerprint": acquisition_scope_fingerprint(request),
    }
    atomic_json(Path(output_dir) / REPORT_RECEIPT_FILENAME, payload)
    return payload


def inspect_pending_report(request: AcquisitionRequest, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify a report-only run before local selection is resumed."""
    output_dir = Path(output_dir).resolve()
    if request.live_acquire is None:
        raise ValueError("continue_acquire_scripts requires liveAcquire")
    try:
        status = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))
        receipt = json.loads((output_dir / REPORT_RECEIPT_FILENAME).read_text(encoding="utf-8"))
        acquisition_receipt = json.loads((output_dir / "acquisition-receipt.json").read_text(encoding="utf-8"))
        pending = json.loads((output_dir / SELECTION_PENDING_FILENAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportClientError("awaiting-selection run evidence is missing or unreadable") from exc
    if not all(isinstance(item, dict) for item in (status, receipt, acquisition_receipt, pending)):
        raise ReportClientError("awaiting-selection run evidence must contain JSON objects")
    if status.get("state") != "awaitingSelection" or receipt.get("status") != "completed":
        raise ReportClientError("run is not awaiting material selection")
    if receipt.get("runId") != output_dir.name or receipt.get("snapshotPath") != REPORT_SNAPSHOT_PATH:
        raise ReportClientError("report receipt does not match the requested run")
    if (
        acquisition_receipt.get("runId") != output_dir.name
        or acquisition_receipt.get("status") != "awaitingSelection"
        or acquisition_receipt.get("counts") != {"requested": 0, "available": 0, "missing": 0, "failed": 0}
        or pending.get("runId") != output_dir.name
        or pending.get("status") != "awaitingSelection"
        or pending.get("reportSnapshot") != REPORT_SNAPSHOT_PATH
    ):
        raise ReportClientError("selection-pending receipt does not match the requested run")
    if receipt.get("queryFingerprint") != report_query_fingerprint(request):
        raise ReportClientError("continuation request changes the report query scope")
    if receipt.get("scopeFingerprint") != acquisition_scope_fingerprint(request):
        raise ReportClientError("continuation request changes the acquisition scope")
    if (output_dir / OUTCOMES_FILENAME).exists() or (output_dir / "facts/qianchuan-script-source-pack.json").exists():
        raise ReportClientError("RPA or source-pack output already exists; this report cannot be replayed")
    if any(
        path.is_file()
        for folder_name in ("attempts", "tasks", "rpa")
        for path in (output_dir / "source-data" / folder_name).rglob("*")
    ):
        raise ReportClientError("RPA evidence already exists; this report cannot be replayed")
    rows, digest = load_material_report_snapshot(output_dir / REPORT_SNAPSHOT_PATH, request)
    snapshot, _ = _report_snapshot_info(output_dir)
    if (
        receipt.get("snapshotSha256") != digest
        or receipt.get("rowsSha256") != snapshot.get("rowsSha256")
        or receipt.get("recordCount") != len(rows)
        or status.get("reportSnapshotSha256") != digest
        or pending.get("reportSnapshotSha256") != digest
        or pending.get("reportRowCount") != len(rows)
    ):
        raise ReportClientError("saved report or selection-pending receipt does not match the snapshot")
    return rows, receipt


def _available_sort_fields(registry: FieldRegistry) -> list[dict[str, str]]:
    return [
        {"fieldId": entry["id"], "label": entry["label"]}
        for entry in registry.entries()
        if entry.get("kind") == "metric" and entry.get("sortable") is True
    ]


def _write_selection_pending(
    output_dir: Path,
    request: AcquisitionRequest,
    registry: FieldRegistry,
    error_code: str,
    message: str,
    selection: MaterialSelection | None = None,
) -> Path:
    snapshot, snapshot_digest = _report_snapshot_info(output_dir)
    payload = {
        "schemaVersion": 1,
        "runId": Path(output_dir).name,
        "status": "awaitingSelection",
        "errorCode": error_code,
        "message": message,
        "requestedSelection": request.live_acquire.material_filter_sort if request.live_acquire else {},
        "availableSortFields": _available_sort_fields(registry),
        "reportSnapshot": REPORT_SNAPSHOT_PATH,
        "reportSnapshotSha256": snapshot_digest,
        "reportRowCount": snapshot["recordCount"],
        "excludedRows": list(selection.excluded_rows) if selection else [],
    }
    pending_path = Path(output_dir) / SELECTION_PENDING_FILENAME
    atomic_json(pending_path, payload)
    write_status(
        output_dir,
        "awaitingSelection",
        errorCode=error_code,
        reportSnapshot=REPORT_SNAPSHOT_PATH,
        reportSnapshotSha256=snapshot_digest,
        recordCount=snapshot["recordCount"],
        availableSortFields=payload["availableSortFields"],
    )
    outputs = [REPORT_SNAPSHOT_PATH, REPORT_RECEIPT_FILENAME, SELECTION_PENDING_FILENAME, "status.json"]
    if selection is not None:
        outputs.append(SELECTION_FILENAME)
    write_receipt(
        output_dir,
        {
            "schemaVersion": 1,
            "runId": Path(output_dir).name,
            "status": "awaitingSelection",
            "counts": {"requested": 0, "available": 0, "missing": 0, "failed": 0},
            "outputs": outputs,
        },
    )
    return Path(output_dir) / REPORT_SNAPSHOT_PATH


def _materials(report_gateway: Any, request: AcquisitionRequest, output_dir: Path) -> list[Any]:
    if hasattr(report_gateway, "fetch_material_report"):
        value = report_gateway.fetch_material_report(request, output_dir / "source-data")
    elif callable(report_gateway):
        value = report_gateway(request)
    else:
        value = report_gateway
    if isinstance(value, dict) and isinstance(value.get("materials"), list):
        value = value["materials"]
    if not isinstance(value, list):
        raise ValueError("report gateway must return a material list")
    return list(value)


def _material_id(material: Any) -> str:
    if isinstance(material, dict):
        return str(material.get("materialId") or material.get("material_id") or "").strip()
    return str(getattr(material, "material_id", "")).strip()


def _material_rank(material: Any, default: int) -> int:
    if isinstance(material, dict):
        return int(material.get("rank") or default)
    return int(getattr(material, "rank", default))


def _material_key(material_id: str) -> str:
    return hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:16]


def _attempt_path(output_dir: Path, material_id: str, attempt: int) -> Path:
    return Path(output_dir) / "source-data" / "attempts" / f"{_material_key(material_id)}-attempt-{attempt:02d}.json"


def _update_attempt(path: Path, **changes: Any) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(changes)
    atomic_json(path, record)
    return record


def _relative_path(path: Path, output_dir: Path) -> str:
    return Path(path).resolve().relative_to(Path(output_dir).resolve()).as_posix()


def _combined_payload_hash(payload_files: list[dict[str, str]]) -> str | None:
    if not payload_files:
        return None
    canonical = json.dumps(
        [{"path": item["path"], "sha256": item["sha256"]} for item in payload_files],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _record_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    return {
        **dict(getattr(record, "raw", {}) or {}),
        "recordType": getattr(record, "record_type", ""),
        "materialId": getattr(record, "material_id", ""),
        "scriptInfo": dict(getattr(record, "script_info", {}) or {}),
        "parseStatus": getattr(record, "parse_status", "parsed"),
        "parseError": getattr(record, "parse_error", None),
        "durationSec": getattr(record, "duration_sec", None),
        "metricValue": getattr(record, "metric_value", None),
        "Dimensions": dict(getattr(record, "dimensions", {}) or {}),
        "Metrics": dict(getattr(record, "metrics", {}) or {}),
        "Fields": dict(getattr(record, "fields", {}) or {}),
    }


def _store_payload_file(path: Path, output_dir: Path, kind: str) -> dict[str, str]:
    if not path.is_file():
        raise ValueError("downloaded RPA payload is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": _relative_path(path, output_dir), "sha256": digest, "kind": kind}


def _task_records(
    result: Any,
    rpa_gateway: Any,
    output_dir: Path,
    material_id: str,
    attempt: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Persist each attempt's returned payload before parsing or identity checks."""
    output_dir = Path(output_dir)
    key = _material_key(material_id)
    attempt_path = _attempt_path(output_dir, material_id, attempt)
    records = [
        _record_payload(record)
        for record in (result.records if isinstance(result, RpaTaskResult) else getattr(result, "records", ()) or ())
    ]
    payload_files: list[dict[str, str]] = []
    if records:
        target = output_dir / "source-data" / "rpa" / f"{key}-attempt-{attempt:02d}.records.json"
        if target.exists():
            raise FileExistsError("RPA attempt payload already exists")
        atomic_json(target, records)
        payload_files.append(_store_payload_file(target, output_dir, "records-json"))
        _update_attempt(
            attempt_path,
            payloadFiles=payload_files,
            payloadSha256=_combined_payload_hash(payload_files),
        )
        return records, payload_files

    files = list(result.files if isinstance(result, RpaTaskResult) else getattr(result, "files", ()) or ())
    records_dir = output_dir / "source-data" / "rpa"
    parsed: list[dict[str, Any]] = []
    for index, file_item in enumerate(files, start=1):
        target = records_dir / f"{key}-attempt-{attempt:02d}-{index}.csv"
        if target.exists():
            raise FileExistsError("RPA attempt payload already exists")
        downloader = getattr(rpa_gateway, "download_csv", None) or RpaGateway().download_csv
        downloaded = Path(downloader(file_item, target))
        if downloaded.resolve() != target.resolve():
            if not downloaded.is_file():
                raise ValueError("downloaded RPA payload is missing")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(downloaded, target)
        payload_files.append(_store_payload_file(target, output_dir, "csv"))
        _update_attempt(
            attempt_path,
            payloadFiles=list(payload_files),
            payloadSha256=_combined_payload_hash(payload_files),
        )
        csv_records = [_record_payload(record) for record in parse_diagnosis_csv(target)]
        records_target = target.with_suffix(".records.json")
        if records_target.exists():
            raise FileExistsError("normalized RPA attempt payload already exists")
        atomic_json(records_target, csv_records)
        payload_files.append(_store_payload_file(records_target, output_dir, "records-json"))
        parsed.extend(csv_records)
        _update_attempt(
            attempt_path,
            payloadFiles=list(payload_files),
            payloadSha256=_combined_payload_hash(payload_files),
        )
    if not files:
        _update_attempt(attempt_path, payloadFiles=[], payloadSha256=None)
    return parsed, payload_files


def _new_attempt_record(material_id: str, attempt: int, output_dir: Path) -> dict[str, Any]:
    path = _attempt_path(output_dir, material_id, attempt)
    task_record_path = Path(output_dir) / "source-data" / "tasks" / f"{_material_key(material_id)}-attempt-{attempt:02d}.json"
    record = {
        "schemaVersion": 1,
        "materialId": material_id,
        "attempt": attempt,
        "attemptRecordPath": _relative_path(path, output_dir),
        "submissionState": "started",
        "phase": "started",
        "taskGroupId": None,
        "taskState": "notStarted",
        "taskRecordPath": None,
        "payloadSha256": None,
        "payloadFiles": [],
        "identityAuditPath": None,
        "identityState": None,
        "mismatchedFields": [],
        "errorCode": None,
    }
    if path.exists() or task_record_path.exists():
        raise FileExistsError("attempt evidence already exists; do not resubmit")
    atomic_json(path, record)
    return record


def _invoke_material(
    material: Any,
    request: AcquisitionRequest,
    detail: dict[str, Any],
    rpa_gateway: Any,
    output_dir: Path,
    attempt: int = 1,
    on_task_submitted: Any = None,
) -> tuple[str, RpaTaskResult]:
    """Persist attempt state before submit and task identity before polling."""
    material_id = _material_id(material)
    attempt_record = _new_attempt_record(material_id, attempt, output_dir)
    attempt_path = Path(output_dir) / attempt_record["attemptRecordPath"]
    task_record_path = Path(output_dir) / "source-data" / "tasks" / f"{_material_key(material_id)}-attempt-{attempt:02d}.json"
    params = {
        "material_id": material_id,
        "date_type": "CUSTOM",
        "custom_start_date": request.period["startDate"],
        "custom_end_date": request.period["endDate"],
    }
    attempt_record.update(phase="submissionPending", submissionState="submitting")
    atomic_json(attempt_path, attempt_record)

    def on_submitted(task_id: str) -> None:
        task_record = {
            "schemaVersion": 1,
            "materialId": material_id,
            "attempt": attempt,
            "taskGroupId": task_id,
        }
        attempt_record.update(
            submissionState="submitted",
            phase="submitted",
            taskGroupId=task_id,
            submittedAt=datetime.now(timezone.utc).isoformat(),
            taskState="running",
            taskRecordPath=_relative_path(task_record_path, output_dir),
        )
        # The task ID is durable before polling begins; retry remains forbidden if
        # this write fails because the existing run directory blocks another acquire.
        atomic_json(attempt_path, attempt_record)
        atomic_json(task_record_path, task_record)
        if on_task_submitted is not None:
            on_task_submitted(material_id, attempt, attempt_record["submittedAt"])

    result = invoke_once(
        rpa_gateway,
        detail,
        request.live_acquire.rpa_shop,
        params,
        timeout_sec=request.live_acquire.timeout_sec,
        on_submitted=on_submitted,
    )
    attempt_record.update(phase="terminal_success", taskState="completed")
    atomic_json(attempt_path, attempt_record)
    return material_id, result


def _script_text(record: dict[str, Any] | None) -> str:
    text = extract_script_content(record).get("text")
    return text if isinstance(text, str) else ""


def _attempt_refs(attempt: dict[str, Any]) -> list[str]:
    refs = [attempt["attemptRecordPath"]]
    if attempt.get("taskRecordPath"):
        refs.append(attempt["taskRecordPath"])
    refs.extend(item["path"] for item in attempt.get("payloadFiles", []))
    if attempt.get("identityAuditPath"):
        refs.append(attempt["identityAuditPath"])
    return refs


def _process_result(
    material: Any,
    result: Any,
    rpa_gateway: Any,
    output_dir: Path,
    attempt_number: int,
    prior_refs: list[str] | None = None,
) -> dict[str, Any]:
    material_id = _material_id(material)
    attempt_path = _attempt_path(output_dir, material_id, attempt_number)
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt.update(phase="terminal_success", taskState="completed")
    atomic_json(attempt_path, attempt)
    try:
        records, _payload_files = _task_records(result, rpa_gateway, output_dir, material_id, attempt_number)
    except Exception:
        attempt = _update_attempt(attempt_path, phase="payload_parse_failed", taskState="completed", errorCode="payload_parse_error")
        return {
            "state": "failed",
            "errorCode": "payload_parse_error",
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": "payload_parse_error", "sourceRefs": _attempt_refs(attempt)},
            "retryEligible": False,
        }

    try:
        identity = audit_identity(material, records)
    except Exception:
        attempt = _update_attempt(attempt_path, phase="identity_audit_failed", taskState="completed", errorCode="identity_audit_error")
        return {
            "state": "failed",
            "errorCode": "identity_audit_error",
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": "identity_audit_error", "sourceRefs": _attempt_refs(attempt)},
            "retryEligible": False,
        }

    identity_path = Path(output_dir) / "source-data" / "identity" / f"{_material_key(material_id)}-attempt-{attempt_number:02d}.json"
    atomic_json(identity_path, identity)
    identity_ref = _relative_path(identity_path, output_dir)
    attempt = _update_attempt(
        attempt_path,
        identityAuditPath=identity_ref,
        identityState=identity["state"],
        mismatchedFields=list(identity.get("mismatchedFields") or []),
        phase="identity_audited",
    )
    refs = list(prior_refs or []) + _attempt_refs(attempt)
    script_records = [record for record in records if str(record.get("recordType") or "") == "script_analysis"]
    if identity["state"] != "matched":
        code = f"material_identity_{identity['state']}"
        return {
            "state": "failed",
            "errorCode": code,
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": code, "sourceRefs": refs},
            "retryEligible": identity["state"] == "mismatch" and attempt_number == 1,
        }
    if len(script_records) > 1:
        code = "ambiguous_script_records"
        attempt = _update_attempt(attempt_path, errorCode=code)
        return {
            "state": "failed",
            "errorCode": code,
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": code, "sourceRefs": refs},
            "retryEligible": False,
        }
    script_record = script_records[0] if script_records else None
    if script_record is None:
        return {
            "state": "submittedWithoutScript",
            "attempt": attempt,
            "scriptFact": {"parseStatus": "missing", "sourceRefs": refs},
            "retryEligible": False,
        }
    if script_record.get("parseStatus") == "failed":
        code = "script_parse_error"
        attempt = _update_attempt(attempt_path, errorCode=code)
        return {
            "state": "failed",
            "errorCode": code,
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": code, "sourceRefs": refs},
            "retryEligible": False,
        }
    content = extract_script_content(script_record)
    text = content["text"] if isinstance(content.get("text"), str) else ""
    completeness = script_completeness(content)
    parse_status = "parsed" if completeness["transcript"] else "missing"
    field_source_refs = {key: list(_attempt_refs(attempt)) for key in ("formula", "detail", "data", "text")}
    material_key = _material_key(material_id)
    script_path = Path(output_dir) / "facts" / "scripts" / f"{material_key}.json"
    if script_path.exists():
        raise FileExistsError("per-material script fact already exists")
    script_payload = {
        "schemaVersion": 1,
        "runId": Path(output_dir).name,
        "materialId": material_id,
        "rank": _material_rank(material, 1),
        "metrics": dict(material.get("metrics") or {}) if isinstance(material, dict) else dict(getattr(material, "metrics", {}) or {}),
        "scriptId": "script:" + hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest(),
        "rawText": text,
        "rawTextSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "normalizedTextSha256": hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest(),
        "formula": content["formula"],
        "detail": content["detail"],
        "data": content["data"],
        "text": content["text"],
        "completeness": completeness,
        "fieldSourceRefs": field_source_refs,
        "parseStatus": parse_status,
        "identityState": identity["state"],
        "selectedAttempt": attempt_number,
        "sourceRefs": refs,
    }
    atomic_json(script_path, script_payload)
    script_file_ref = _relative_path(script_path, output_dir)
    script_file_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()
    return {
        "state": "available" if parse_status == "parsed" else "submittedWithoutScript",
        "attempt": attempt,
        "scriptFact": {
            "parseStatus": parse_status,
            "record": script_record,
            **content,
            "completeness": completeness,
            "fieldSourceRefs": field_source_refs,
            "sourceRefs": refs,
            "materialFile": script_file_ref,
            "materialFileSha256": script_file_hash,
        },
        "retryEligible": False,
    }


def _exception_result(material: Any, output_dir: Path, attempt_number: int, exc: Exception) -> tuple[dict[str, Any], bool]:
    material_id = _material_id(material)
    path = _attempt_path(output_dir, material_id, attempt_number)
    attempt = json.loads(path.read_text(encoding="utf-8"))
    task_id = attempt.get("taskGroupId")
    explicit_terminal_failure = (
        isinstance(exc, RpaTaskError)
        and bool(task_id)
        and str(exc) == f"RPA task failed: {task_id}"
    )
    hard_stop = not explicit_terminal_failure
    if explicit_terminal_failure:
        code, state = "rpa_task_terminal_failure", "failed"
        attempt.update(phase="terminal_failure", taskState="failed", errorCode=code)
    elif isinstance(exc, RpaAuthorizationError):
        code, state = "rpa_authorization_failed", "failed"
        attempt.update(submissionState="notSubmitted", phase="authorization_failed", taskState="notStarted", errorCode=code)
    elif isinstance(exc, RpaContractError):
        code, state = "rpa_contract_error", "failed"
        attempt.update(submissionState="notSubmitted", phase="contract_failed", taskState="notStarted", errorCode=code)
    elif attempt.get("phase") in {"submitting", "submissionPending"} and not task_id:
        code, state = "submission_outcome_unknown", "submissionUnknown"
        attempt.update(submissionState="unknown", taskState="unknown", errorCode=code)
    elif task_id:
        code, state = "rpa_task_state_unknown", "submissionUnknown"
        attempt.update(phase="task_state_unknown", taskState="unknown", errorCode=code)
    else:
        code, state = ("rpa_client_error" if isinstance(exc, RpaClientError) else "acquisition_error"), "failed"
        attempt.update(submissionState="notSubmitted", taskState="notStarted", errorCode=code)
    atomic_json(path, attempt)
    return (
        {
            "state": state,
            "errorCode": code,
            "attempt": attempt,
            "scriptFact": {"parseStatus": "failed", "error": code, "sourceRefs": _attempt_refs(attempt)},
            "retryEligible": False,
        },
        hard_stop,
    )


def _outcome_summary(outcomes: list[dict[str, Any]], run_id: str, status: str, stop_reason: str | None) -> dict[str, Any]:
    counts = {
        "requested": len(outcomes),
        "taskSubmissions": 0,
        "available": 0,
        "submittedWithoutScript": 0,
        "failed": 0,
        "submissionUnknown": 0,
        "unsubmitted": 0,
    }
    for item in outcomes:
        counts[item["state"]] += 1
        counts["taskSubmissions"] += sum(bool(attempt.get("taskGroupId")) for attempt in item["attempts"])
    result = {"schemaVersion": 1, "runId": run_id, "status": status, "counts": counts, "materials": outcomes}
    if stop_reason:
        result["stopReason"] = stop_reason
    return result


def acquire_scripts(
    request: AcquisitionRequest,
    output_dir: Path,
    report_gateway: Any,
    rpa_gateway: Any,
    registry: FieldRegistry | None = None,
    *,
    resume_from_report: bool = False,
) -> Path:
    if request.live_acquire is None:
        raise ValueError("acquire_scripts requires liveAcquire")
    output_dir = Path(output_dir)
    result_path = output_dir / "facts" / "qianchuan-script-source-pack.json"
    if result_path.is_file():
        return result_path
    registry = registry or _default_registry()
    status_path = output_dir / "status.json"
    if status_path.exists():
        if not resume_from_report:
            raise ValueError("incomplete_run_requires_read_only_recovery; do not resubmit")
        raw_materials, report_receipt = inspect_pending_report(request, output_dir)
    else:
        if resume_from_report:
            raise ReportClientError("cannot continue selection without an awaiting-selection run")
        output_dir.mkdir(parents=True, exist_ok=True)
        write_status(output_dir, "querying")
        try:
            raw_materials = _materials(report_gateway, request, output_dir)
            snapshot_path, snapshot_digest = write_material_report_snapshot(
                raw_materials,
                request,
                output_dir / "source-data",
            )
            if snapshot_path != output_dir / REPORT_SNAPSHOT_PATH:
                raise ReportClientError("material report snapshot path is inconsistent")
            report_receipt = _write_report_query_receipt(output_dir, request)
            if report_receipt["snapshotSha256"] != snapshot_digest:
                raise ReportClientError("material report snapshot changed while being recorded")
        except Exception:
            write_status(output_dir, "failed", errorCode="report_failed")
            raise

    try:
        selection = select_materials_with_audit(raw_materials, request, registry)
    except QueryError as exc:
        return _write_selection_pending(
            output_dir,
            request,
            registry,
            "selection_requires_confirmation",
            str(exc),
        )

    selection_payload = selection.to_dict()
    selection_payload["reportSnapshot"] = REPORT_SNAPSHOT_PATH
    selection_payload["reportSnapshotSha256"] = report_receipt["snapshotSha256"]
    atomic_json(output_dir / SELECTION_FILENAME, selection_payload)
    if selection.systemic_error:
        return _write_selection_pending(
            output_dir,
            request,
            registry,
            "selection_metric_unavailable",
            selection.systemic_error,
            selection,
        )
    if resume_from_report:
        atomic_json(
            output_dir / "selection-resolution.json",
            {
                "schemaVersion": 1,
                "runId": output_dir.name,
                "status": "resolved",
                "previousPendingSelection": SELECTION_PENDING_FILENAME,
                "selectionAudit": SELECTION_FILENAME,
                "reportSnapshot": REPORT_SNAPSHOT_PATH,
                "reportSnapshotSha256": report_receipt["snapshotSha256"],
            },
        )
    materials = list(selection.candidates)
    materials = sorted(materials, key=lambda item: (_material_rank(item, 10**9), _material_id(item)))
    selected_materials = materials[: request.live_acquire.top_n]
    outcomes = [
        {"materialId": _material_id(material), "rank": _material_rank(material, index + 1), "state": "unsubmitted", "attempts": []}
        for index, material in enumerate(selected_materials)
    ]
    outcome_by_id = {item["materialId"]: item for item in outcomes}
    script_facts: dict[str, dict[str, Any]] = {}
    hard_stop = False
    stop_reason: str | None = None

    if selected_materials:
        try:
            detail = rpa_gateway.connector_detail()
        except Exception as exc:
            hard_stop = True
            stop_reason = "rpa_connector_unavailable" if isinstance(exc, RpaClientError) else "rpa_configuration_error"
            detail = None
    else:
        detail = None

    scheduler_events: list[dict[str, Any]] = []
    task_queue: list[tuple[Any, int, list[str]]] = [(item, 1, []) for item in selected_materials]
    active: dict[Any, tuple[Any, int, list[str]]] = {}
    submitted_count = 0
    active_count = 0
    scheduler_lock = Lock()
    if detail is not None:
        with ThreadPoolExecutor(max_workers=RPA_MAX_CONCURRENCY) as executor:
            while task_queue or active:
                while task_queue and len(active) < RPA_MAX_CONCURRENCY and not hard_stop:
                    material, attempt_number, prior_refs = task_queue.pop(0)
                    material_id = _material_id(material)
                    if not material_id:
                        continue
                    def record_submission(submitted_material_id: str, submitted_attempt: int, submitted_at: str) -> None:
                        nonlocal submitted_count
                        with scheduler_lock:
                            submitted_count += 1
                            scheduler_events.append({
                                "materialId": submitted_material_id,
                                "attempt": submitted_attempt,
                                "submittedAt": submitted_at,
                                "inFlight": active_count,
                                "queued": len(task_queue),
                                "reason": "identity_mismatch_retry" if submitted_attempt == 2 else "initial_queue",
                            })
                    with scheduler_lock:
                        active_count += 1
                    future = executor.submit(
                        _invoke_material, material, request, detail, rpa_gateway, output_dir, attempt_number,
                        record_submission,
                    )
                    active[future] = (material, attempt_number, prior_refs)
                    write_status(
                        output_dir, "rpaProcessing", currentMaterialId=material_id,
                        maxConcurrency=RPA_MAX_CONCURRENCY, inFlight=len(active), queued=len(task_queue),
                    )
                if not active:
                    break
                done, _pending = wait(active, return_when=FIRST_COMPLETED)
                # Persist and process every currently completed task before filling slots.
                for future in done:
                    material, attempt_number, prior_refs = active.pop(future)
                    with scheduler_lock:
                        active_count -= 1
                    material_id = _material_id(material)
                    outcome = outcome_by_id[material_id]
                    try:
                        _, result = future.result()
                    except Exception as exc:
                        processed, stop = _exception_result(material, output_dir, attempt_number, exc)
                        hard_stop = hard_stop or stop
                        if stop:
                            stop_reason = stop_reason or processed["errorCode"]
                    else:
                        try:
                            processed = _process_result(
                                material, result, rpa_gateway, output_dir, attempt_number,
                                prior_refs=prior_refs,
                            )
                        except Exception:
                            attempt_path = _attempt_path(output_dir, material_id, attempt_number)
                            attempt = _update_attempt(
                                attempt_path, errorCode="result_processing_error", phase="result_processing_failed"
                            )
                            processed = {
                                "state": "failed", "errorCode": "result_processing_error", "attempt": attempt,
                                "scriptFact": {"parseStatus": "failed", "error": "result_processing_error", "sourceRefs": _attempt_refs(attempt)},
                                "retryEligible": False,
                            }
                    outcome["state"] = processed["state"]
                    if processed.get("errorCode"):
                        outcome["errorCode"] = processed["errorCode"]
                    elif attempt_number > 1:
                        outcome.pop("errorCode", None)
                    attempts = list(outcome.get("attempts", []))
                    attempt_path = _attempt_path(output_dir, material_id, attempt_number)
                    current_attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
                    if attempt_number == 1:
                        attempts = [current_attempt]
                    else:
                        attempts.append(current_attempt)
                    outcome["attempts"] = attempts
                    script_facts[material_id] = processed["scriptFact"]
                    if processed.get("retryEligible") and not hard_stop:
                        task_queue.append((material, 2, _attempt_refs(processed["attempt"])))
                    elif processed.get("retryEligible"):
                        outcome["retrySuppressedReason"] = "global_hard_stop"
                    write_status(
                        output_dir, "rpaProcessing", currentMaterialId=material_id,
                        maxConcurrency=RPA_MAX_CONCURRENCY, inFlight=active_count, queued=len(task_queue),
                    )
                if hard_stop:
                    # The active tasks are drained, but no queued first attempts or retries are started.
                    while task_queue:
                        material, attempt_number, _prior_refs = task_queue.pop(0)
                        if attempt_number == 1:
                            continue
                        outcome = outcome_by_id[_material_id(material)]
                        outcome["retrySuppressedReason"] = "global_hard_stop"
                        outcome["state"] = "failed"
                        outcome["errorCode"] = outcome.get("errorCode", "retry_suppressed")
        if hard_stop:
            underfill_reason = "hard_stop"
        else:
            underfill_reason = "remaining_queue_exhausted" if submitted_count % RPA_MAX_CONCURRENCY else "none"
    else:
        underfill_reason = stop_reason or ("no_selected_materials" if not selected_materials else "connector_unavailable")

    for material in selected_materials:
        material_id = _material_id(material)
        if outcome_by_id[material_id]["state"] == "unsubmitted":
            script_facts[material_id] = {"parseStatus": "missing", "sourceRefs": []}

    source_selection = {
        "runId": output_dir.name,
        "rankingField": selection.query.sort_entry["id"],
        "rankingLabel": selection.query.sort_entry["label"],
        "direction": selection.query.direction,
        "filters": selection_payload["filters"],
        "topN": request.live_acquire.top_n,
        "reportRowCount": selection.report_row_count,
        "filteredOutCount": selection.filtered_out_count,
        "matchingRowCount": selection.matching_row_count,
        "rankableRowCount": selection.rankable_row_count,
        "selectedMaterialIds": selection_payload["selectedMaterialIds"],
        "excludedRows": list(selection.excluded_rows),
        "reportSnapshotPath": REPORT_SNAPSHOT_PATH,
        "reportSnapshotSha256": report_receipt["snapshotSha256"],
        "selectionAuditPath": SELECTION_FILENAME,
    }
    write_status(output_dir, "sourcePackBuilding")
    pack = build_source_pack(selected_materials, script_facts, request.period, source_selection, ["material-report", "rpa-diagnosis", OUTCOMES_FILENAME, REPORT_SNAPSHOT_PATH, SELECTION_FILENAME])
    atomic_json(result_path, pack)

    failed_or_unsafe = any(item["state"] in {"failed", "submissionUnknown", "unsubmitted"} for item in outcomes)
    state = "partialFailed" if failed_or_unsafe else "ready"
    outcome_payload = _outcome_summary(outcomes, output_dir.name, state, stop_reason)
    outcome_payload["scheduler"] = {
        "maxConcurrency": RPA_MAX_CONCURRENCY,
        "submittedTaskCount": submitted_count,
        "events": scheduler_events,
        "underfillReason": underfill_reason,
        "hardStopObserved": hard_stop,
    }
    outcomes_path = output_dir / OUTCOMES_FILENAME
    atomic_json(outcomes_path, outcome_payload)
    write_status(
        output_dir,
        state,
        runId=pack["runId"],
        availability=pack["availability"],
        reportSnapshot=REPORT_SNAPSHOT_PATH,
        reportSnapshotSha256=report_receipt["snapshotSha256"],
        recordCount=report_receipt["recordCount"],
    )
    write_receipt(
        output_dir,
        {
            "schemaVersion": 1,
            "runId": pack["runId"],
            "status": state,
            "counts": pack["availability"],
            "outputs": [
                "facts/qianchuan-script-source-pack.json",
                *sorted({fact["materialFile"] for fact in script_facts.values() if fact.get("materialFile")}),
                "status.json",
                OUTCOMES_FILENAME,
                REPORT_RECEIPT_FILENAME,
                REPORT_SNAPSHOT_PATH,
                SELECTION_FILENAME,
            ],
        },
    )
    return result_path


def continue_acquire_scripts(
    request: AcquisitionRequest,
    output_dir: Path,
    rpa_gateway: Any,
    registry: FieldRegistry | None = None,
) -> Path:
    """Resume local selection and RPA from a verified, already-saved report."""
    return acquire_scripts(
        request,
        output_dir,
        report_gateway=None,
        rpa_gateway=rpa_gateway,
        registry=registry,
        resume_from_report=True,
    )


__all__ = [
    "RPA_MAX_CONCURRENCY",
    "OUTCOMES_FILENAME",
    "REPORT_SNAPSHOT_PATH",
    "SELECTION_FILENAME",
    "_invoke_material",
    "acquire_scripts",
    "continue_acquire_scripts",
    "inspect_pending_report",
]
