"""Build Qianchuan script facts with optional indexed RPA detail sources."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping


def bind_report_metric_sources(pack: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """Derive field evidence from the immutable report, never mutate an old pack."""
    result = deepcopy(dict(pack))
    selection = pack.get("selection") or {}
    relative = selection.get("reportSnapshotPath")
    if not relative:
        return result  # Historical imports without a report retain their own evidence.
    root = Path(run_dir).resolve()
    path = (root / relative).resolve()
    if relative != "source-data/material-report-snapshot.json" or not path.is_relative_to(root):
        raise ValueError("metric source snapshot path is invalid")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    receipt = json.loads((root / "report-query-receipt.json").read_text(encoding="utf-8"))
    snapshot = json.loads(raw)
    rows = snapshot.get("rows")
    if (digest != selection.get("reportSnapshotSha256")
            or digest != receipt.get("snapshotSha256")
            or receipt.get("runId") != pack.get("runId")
            or receipt.get("snapshotPath") != relative or receipt.get("status") != "completed"
            or snapshot.get("complete") is not True or not isinstance(rows, list)):
        raise ValueError("metric source snapshot hash or identity mismatch")
    rows_hash = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (snapshot.get("rowsSha256") != rows_hash or receipt.get("rowsSha256") != rows_hash
            or snapshot.get("recordCount") != len(rows) or receipt.get("recordCount") != len(rows)
            or any(snapshot.get(key) != receipt.get(key) for key in ("queryFingerprint", "scopeFingerprint"))):
        raise ValueError("metric source snapshot rows failed verification")
    from qianchuan_script_acquisition_field_registry import MaterialCandidate, load_field_registry, _value_at
    registry = load_field_registry(Path(__file__).resolve().parents[1] / "config/asset-field-registry-v1.json")
    by_id: dict[str, list] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not _value_at(row, registry.require("material_id")):
            continue  # Non-addressable report rows are retained, but never evidence.
        candidate = MaterialCandidate.from_row(row, index + 1, registry)
        by_id.setdefault(candidate.material_id, []).append((index, candidate))
    for material in result["materials"]:
        matches = by_id.get(material["materialId"], [])
        if len(matches) != 1:
            raise ValueError("metric source material row missing or ambiguous: " + material["materialId"])
        index, candidate = matches[0]
        prefix = f"{relative}#sha256={digest}&row={index}&materialId={material['materialId']}"
        sources = {}
        for field, value in material["metrics"].items():
            if value is None:
                continue
            if field not in candidate.metrics or str(value) != str(candidate.metrics[field]):
                raise ValueError("metric source value mismatch: " + material["materialId"] + "/" + field)
            sources[field] = [prefix + "&field=" + field]
        if material.get("metricSourceRefs") is not None and material["metricSourceRefs"] != sources:
            raise ValueError("metric source references mismatch")
        material["metricSourceRefs"] = sources
        material["sourceRefs"] = [prefix]
    return result


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _material_value(material: Any, key: str, default: Any = None) -> Any:
    if isinstance(material, Mapping):
        return material.get(key, default)
    return getattr(material, {"materialId": "material_id", "rank": "rank", "metrics": "metrics"}.get(key, key), default)


def _script_text(fact: Mapping[str, Any]) -> str:
    if isinstance(fact.get("rawText"), str):
        return fact["rawText"]
    if isinstance(fact.get("text"), str):
        return fact["text"]
    record = fact.get("record")
    if isinstance(record, Mapping):
        info = record.get("scriptInfo")
        if isinstance(info, Mapping):
            return str(info.get("text") or "")
        if isinstance(info, str):
            return info
    return ""


def extract_script_content(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return platform fields as received; never derive formula from transcript."""
    info = record.get("scriptInfo") if isinstance(record, Mapping) else None
    if isinstance(info, Mapping):
        return {key: info.get(key) if key in info else None for key in ("formula", "detail", "data", "text")}
    if isinstance(info, str):
        return {"formula": None, "detail": None, "data": None, "text": info}
    return {"formula": None, "detail": None, "data": None, "text": None}


