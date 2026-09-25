"""Parse the unit-separated CSV returned by Qianchuan diagnosis."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
from typing import Any


FIELD_DELIMITER = "\x01"
RECORD_PREFIX = "\x02"
STRUCTURED_FIELDS = ("Dimensions", "Metrics", "Fields")


class RpaCsvError(ValueError):
    pass


@dataclass(frozen=True)
class DiagnosisRecord:
    record_type: str
    material_id: str
    raw: dict[str, Any]
    script_info: dict[str, Any]
    parse_status: str
    parse_error: str | None = None
    duration_sec: float | None = None
    metric_value: float | None = None
    dimensions: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    fields: dict[str, Any] | None = None


def _number(value: Any, field_name: str, source: Path, row_number: int) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise RpaCsvError(f"RPA CSV {source}, row {row_number}: {field_name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RpaCsvError(f"RPA CSV {source}, row {row_number}: {field_name} must be a finite number") from exc
    if not math.isfinite(result):
        raise RpaCsvError(f"RPA CSV {source}, row {row_number}: {field_name} must be a finite number")
    return result


def _structured(value: Any, field_name: str, source: Path, row_number: int) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError, TypeError) as exc:
            raise RpaCsvError(f"RPA CSV {source}, row {row_number}: {field_name} must be a structured object") from exc
    if not isinstance(parsed, dict):
        raise RpaCsvError(f"RPA CSV {source}, row {row_number}: {field_name} must be a structured object")
    return parsed


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RpaCsvError(f"unable to read RPA CSV {path}") from exc


def parse_diagnosis_csv(path: Path) -> list[DiagnosisRecord]:
    source = Path(path)
    text = _read(source)
    if FIELD_DELIMITER not in text.partition("\n")[0]:
        raise RpaCsvError(f"RPA CSV {source} must use the \\x01 field delimiter")
    text = text.removeprefix(RECORD_PREFIX).replace("\n" + RECORD_PREFIX, "\n")
    reader = csv.DictReader(io.StringIO(text), delimiter=FIELD_DELIMITER)
    if not reader.fieldnames or any(not name for name in reader.fieldnames):
        raise RpaCsvError(f"RPA CSV {source} has an invalid header")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise RpaCsvError(f"RPA CSV {source} has duplicate header names")
    records: list[DiagnosisRecord] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise RpaCsvError(f"RPA CSV {source}, row {row_number}: has more values than header columns")
        if not any(value not in (None, "") for value in row.values()):
            continue
        raw = dict(row)
        structured: dict[str, dict[str, Any]] = {}
        for field in STRUCTURED_FIELDS:
            if field in raw:
                structured[field] = _structured(raw[field], field, source, row_number)
        duration = _number(raw.get("durationSec"), "durationSec", source, row_number)
        metric = _number(raw.get("metricValue"), "metricValue", source, row_number)
        script_info: dict[str, Any] = {}
        parse_status = "parsed"
        parse_error: str | None = None
        if raw.get("scriptInfo"):
            try:
                script_info = _structured(raw["scriptInfo"], "scriptInfo", source, row_number)
            except RpaCsvError as exc:
                parse_status = "failed"
                parse_error = str(exc)
        record_type = str(raw.get("recordType") or "").strip()
        if record_type == "script_analysis" and not raw.get("scriptInfo"):
            parse_status = "missing"
        records.append(
            DiagnosisRecord(
                record_type=record_type,
                material_id=str(raw.get("materialId") or "").strip(),
                raw=raw,
                script_info=script_info,
                parse_status=parse_status,
                parse_error=parse_error,
                duration_sec=duration,
                metric_value=metric,
                dimensions=structured.get("Dimensions", {}),
                metrics=structured.get("Metrics", {}),
                fields=structured.get("Fields", {}),
            )
        )
    if not records:
        raise RpaCsvError(f"RPA CSV {source} has no records")
    return records


__all__ = ["DiagnosisRecord", "FIELD_DELIMITER", "RECORD_PREFIX", "RpaCsvError", "parse_diagnosis_csv"]
