"""Read-only phase-one summary projection for a verified Qianchuan run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from qianchuan_script_acquisition_receipt import atomic_json
from script_creation_contracts import validate_payload


class WorkbenchError(ValueError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkbenchError("invalid_json", f"unable to read {path.name}") from exc
    if not isinstance(payload, dict):
        raise WorkbenchError("invalid_json", f"{path.name} must contain an object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            if not value.endswith("\n"):
                handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _script_map(pack: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("materialId")): dict(item) for item in pack.get("scripts", []) if isinstance(item, Mapping)}


def _result_map(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "acquisition-results.json"
    if not path.is_file():
        return {}
    payload = _read_json(path)
    return {str(item.get("materialId")): dict(item) for item in payload.get("materials", []) if isinstance(item, Mapping)}


def _field_registry() -> dict[str, dict[str, Any]]:
    candidates = [ancestor / "config" / "asset-field-registry-v1.json" for ancestor in Path(__file__).resolve().parents]
    for path in candidates:
        if path.is_file():
            payload = _read_json(path)
            return {str(item["id"]): dict(item) for item in payload.get("fields", []) if isinstance(item, Mapping) and item.get("kind") == "metric"}
    return {}


def _source_ref_label(value: Any) -> str:
    if isinstance(value, Mapping):
        path = str(value.get("path") or "")
        digest = str(value.get("sha256") or "")
        if path and digest:
            return f"`{path}` (sha256 `{digest[:12]}`)"
        return "`" + json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "`"
    return f"`{str(value)}`"


def _selection_summary(pack: Mapping[str, Any]) -> dict[str, Any]:
    selection = dict(pack.get("selection") or {})
    ranking_field = str(selection.get("rankingField") or "")
    registry = _field_registry()
    definition = registry.get(ranking_field) or next((item for item in registry.values() if item.get("label") == ranking_field), None)
    return {
        "rankingField": ranking_field,
        "rankingLabel": selection.get("rankingLabel") or (definition or {}).get("label") or ranking_field,
        "rankingMetric": {
            "fieldId": (definition or {}).get("id") or (ranking_field or None),
            "label": selection.get("rankingLabel") or (definition or {}).get("label") or (ranking_field or None),
            "sourceKey": (definition or {}).get("sourceKey") or (ranking_field or None),
            "unit": (definition or {}).get("unit"),
            "definitionAvailable": definition is not None,
        },
        "direction": selection.get("direction") if ranking_field else None,
        "filters": selection.get("filters") or [],
        "topN": selection.get("topN"),
        "reportRowCount": selection.get("reportRowCount"),
        "filteredOutCount": selection.get("filteredOutCount"),
        "matchingRowCount": selection.get("matchingRowCount"),
        "rankableRowCount": selection.get("rankableRowCount"),
    }


def _delivery_details(run_dir: Path, script: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Keep rejected payload evidence separate from accepted script facts."""
    error = outcome.get("errorCode") or script.get("error")
    state = outcome.get("state")
    if error in {"material_identity_mismatch", "material_identity_unverified"}:
        delivery = "identityMismatch" if error.endswith("mismatch") else "identityUnverified"
    elif state in {"submissionUnknown", "unsubmitted"}:
        delivery = state
    elif script.get("parseStatus") == "parsed" and _nonempty(script.get("rawText")):
        delivery = "available"
    elif script.get("parseStatus") == "failed" or state == "failed":
        delivery = "failed"
    else:
        delivery = "missing"
    evidence = []
    for attempt in outcome.get("attempts") or []:
        ref = attempt.get("identityAuditPath")
        audit = {}
        if ref:
            path = (run_dir / ref).resolve()
            if not path.is_relative_to(run_dir):
                raise WorkbenchError("invalid_identity_path", "identity evidence must remain inside the run")
            audit = _read_json(path)
        evidence.append({
            "attempt": attempt.get("attempt"), "identityState": attempt.get("identityState"),
            "auditPath": ref, "expected": audit.get("expected", {}), "observed": audit.get("observed", {}),
            "mismatchedFields": audit.get("mismatchedFields", []),
            "scriptContentPresent": attempt.get("scriptContentPresent"),
            "scriptContentSha256": attempt.get("scriptContentSha256"),
            "observedIdentitySha256": attempt.get("observedIdentitySha256"),
        })
    presence = [item["scriptContentPresent"] for item in evidence]
    returned = True if True in presence else (False if presence and all(value is False for value in presence) else None)
    if delivery == "available":
        returned = True
    labels = {
        "available": "已核验，可用", "missing": "平台未返回可用正文", "failed": "采集或解析失败",
        "submissionUnknown": "任务状态未确认", "unsubmitted": "未提交采集",
        "identityMismatch": "已返回脚本内容，但素材身份不一致，未采信" if returned else "返回内容身份不一致，未采信",
        "identityUnverified": "返回内容缺少独立身份依据，未采信",
    }
    return {"deliveryStatus": delivery, "statusLabel": labels[delivery],
            "returnedContentPresent": returned, "identityEvidence": evidence,
            "recoveredAfterMismatch": delivery == "available" and any(item["identityState"] == "mismatch" for item in evidence)}


