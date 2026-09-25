"""Compare independently returned material metadata before admitting a script."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping

from qianchuan_script_acquisition_fact_pack import extract_script_content, normalize_text

ALIASES = {
    "materialName": ("materialName", "material_name", "roi2_material_video_name", "素材名称", "name"),
    "createTime": ("createTime", "create_time", "material_create_time_v2", "素材创建时间"),
    "videoDuration": ("videoDuration", "video_duration", "视频时长"),
}
RETURNED_ID_POLICY = "metadata_and_returned_id_v2"


def _get(row, aliases):
    for container in (row, row.get("dimensions", {}), row.get("Dimensions", {})):
        if not isinstance(container, Mapping):
            continue
        for key in aliases:
            value = container.get(key)
            if isinstance(value, Mapping):
                value = value.get("Value") if value.get("Value") is not None else value.get("ValueStr")
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, Mapping):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _meaningful(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_meaningful(item) for key, item in value.items() if str(key).lower() not in {"error", "errors", "errorcode", "errormessage"})
    if isinstance(value, list):
        return any(_meaningful(item) for item in value)
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def content_evidence(records: list[dict], identity: Mapping[str, Any]) -> dict:
    """Fingerprint content independently of echoed IDs, task IDs and file names."""
    contents = [_normalized(extract_script_content(record)) for record in records
                if record.get("recordType") == "script_analysis" and record.get("parseStatus") != "failed"]
    # CSV row ordering is transport detail, not content identity.
    contents.sort(key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
    return {
        "scriptContentPresent": any((isinstance(item.get("text"), str) and bool(item["text"])) or _meaningful(item.get("detail"))
            or _meaningful(item.get("data")) or (isinstance(item.get("formula"), Mapping) and _meaningful(item["formula"].get("labels")))
            for item in contents),
        "scriptContentSha256": _digest(contents) if contents else None,
        "observedIdentitySha256": _digest(identity["observed"]),
    }


def audit_identity(material: Any, records: list[dict], *, include_returned_id: bool = True) -> dict:
    expected = material if isinstance(material, Mapping) else material.source_row
    material_id = str(material.get("materialId") or material.get("material_id") or "") if isinstance(material, Mapping) else material.material_id
    observed_ids = {str(r.get("materialId")) for r in records if r.get("materialId")}
    mismatches = ["materialId"] if observed_ids - {material_id} else []
    expected_values = {key: _get(expected, aliases) for key, aliases in ALIASES.items()}
    observed_values = {key: sorted({v for r in records if (v := _get(r, aliases)) is not None}) for key, aliases in ALIASES.items()}
    if include_returned_id:
        # This page label is independent of the connector's echoed materialId.
        # Unknown formats are retained for inspection, never guessed as IDs.
        returned_tags = sorted({str(r["materialIdTag"]).strip() for r in records
                                if r.get("materialIdTag") is not None and str(r["materialIdTag"]).strip()})
        expected_values["materialIdTag"] = material_id
        observed_values["materialIdTag"] = sorted({match.group(1) for tag in returned_tags
            if (match := re.fullmatch(r"(?:ID：\s*)?([0-9]+)", tag))})
    compared = []
    for key, value in expected_values.items():
        values = observed_values[key]
        if value is None or not values:
            continue
        compared.append(key)
        def same(other):
            if key == "videoDuration":
                try:
                    left, right = Decimal(value), Decimal(other)
                    return left.is_finite() and right.is_finite() and abs(left - right) <= Decimal("0.1")
                except InvalidOperation:
                    return False
            return value == other
        if not all(same(other) for other in values):
            mismatches.append(key)
    state = "mismatch" if mismatches else ("matched" if compared else "unverified")
    result = {"state": state, "materialId": material_id, "expected": expected_values, "observed": observed_values,
              "observedMaterialIds": sorted(observed_ids), "comparedFields": compared, "mismatchedFields": mismatches}
    if include_returned_id:
        result.update(identityPolicy=RETURNED_ID_POLICY, returnedMaterialIdTags=returned_tags)
    return result
