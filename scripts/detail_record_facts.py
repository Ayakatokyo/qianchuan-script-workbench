"""Index verified RPA details and select bounded, source-bound analysis records."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def _read_source(root, ref):
    path = (root / ref["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("detail source path is invalid")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise ValueError("detail source hash mismatch")
    return data


def index_attempt(root, material_id, attempt):
    """Keep all business record types from the accepted attempt, without inlining rows."""
    root = Path(root).resolve()
    if attempt.get("identityState") != "matched":
        return None
    sources = []
    counts = Counter()
    files = attempt.get("payloadFiles", [])
    for ref in files:
        if ref.get("kind") != "records-json":
            continue
        csv_ref = next((r for r in files if r.get("kind") == "csv"
                        and Path(r["path"]).with_suffix(".records.json").as_posix() == ref["path"]), None)
        if csv_ref is None:
            continue  # A JSON-only response cannot replace the CSV gate.
        _read_source(root, csv_ref)
        rows = json.loads(_read_source(root, ref))
        if not isinstance(rows, list) or any(not isinstance(r, dict)
                or str(r.get("materialId")) != str(material_id) for r in rows):
            raise ValueError("detail record identity mismatch")
        counts.update(str(r.get("recordType") or "unknown") for r in rows)
        sources.append({"path": ref["path"], "sha256": ref["sha256"],
                        "csv": {"path": csv_ref["path"], "sha256": csv_ref["sha256"]}})
    return {"materialId": str(material_id), "recordCounts": dict(counts), "sources": sources} if sources else None


def bind_detail_index(pack, root):
    """For older runs, verify retained acquisition evidence without rewriting it."""
    root = Path(root).resolve()
    if "detailSources" in pack:
        return deepcopy(pack["detailSources"])
    outcomes = root / "acquisition-results.json"
    if not (root / "acquisition-receipt.json").is_file() or not outcomes.is_file():
        return []
    # This read-only acquisition verifier checks accepted attempts, CSV hashes,
    # identity audits and script facts before legacy evidence becomes selectable.
    from argparse import Namespace
    from script_cli import _verify
    _verify(Namespace(path=str(root)))
    known = {str(m["materialId"]) for m in pack["materials"]}
    result = []
    for material in json.loads(outcomes.read_text())["materials"]:
        mid = str(material["materialId"])
        if mid not in known:
            continue
        attempts = material.get("attempts", [])
        # A later failed/rejected attempt must not expose an earlier payload.
        if attempts and attempts[-1].get("identityState") == "matched":
            entry = index_attempt(root, mid, attempts[-1])
            if entry:
                result.append(entry)
    return result


def _value(record, field):
    value = record
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(row, condition):
    value = _value(row, condition["field"])
    target = condition["value"]
    if condition["op"] == "eq":
        return value == target
    if condition["op"] == "in":
        return value in target
    try:
        if value is None or isinstance(value, bool):
            return False
        return float(value) >= float(target) if condition["op"] == "gte" else float(value) <= float(target)
    except (TypeError, ValueError):
        return False


def _project(row, fields):
    if not fields:
        return deepcopy(row)
    result = {k: row[k] for k in ("recordType", "materialId") if k in row}
    for field in fields:
        value = _value(row, field)
        if value is None:
            continue
        current = result
        parts = field.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = deepcopy(value)
    return result


def select_detail_records(root, index, material_ids, selection):
    """Filter and page each requested record type; never present a page as a total."""
    root = Path(root).resolve()
    entries = {e["materialId"]: e for e in index}
    if len(entries) != len(index) or set(entries) - set(material_ids):
        raise ValueError("detail source index is outside selected materials")
    result = {}
    for mid in material_ids:
        entry = entries.get(mid)
        rows = []
        if entry:
            observed = Counter()
            for source in entry["sources"]:
                _read_source(root, source["csv"])
                data = json.loads(_read_source(root, source))
                if not isinstance(data, list):
                    raise ValueError("detail records must be an array")
                for number, record in enumerate(data):
                    if not isinstance(record, dict) or str(record.get("materialId")) != mid:
                        raise ValueError("detail record identity mismatch")
                    kind = str(record.get("recordType") or "unknown")
                    observed[kind] += 1
                    if record.get("parseStatus") != "failed":
                        token = f'{source["path"]}#/{number};sha256={source["sha256"]}'
                        rows.append((kind, record, token))
            if dict(observed) != entry["recordCounts"]:
                raise ValueError("detail record counts differ from source index")
        fields = {}
        offset = selection.get("offsetPerMaterial", 0)
        limit = selection.get("limitPerMaterial", 100)
        for kind in selection["recordTypes"]:
            matching = [(row, token) for name, row, token in rows if name == kind
                        and all(_matches(row, c) for c in selection.get("filters", []))
                        and (not selection.get("fields") or any(
                            _value(row, f) is not None for f in selection["fields"]))]
            page = matching[offset:offset + limit]
            fields[kind] = {
                "value": [_project(row, selection.get("fields", [])) for row, _ in page],
                "available": bool(page), "sourceRefs": [token for _, token in page],
                "matchingRecordCount": len(matching), "returnedRecordCount": len(page),
                "offset": offset, "hasMore": offset + len(page) < len(matching),
                "nextOffset": offset + len(page) if offset + len(page) < len(matching) else None,
            }
        result[mid] = fields
    return result