def script_completeness(content: Mapping[str, Any]) -> dict[str, bool]:
    formula = content.get("formula")
    return {
        "text": isinstance(content.get("text"), str) and bool(content.get("text")),
        "formulaLabels": isinstance(formula, Mapping) and bool(formula.get("labels")),
        "detailLabels": bool(content.get("detail")),
        "structuredData": bool(content.get("data")),
        "transcript": isinstance(content.get("text"), str) and bool(content.get("text")),
    }


def build_source_pack(materials: list[Any], script_facts: Mapping[str, Mapping[str, Any]], period: Mapping[str, str], selection: Mapping[str, Any], source_refs: list[str]) -> dict[str, Any]:
    material_payload = []
    script_payload = []
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    availability = {"requested": len(materials), "available": 0, "missing": 0, "failed": 0}
    content_availability = {key: {"available": 0, "missing": 0} for key in ("formulaLabels", "detailLabels", "structuredData", "transcript")}
    for material in materials:
        material_id = str(_material_value(material, "materialId", "")).strip()
        rank = int(_material_value(material, "rank", len(material_payload) + 1))
        metrics = dict(_material_value(material, "metrics", {}) or {})
        refs = list(_material_value(material, "sourceRefs", []) or [])
        material_payload.append({"materialId": material_id, "rank": rank, "metrics": metrics, "sourceRefs": refs})
        fact = dict(script_facts.get(material_id, {}))
        status = str(fact.get("parseStatus") or "missing")
        text = _script_text(fact)
        if status == "parsed" and not text:
            status = "missing"
        if status not in {"parsed", "missing", "failed"}:
            status = "failed"
        if status == "parsed":
            availability["available"] += 1
        else:
            availability[status] += 1
        content = {key: fact[key] for key in ("formula", "detail", "data", "text") if key in fact}
        if not content:
            content = extract_script_content(fact.get("record") if isinstance(fact.get("record"), Mapping) else None)
            if "rawText" in fact and "text" not in content:
                content["text"] = fact.get("rawText")
        else:
            content = {key: content.get(key) for key in ("formula", "detail", "data", "text")}
        if not isinstance(content.get("text"), str):
            content["text"] = text or None
        completeness = script_completeness(content)
        for key in content_availability:
            content_availability[key]["available" if completeness[key] else "missing"] += 1
        supplied_field_refs = fact.get("fieldSourceRefs")
        field_source_refs = {
            key: list(supplied_field_refs.get(key) or []) if isinstance(supplied_field_refs, Mapping) else []
            for key in ("formula", "detail", "data", "text")
        }
        raw_hash = _sha256(text)
        normalized_hash = _sha256(normalize_text(text))
        script_id = "script:" + normalized_hash
        record = {
            "scriptId": script_id,
            "materialId": material_id,
            "rawText": text,
            "rawTextSha256": raw_hash,
            "normalizedTextSha256": normalized_hash,
            "parseStatus": status,
            "completeness": completeness,
            "formula": content["formula"],
            "detail": content["detail"],
            "data": content["data"],
            "text": content["text"],
            "fieldSourceRefs": field_source_refs,
            "sourceRefs": list(fact.get("sourceRefs") or refs),
        }
        if fact.get("materialFile") and fact.get("materialFileSha256"):
            record["materialFile"] = str(fact["materialFile"])
            record["materialFileSha256"] = str(fact["materialFileSha256"])
        if fact.get("error"):
            record["error"] = str(fact["error"])
        script_payload.append(record)
        if status == "parsed":
            group = groups.setdefault(normalized_hash, {"scriptId": script_id, "materialIds": [], "materialMetrics": {}})
            group["materialIds"].append(material_id)
            group["materialMetrics"][material_id] = metrics
    return {
        "schemaVersion": 1,
        "runId": str(selection.get("runId") or "script-run"),
        "period": dict(period),
        "selection": dict(selection),
        "materials": material_payload,
        "scripts": script_payload,
        "detailSources": [dict(f["detailSource"]) for f in script_facts.values() if f.get("detailSource")],
        "deduplication": {"uniqueScriptCount": len(groups), "groups": list(groups.values())},
        "availability": availability,
        "contentAvailability": content_availability,
        "sourceRefs": list(source_refs),
    }


__all__ = ["build_source_pack", "extract_script_content", "normalize_text", "script_completeness"]