def build_summary(run_dir: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    run_dir = Path(run_dir).expanduser().resolve()
    status = _read_json(run_dir / "status.json")
    acquisition_state = status.get("state") or status.get("status")
    if acquisition_state not in {"ready", "partialFailed"}:
        raise WorkbenchError("run_not_ready", "phase-one summary requires a ready or partialFailed acquisition")
    source_pack_path = run_dir / "facts" / "qianchuan-script-source-pack.json"
    if not source_pack_path.is_file():
        raise WorkbenchError("source_pack_missing", "verified Qianchuan script source pack is missing")
    pack = _read_json(source_pack_path)
    validate_payload(pack, "qianchuan-script-source-pack.schema.json")
    if pack.get("runId") != run_dir.name or status.get("runId") != run_dir.name:
        raise WorkbenchError("identity_mismatch", "runId differs across the status, path and source pack")

    source_pack_sha = _sha256(source_pack_path)
    scripts = _script_map(pack)
    outcomes = _result_map(run_dir)
    materials: list[dict[str, Any]] = []
    available_fields = {name: [] for name in ("formula", "detail", "data", "text")}
    field_counts = {name: {"available": 0, "missing": 0} for name in available_fields}
    failure_gaps: list[dict[str, Any]] = []
    for material in pack.get("materials", []):
        material_id = str(material.get("materialId") or "")
        script = scripts.get(material_id, {})
        outcome = outcomes.get(material_id, {})
        delivery = _delivery_details(run_dir, script, outcome)
        completeness = script.get("completeness") if isinstance(script.get("completeness"), Mapping) else {}
        text_available = script.get("parseStatus") == "parsed" and _nonempty(script.get("rawText"))
        field_available: dict[str, bool] = {}
        for field in available_fields:
            if field == "text":
                has_field = text_available
            else:
                has_field = bool(completeness.get({"formula": "formulaLabels", "detail": "detailLabels", "data": "structuredData"}[field])) and _nonempty(script.get(field))
            field_available[field] = has_field
            field_counts[field]["available" if has_field else "missing"] += 1
            if has_field:
                available_fields[field].append(material_id)
        metric_values = dict(material.get("metrics") or {})
        materials.append({
            "materialId": material_id,
            "rank": material.get("rank"),
            "metrics": metric_values,
            "sourceRefs": list(material.get("sourceRefs") or []),
            "script": {
                **delivery,
                "scriptId": script.get("scriptId"),
                "parseStatus": script.get("parseStatus", "missing"),
                "textAvailable": text_available,
                "fieldAvailability": field_available,
                "textExcerpt": (str(script.get("rawText") or "").strip()[:260] + ("…" if len(str(script.get("rawText") or "").strip()) > 260 else "")) if text_available else None,
                "materialFactPath": script.get("materialFile"),
                "sourceRefs": list(script.get("sourceRefs") or []),
            },
            "acquisitionOutcome": outcome.get("state"),
            "errorCode": outcome.get("errorCode"),
        })
        if outcome and outcome.get("state") in {"failed", "submissionUnknown", "unsubmitted", "submittedWithoutScript"}:
            failure_gaps.append({"materialId": material_id, "state": outcome.get("state"), "errorCode": outcome.get("errorCode"), "deliveryStatus": delivery["deliveryStatus"], "message": delivery["statusLabel"]})
        elif script.get("parseStatus") in {"missing", "failed"}:
            failure_gaps.append({"materialId": material_id, "state": "scriptMissing" if script.get("parseStatus") == "missing" else "scriptFailed", "errorCode": script.get("error")})
    materials.sort(key=lambda item: (item.get("rank") or 0, item["materialId"]))

    availability = dict(pack.get("availability") or {})
    count_by_outcome = {state: 0 for state in ("available", "submittedWithoutScript", "failed", "submissionUnknown", "unsubmitted")}
    for outcome in outcomes.values():
        state = outcome.get("state")
        if state in count_by_outcome:
            count_by_outcome[state] += 1
    selection = _selection_summary(pack)
    duplicate_groups = [
        group for group in ((pack.get("deduplication") or {}).get("groups") or [])
        if len(group.get("materialIds") or group.get("materials") or []) > 1
    ]
    summary = {
        "schemaVersion": 1,
        "runId": run_dir.name,
        "acquisitionState": acquisition_state,
        "period": dict(pack.get("period") or {}),
        "selection": selection,
        "counts": {
            "reportRows": selection.get("reportRowCount"),
            "selectedMaterials": len(pack.get("materials", [])),
            "requestedScripts": availability.get("requested", len(pack.get("scripts", []))),
            "availableScripts": sum(1 for item in scripts.values() if item.get("parseStatus") == "parsed" and _nonempty(item.get("rawText"))),
            "missingScripts": sum(1 for item in scripts.values() if item.get("parseStatus") == "missing"),
            "failedScripts": sum(1 for item in scripts.values() if item.get("parseStatus") == "failed"),
            "submittedWithoutScript": count_by_outcome["submittedWithoutScript"],
            "submissionUnknown": count_by_outcome["submissionUnknown"],
            "unsubmitted": count_by_outcome["unsubmitted"],
            "failedMaterials": count_by_outcome["failed"],
            "identityMismatchScripts": sum(item["script"]["deliveryStatus"] == "identityMismatch" for item in materials),
            "identityRecoveredScripts": sum(item["script"]["recoveredAfterMismatch"] for item in materials),
        },
        "fieldAvailability": field_counts,
        "materials": materials,
        "duplicateTextGroups": duplicate_groups,
        "gaps": failure_gaps,
        "sourcePack": {"path": "facts/qianchuan-script-source-pack.json", "sha256": source_pack_sha},
    }
    report = render_markdown(summary)
    handoff = {
        "schemaVersion": 1,
        "runId": run_dir.name,
        "workflowState": "awaitingAnalysisInput",
        "acquisitionState": acquisition_state,
        "sourcePack": {"path": "facts/qianchuan-script-source-pack.json", "sha256": source_pack_sha},
        "summary": {"path": "overview/summary-data.json", "sha256": None},
        "report": {"path": "overview/report.md", "sha256": None},
        "period": dict(pack.get("period") or {}),
        "selection": selection,
        "materialIds": [item["materialId"] for item in materials],
        "availableScriptMaterialIds": [item["materialId"] for item in materials if item["script"]["textAvailable"]],
        "fieldAvailability": field_counts,
        "availableFields": [name for name, value in field_counts.items() if value["available"] > 0],
        "gaps": failure_gaps,
        "analysisAllowed": any(item["script"]["textAvailable"] for item in materials),
    }
    return summary, report, handoff


def render_markdown(summary: Mapping[str, Any]) -> str:
    counts = summary["counts"]
    selection = summary["selection"]
    lines = [
        f"# 千川素材脚本数据汇总 · {summary['runId']}",
        "",
        f"- 取数状态：`{summary['acquisitionState']}`",
        f"- 周期：{summary['period'].get('startDate', '未知')} 至 {summary['period'].get('endDate', '未知')}",
        f"- 选材口径：字段 ID `{(selection.get('rankingMetric') or {}).get('fieldId') or '未记录'}`（{(selection.get('rankingMetric') or {}).get('label') or '未记录'}；单位 `{(selection.get('rankingMetric') or {}).get('unit') or '源数据未提供'}`；方向 {selection.get('direction') or '未记录'}）/ TopN={selection.get('topN') or '未记录'}；筛选 `{json.dumps(selection.get('filters') or [], ensure_ascii=False)}`",
        f"- 完整报表行数：{counts.get('reportRows') if counts.get('reportRows') is not None else '未知'}；入选素材：{counts['selectedMaterials']}",
        f"- 脚本文本：可用 {counts['availableScripts']}，缺失 {counts['missingScripts']}，失败 {counts['failedScripts']}",
        f"- 身份核对：不一致且未采信 {counts.get('identityMismatchScripts', 0)}，重试后恢复 {counts.get('identityRecoveredScripts', 0)}；未采信不等于平台没有脚本。",
        f"- 内容公式：可用 {summary['fieldAvailability']['formula']['available']}，缺失 {summary['fieldAvailability']['formula']['missing']}；detail：可用 {summary['fieldAvailability']['detail']['available']}，缺失 {summary['fieldAvailability']['detail']['missing']}；data：可用 {summary['fieldAvailability']['data']['available']}，缺失 {summary['fieldAvailability']['data']['missing']}",
        "",
        "## 素材明细",
        "",
        "排名 | 素材 ID | 所选指标 | 脚本状态 | 结构字段 | 原文摘要/入口",
        "---:|---|---|---|---|---",
    ]
    ranking_field = (selection.get("rankingMetric") or {}).get("sourceKey") or selection.get("rankingField")
    for item in summary["materials"]:
        script = item["script"]
        metric = item["metrics"].get(ranking_field) if ranking_field else None
        text_excerpt = (script.get("textExcerpt") or "").replace("|", "\\|").replace("\n", " ")
        fact_path = script.get("materialFactPath") or summary["sourcePack"]["path"]
        if not str(fact_path).startswith("../"):
            fact_path = "../" + str(fact_path)
        if text_excerpt:
            text_cell = f"{text_excerpt} [{fact_path}]"
        else:
            text_cell = f"{script.get('statusLabel', '未提供')}；[{fact_path}]"
        source_refs = list(item.get("sourceRefs") or []) + list(script.get("sourceRefs") or [])
        source_labels = ", ".join(_source_ref_label(value) for value in source_refs) or "来源未记录"
        text_cell += f"；来源：{source_labels}"
        structure = ", ".join(field for field in ("formula", "detail", "data") if script["fieldAvailability"][field]) or "无"
        if not ranking_field:
            metric_display = "选材指标未记录"
        else:
            metric_display = str(metric) if metric is not None else "该素材指标缺失"
        lines.append(f"{item['rank']} | `{item['materialId']}` | {metric_display} | {script.get('statusLabel', script['parseStatus'])} | {structure} | {text_cell}")
    lines.extend(["", "## 素材身份核对证据", ""])
    for item in summary["materials"]:
        for evidence in item["script"].get("identityEvidence", []):
            if evidence.get("identityState") not in {"mismatch", "unverified"}:
                continue
            lines.append(f"- 素材 `{item['materialId']}` 第 {evidence.get('attempt')} 次：{evidence['identityState']}；不一致字段 `{', '.join(evidence.get('mismatchedFields') or [])}`。")
            lines.append(f"  期望身份：`{json.dumps(evidence.get('expected'), ensure_ascii=False)}`；返回身份：`{json.dumps(evidence.get('observed'), ensure_ascii=False)}`。")
            lines.append(f"  身份核对文件：`{evidence.get('auditPath') or '未记录'}`；脚本内容指纹：`{evidence.get('scriptContentSha256') or '旧记录未提供'}`。原始载荷仅用于核对，不作为该素材脚本事实。")
    lines.extend(["", "## 重复正文", ""])
    groups = summary.get("duplicateTextGroups") or []
    if not groups:
        lines.append("未发现或未提供重复正文分组。")
    else:
        for group in groups:
            ids = group.get("materialIds") or group.get("materials") or []
            lines.append(f"- 正文哈希 `{group.get('normalizedTextSha256') or group.get('textSha256') or '未记录'}`：{', '.join(map(str, ids)) or '素材范围未记录'}")
    lines.extend(["", "## 失败与缺口", ""])
    if summary.get("gaps"):
        for gap in summary["gaps"]:
            lines.append(f"- `{gap['materialId']}`：{gap.get('message') or gap['state']}；错误码 `{gap.get('errorCode') or '未提供'}`")
    else:
        lines.append("未记录失败、未知或未提交素材。")
    lines.extend([
        "",
        "> 本报告只投影已验证的千川事实。指标描述所选日期和口径下的素材表现，不证明脚本写法导致效果。",
        "> 报告生成后工作流暂停；请先描述分析目标和素材范围，再选择分析、生成或改写。",
        "",
    ])
    return "\n".join(lines)


def verify_handoff(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    run_dir = Path(run_dir).expanduser().resolve()
    handoff_path = run_dir / "analysis-handoff.json"
    handoff = _read_json(handoff_path)
    validate_payload(handoff, "analysis-handoff.schema.json")
    if handoff["runId"] != run_dir.name:
        raise WorkbenchError("identity_mismatch", "analysis handoff runId differs from its directory")
    for label in ("sourcePack", "summary", "report"):
        record = handoff[label]
        target = (run_dir / record["path"]).resolve()
        if not target.is_relative_to(run_dir) or not target.is_file() or _sha256(target) != record["sha256"]:
            raise WorkbenchError("handoff_hash_mismatch", f"analysis handoff {label} path or SHA-256 is invalid")
    pack_path = (run_dir / handoff["sourcePack"]["path"]).resolve()
    pack = _read_json(pack_path)
    validate_payload(pack, "qianchuan-script-source-pack.schema.json")
    if pack.get("runId") != handoff["runId"]:
        raise WorkbenchError("identity_mismatch", "handoff source pack has a different runId")
    overview_receipt = _read_json(run_dir / "overview" / "receipt.json")
    validate_payload(overview_receipt, "summary-report-receipt.schema.json")
    if (
        overview_receipt.get("runId") != run_dir.name
        or overview_receipt.get("sourcePackSha256") != handoff["sourcePack"]["sha256"]
        or overview_receipt.get("summarySha256") != handoff["summary"]["sha256"]
        or overview_receipt.get("reportSha256") != handoff["report"]["sha256"]
    ):
        raise WorkbenchError("receipt_mismatch", "summary receipt and handoff differ")
    summary = _read_json(run_dir / handoff["summary"]["path"])
    validate_payload(summary, "summary-data.schema.json")
    if summary.get("runId") != handoff["runId"] or summary.get("sourcePack", {}).get("sha256") != handoff["sourcePack"]["sha256"]:
        raise WorkbenchError("summary_mismatch", "summary data differs from its handoff")
    return handoff, pack, pack_path


def render_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir).expanduser().resolve()
    summary, report, handoff = build_summary(run_dir)
    overview = run_dir / "overview"
    if overview.exists():
        receipt_path = overview / "receipt.json"
        if not receipt_path.is_file():
            raise WorkbenchError("summary_exists", "an incomplete overview already exists; refusing to overwrite it")
        receipt = _read_json(receipt_path)
        if receipt.get("sourcePackSha256") != summary["sourcePack"]["sha256"]:
            raise WorkbenchError("summary_source_mismatch", "overview belongs to a different source pack")
        for record in receipt.get("outputs", []):
            target = (run_dir / record["path"]).resolve()
            if not target.is_relative_to(run_dir) or not target.is_file() or _sha256(target) != record["sha256"]:
                raise WorkbenchError("summary_hash_mismatch", "an existing overview output failed hash verification")
        summary_path, report_path = overview / "summary-data.json", overview / "report.md"
        if not summary_path.is_file() or not report_path.is_file():
            raise WorkbenchError("summary_incomplete", "existing overview is missing a required file")
        handoff["summary"]["sha256"] = _sha256(summary_path)
        handoff["report"]["sha256"] = _sha256(report_path)
        handoff_path = run_dir / "analysis-handoff.json"
        if handoff_path.exists():
            existing, _pack, _path = verify_handoff(run_dir)
            return {"status": "awaitingAnalysisInput", "runId": run_dir.name, "analysisAllowed": existing["analysisAllowed"], "outputPath": str(overview), "handoffPath": str(handoff_path), "idempotent": True}
        atomic_json(handoff_path, handoff)
        atomic_json(run_dir / "workbench-state.json", {"schemaVersion": 1, "runId": run_dir.name, "state": "awaitingAnalysisInput", "operation": "acquisitionReport", "acquisitionState": summary["acquisitionState"]})
        return {"status": "awaitingAnalysisInput", "runId": run_dir.name, "analysisAllowed": handoff["analysisAllowed"], "outputPath": str(overview), "handoffPath": str(handoff_path), "idempotent": True}

    overview.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".overview-build-", dir=run_dir) as temporary:
        staging = Path(temporary) / "overview"
        staging.mkdir()
        summary_path = staging / "summary-data.json"
        report_path = staging / "report.md"
        atomic_json(summary_path, summary)
        _write_text(report_path, report)
        receipt = {
            "schemaVersion": 1,
            "runId": run_dir.name,
            "acquisitionState": summary["acquisitionState"],
            "sourcePackSha256": summary["sourcePack"]["sha256"],
            "summarySha256": _sha256(summary_path),
            "reportSha256": _sha256(report_path),
            "outputs": [
                {"path": "overview/summary-data.json", "sha256": _sha256(summary_path)},
                {"path": "overview/report.md", "sha256": _sha256(report_path)},
            ],
        }
        validate_payload(receipt, "summary-report-receipt.schema.json")
        atomic_json(staging / "receipt.json", receipt)
        os.replace(staging, overview)
    handoff["summary"]["sha256"] = _sha256(overview / "summary-data.json")
    handoff["report"]["sha256"] = _sha256(overview / "report.md")
    atomic_json(run_dir / "analysis-handoff.json", handoff)
    atomic_json(run_dir / "workbench-state.json", {"schemaVersion": 1, "runId": run_dir.name, "state": "awaitingAnalysisInput", "operation": "acquisitionReport", "acquisitionState": summary["acquisitionState"]})
    return {"status": "awaitingAnalysisInput", "runId": run_dir.name, "analysisAllowed": handoff["analysisAllowed"], "outputPath": str(overview), "handoffPath": str(run_dir / "analysis-handoff.json"), "idempotent": False}


__all__ = ["WorkbenchError", "build_summary", "render_markdown", "render_summary", "verify_handoff"]
