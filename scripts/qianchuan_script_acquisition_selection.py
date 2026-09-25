"""Deterministic local filtering, ranking, and auditable material selection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Mapping

from qianchuan_script_acquisition_contracts import AcquisitionRequest
from qianchuan_script_acquisition_field_registry import (
    FieldRegistry,
    MaterialCandidate,
    MaterialQuery,
    QueryError,
    _decimal,
    _value_at,
    decimal_text,
)


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _serialized_filter_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, tuple):
        return [_serialized_filter_value(item) for item in value]
    return value


@dataclass(frozen=True)
class MaterialSelection:
    candidates: tuple[MaterialCandidate, ...]
    query: MaterialQuery
    report_row_count: int
    filtered_out_count: int
    matching_row_count: int
    rankable_row_count: int
    excluded_rows: tuple[dict[str, Any], ...]
    top_n: int
    systemic_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "status": "awaitingSelection" if self.systemic_error else "selected",
            "reportRowCount": self.report_row_count,
            "filteredOutCount": self.filtered_out_count,
            "matchingRowCount": self.matching_row_count,
            "rankableRowCount": self.rankable_row_count,
            "selectedCount": len(self.candidates),
            "topN": self.top_n,
            "ranking": {
                "fieldId": self.query.sort_entry["id"],
                "label": self.query.sort_entry["label"],
                "direction": self.query.direction,
                "tieBreaker": {"field": "material_id", "direction": self.query.direction},
            },
            "filters": [
                {
                    "fieldId": entry["id"],
                    "label": entry["label"],
                    "operator": operator,
                    "value": _serialized_filter_value(value),
                }
                for entry, operator, value in self.query.filters
            ],
            "selectedMaterialIds": [item.material_id for item in self.candidates],
            "excludedRows": list(self.excluded_rows),
            "systemicError": self.systemic_error,
        }


def _filter_result(query: MaterialQuery, row: Mapping[str, Any]) -> tuple[bool, str | None, str | None]:
    for entry, operator, expected in query.filters:
        raw_value = query.value(row, entry)
        if _missing(raw_value):
            return False, "filter_value_unavailable", entry["id"]
        try:
            value = _decimal(raw_value, entry["id"]) if entry["kind"] == "metric" else str(raw_value)
        except QueryError:
            return False, "filter_value_invalid", entry["id"]
        matched = {
            "eq": lambda: value == expected,
            "gt": lambda: value > expected,
            "gte": lambda: value >= expected,
            "lt": lambda: value < expected,
            "lte": lambda: value <= expected,
            "between": lambda: expected[0] <= value <= expected[1],
            "in": lambda: value in expected,
            "contains": lambda: expected in value,
            "regex": lambda: re.search(expected, value) is not None,
        }[operator]()
        if not matched:
            return False, "filter_not_matched", entry["id"]
    return True, None, None


def select_materials_with_audit(
    rows: list[dict[str, Any]],
    request: AcquisitionRequest,
    registry: FieldRegistry,
) -> MaterialSelection:
    if request.live_acquire is None:
        raise QueryError("select_materials requires liveAcquire")
    query = registry.resolve_query(request.live_acquire.material_filter_sort)
    material_entry = registry.require("material_id")
    ranked: list[tuple[Decimal, str, Mapping[str, Any]]] = []
    exclusions: list[dict[str, Any]] = []
    filtered_out_count = 0
    matching_row_count = 0

    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise QueryError(f"material report row {row_number} is not an object")
        matches, reason, filter_field_id = _filter_result(query, row)
        if not matches:
            if reason == "filter_not_matched":
                filtered_out_count += 1
                continue
            exclusions.append({"rowNumber": row_number, "reason": reason, "fieldId": filter_field_id})
            continue

        matching_row_count += 1
        material_id = str(_value_at(row, material_entry) or "").strip()
        raw_sort_value = query.value(row, query.sort_entry)
        if _missing(raw_sort_value):
            exclusion = {
                "rowNumber": row_number,
                "reason": "sort_value_unavailable",
                "fieldId": query.sort_entry["id"],
            }
            if material_id:
                exclusion["materialId"] = material_id
            exclusions.append(exclusion)
            continue
        try:
            sort_value = _decimal(raw_sort_value, query.sort_entry["id"])
        except QueryError:
            exclusion = {
                "rowNumber": row_number,
                "reason": "sort_value_invalid",
                "fieldId": query.sort_entry["id"],
            }
            if material_id:
                exclusion["materialId"] = material_id
            exclusions.append(exclusion)
            continue
        if not material_id:
            exclusions.append({"rowNumber": row_number, "reason": "material_id_unavailable", "fieldId": material_entry["id"]})
            continue
        ranked.append((sort_value, material_id, row))

    systemic_error = None
    bad_sort_rows = sum(item["reason"].startswith("sort_value_") for item in exclusions)
    if matching_row_count and not ranked and bad_sort_rows == matching_row_count:
        systemic_error = "all_matching_rows_have_unusable_sort_value"

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=query.direction == "desc")
    candidates = tuple(
        MaterialCandidate.from_row(row, rank, registry)
        for rank, (_value, _material_id, row) in enumerate(ranked[: request.live_acquire.top_n], start=1)
    )
    return MaterialSelection(
        candidates=candidates,
        query=query,
        report_row_count=len(rows),
        filtered_out_count=filtered_out_count,
        matching_row_count=matching_row_count,
        rankable_row_count=len(ranked),
        excluded_rows=tuple(exclusions),
        top_n=request.live_acquire.top_n,
        systemic_error=systemic_error,
    )


def select_materials(rows: list[dict[str, Any]], request: AcquisitionRequest, registry: FieldRegistry) -> list[MaterialCandidate]:
    result = select_materials_with_audit(rows, request, registry)
    if result.systemic_error:
        raise QueryError(result.systemic_error)
    return list(result.candidates)


__all__ = ["MaterialSelection", "QueryError", "select_materials", "select_materials_with_audit"]
