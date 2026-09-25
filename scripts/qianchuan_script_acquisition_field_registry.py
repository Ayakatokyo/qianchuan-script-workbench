"""Allowlisted Qianchuan report fields and deterministic local queries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any, Mapping


class FieldRegistryError(ValueError):
    pass


class QueryError(ValueError):
    pass


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise QueryError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise QueryError(f"{label} must be a finite number") from exc
    if not result.is_finite():
        raise QueryError(f"{label} must be a finite number")
    return result


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _value_at(row: Mapping[str, Any], entry: Mapping[str, Any]) -> Any:
    field_id = entry["id"]
    label = entry.get("label")
    for container_name in ("metrics", "dimensions"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            for key in (field_id, label):
                if key in container:
                    value = container[key]
                    if isinstance(value, Mapping):
                        numeric_value = value.get("Value")
                        return value.get("ValueStr") if numeric_value is None else numeric_value
                    return value
    for key in (field_id, label, entry.get("sourceKey")):
        if key and key in row:
            return row[key]
    source = entry.get("source")
    if isinstance(source, list):
        current: Any = row
        for key in source:
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        return current
    return None


@dataclass(frozen=True)
class FieldRegistry:
    version: str
    entries_by_id: dict[str, dict[str, Any]]
    ids_by_label: dict[str, str]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FieldRegistry":
        if not isinstance(payload, Mapping) or payload.get("schemaVersion") != 1:
            raise FieldRegistryError("field registry schemaVersion must be 1")
        fields = payload.get("fields")
        if not isinstance(fields, list) or not fields:
            raise FieldRegistryError("field registry fields must be a nonempty list")
        by_id: dict[str, dict[str, Any]] = {}
        by_label: dict[str, str] = {}
        for entry in fields:
            if not isinstance(entry, Mapping):
                raise FieldRegistryError("field registry entry must be an object")
            field_id = str(entry.get("id") or "").strip()
            label = str(entry.get("label") or "").strip()
            if not field_id or field_id in by_id or not label or label in by_label:
                raise FieldRegistryError("field registry has an invalid or duplicate field")
            if entry.get("kind") not in {"dimension", "metric"}:
                raise FieldRegistryError("field registry field kind is invalid")
            operators = entry.get("operators")
            if not isinstance(operators, list) or not all(isinstance(item, str) for item in operators):
                raise FieldRegistryError("field registry operators must be a string list")
            by_id[field_id] = dict(entry)
            by_label[label] = field_id
        return cls(str(payload.get("registryVersion") or ""), by_id, by_label)

    def require(self, field: str) -> dict[str, Any]:
        key = str(field or "").strip()
        key = self.ids_by_label.get(key, key)
        try:
            return self.entries_by_id[key]
        except KeyError as exc:
            raise QueryError(f"field registry does not contain {field}") from exc

    def validate_operator(self, field: str, operator: str) -> dict[str, Any]:
        entry = self.require(field)
        if operator not in entry["operators"]:
            raise QueryError(f"field registry field {entry['id']} does not allow {operator}")
        return entry

    def resolve_query(self, spec: Mapping[str, Any] | None) -> "MaterialQuery":
        spec = dict(spec or {})
        sort_field = spec.get("sortField") or spec.get("field") or "千次曝光成本"
        try:
            sort_entry = self.require(sort_field)
        except QueryError as exc:
            raise QueryError(f"field registry: unknown sort field {sort_field}") from exc
        if sort_entry.get("kind") != "metric" or not sort_entry.get("sortable", False):
            raise QueryError(f"field registry: sort field {sort_field} is not a sortable metric")
        direction = str(spec.get("direction", "desc")).lower()
        if direction not in {"asc", "desc"}:
            raise QueryError("field registry: sort direction must be asc or desc")
        filters = []
        for raw in spec.get("filters", []):
            if not isinstance(raw, Mapping):
                raise QueryError("field registry: filter must be an object")
            field = raw.get("field")
            operator = str(raw.get("operator") or "eq")
            entry = self.validate_operator(field, operator)
            value = raw.get("value")
            if entry["kind"] == "metric":
                if operator == "between":
                    if not isinstance(value, list) or len(value) != 2:
                        raise QueryError("metric between filter requires exactly two values")
                    value = (_decimal(value[0], entry["id"]), _decimal(value[1], entry["id"]))
                    if value[0] > value[1]:
                        raise QueryError("metric between lower value must not exceed upper value")
                else:
                    value = _decimal(value, entry["id"])
            elif operator == "in":
                if not isinstance(value, list) or not value:
                    raise QueryError("dimension in filter requires a nonempty list")
                value = tuple(str(item).strip() for item in value)
            else:
                value = str(value or "").strip()
                if not value:
                    raise QueryError("dimension filter value must be nonempty")
                if operator == "regex":
                    try:
                        re.compile(value)
                    except re.error as exc:
                        raise QueryError("dimension regex is invalid") from exc
            filters.append((entry, operator, value))
        return MaterialQuery(self, sort_entry, direction, tuple(filters))

    def entries(self):
        return tuple(self.entries_by_id.values())


@dataclass(frozen=True)
class MaterialQuery:
    registry: FieldRegistry
    sort_entry: dict[str, Any]
    direction: str
    filters: tuple[tuple[dict[str, Any], str, Any], ...]

    def value(self, row: Mapping[str, Any], entry: Mapping[str, Any]) -> Any:
        return _value_at(row, entry)

    def matches(self, row: Mapping[str, Any]) -> bool:
        for entry, operator, expected in self.filters:
            value = self.value(row, entry)
            if value is None or (isinstance(value, str) and not value.strip()):
                return False
            if entry["kind"] == "metric":
                value = _decimal(value, entry["id"])
            else:
                value = str(value)
            if operator == "eq" and value != expected:
                return False
            if operator == "gt" and not value > expected:
                return False
            if operator == "gte" and not value >= expected:
                return False
            if operator == "lt" and not value < expected:
                return False
            if operator == "lte" and not value <= expected:
                return False
            if operator == "between" and not expected[0] <= value <= expected[1]:
                return False
            if operator == "in" and value not in expected:
                return False
            if operator == "contains" and expected not in value:
                return False
            if operator == "regex" and re.search(expected, value) is None:
                return False
        return True

    def sort_value(self, row: Mapping[str, Any]) -> Decimal:
        value = self.value(row, self.sort_entry)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise QueryError(f"sort field {self.sort_entry['id']} is unavailable")
        return _decimal(value, self.sort_entry["id"])


@dataclass(frozen=True)
class MaterialCandidate:
    material_id: str
    rank: int
    metrics: dict[str, str]
    dimensions: dict[str, str]
    source_row: dict[str, Any]

    @classmethod
    def from_row(cls, row: Mapping[str, Any], rank: int, registry: FieldRegistry) -> "MaterialCandidate":
        material_entry = registry.require("material_id")
        material_id = str(_value_at(row, material_entry) or "").strip()
        if not material_id:
            raise QueryError("material report row has no materialId")
        metrics: dict[str, str] = {}
        dimensions: dict[str, str] = {}
        for entry in registry.entries():
            value = _value_at(row, entry)
            if value is None:
                continue
            if entry["kind"] == "metric":
                # Non-selection metrics remain raw report facts. Only the chosen
                # ranking/filter fields must parse numerically for this run.
                metrics[entry["id"]] = str(value)
            else:
                dimensions[entry["id"]] = str(value)
        return cls(material_id, rank, metrics, dimensions, dict(row))


def load_field_registry(path: Path) -> FieldRegistry:
    try:
        return FieldRegistry.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FieldRegistryError("field registry is unreadable") from exc


__all__ = ["FieldRegistry", "FieldRegistryError", "MaterialCandidate", "MaterialQuery", "QueryError", "decimal_text", "load_field_registry"]
