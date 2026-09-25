"""Build a portable, script-only Qianchuan source pack."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import re
import unicodedata
from typing import Any, Mapping


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
        "deduplication": {"uniqueScriptCount": len(groups), "groups": list(groups.values())},
        "availability": availability,
        "contentAvailability": content_availability,
        "sourceRefs": list(source_refs),
    }


__all__ = ["build_source_pack", "extract_script_content", "normalize_text", "script_completeness"]
