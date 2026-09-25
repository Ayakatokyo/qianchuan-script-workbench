"""Compare independently returned material metadata before admitting a script."""
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

ALIASES = {
    "materialName": ("materialName", "material_name", "roi2_material_video_name", "素材名称", "name"),
    "createTime": ("createTime", "create_time", "material_create_time_v2", "素材创建时间"),
    "videoDuration": ("videoDuration", "video_duration", "视频时长"),
}


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


def audit_identity(material: Any, records: list[dict]) -> dict:
    expected = material if isinstance(material, Mapping) else material.source_row
    material_id = str(material.get("materialId") or material.get("material_id") or "") if isinstance(material, Mapping) else material.material_id
    observed_ids = {str(r.get("materialId")) for r in records if r.get("materialId")}
    mismatches = ["materialId"] if observed_ids - {material_id} else []
    expected_values = {key: _get(expected, aliases) for key, aliases in ALIASES.items()}
    observed_values = {key: sorted({v for r in records if (v := _get(r, aliases)) is not None}) for key, aliases in ALIASES.items()}
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
    return {"state": state, "materialId": material_id, "expected": expected_values, "observed": observed_values,
            "observedMaterialIds": sorted(observed_ids), "comparedFields": compared, "mismatchedFields": mismatches}
