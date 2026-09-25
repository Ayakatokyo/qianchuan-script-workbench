"""Read-only adapter for an already completed Qianchuan fact-pack run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from qianchuan_script_acquisition_fact_pack import build_source_pack
from qianchuan_script_acquisition_receipt import atomic_json, write_receipt, write_status


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read verified-run JSON: {path.name}") from exc


def _verify_manifest(fact_pack: Path, manifest: dict[str, Any], *, source_root: Path) -> None:
    declared = manifest.get("sourceFiles")
    base = source_root
    if declared is None:
        declared = manifest.get("files")
        base = fact_pack
    if not isinstance(declared, list):
        raise ValueError("verified-run manifest has invalid declared files")
    for entry in declared:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise ValueError("verified-run manifest has an invalid file entry")
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("verified-run manifest path escapes fact-pack")
        path = base / relative
        if not path.is_file():
            raise ValueError(f"verified-run manifest file missing: {entry['path']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"verified-run hash mismatch: {entry['path']}")
        if "sizeBytes" in entry and entry["sizeBytes"] != path.stat().st_size:
            raise ValueError(f"verified-run size mismatch: {entry['path']}")


def import_verified_run(source_run: Path, output_dir: Path) -> Path:
    source_run = Path(source_run)
    output_dir = Path(output_dir)
    result_path = output_dir / "facts" / "qianchuan-script-source-pack.json"
    if result_path.exists():
        raise ValueError("verified-run output already exists")
    fact_pack = source_run / "fact-pack"
    required = {name: fact_pack / name for name in ("manifest.json", "material-leaderboard.json", "scripts.json")}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError("verified-run requires " + ", ".join(missing))
    manifest = _read_json(required["manifest.json"])
    _verify_manifest(fact_pack, manifest, source_root=source_run)
    leaderboard = _read_json(required["material-leaderboard.json"])
    scripts_payload = _read_json(required["scripts.json"])
    materials = leaderboard.get("materials", []) if isinstance(leaderboard, dict) else leaderboard
    script_rows = scripts_payload.get("scripts", []) if isinstance(scripts_payload, dict) else scripts_payload
    script_facts = {}
    for row in script_rows:
        if not isinstance(row, dict):
            raise ValueError("verified-run scripts.json contains a non-object record")
        material_id = str(row.get("materialId") or "").strip()
        script_facts[material_id] = {
            "parseStatus": row.get("parseStatus", "parsed"),
            "rawText": row.get("rawText", row.get("text", "")),
            "sourceRefs": list(row.get("sourceRefs") or ["fact-pack/scripts.json"]),
        }
    period = manifest.get("period") or {"startDate": "unknown", "endDate": "unknown"}
    selection = {"runId": source_run.name, "rankingField": "", "direction": "desc", "filters": []}
    pack = build_source_pack(materials, script_facts, period, selection, ["fact-pack/manifest.json", "fact-pack/material-leaderboard.json", "fact-pack/scripts.json"])
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(result_path, pack)
    write_status(output_dir, "ready", runId=pack["runId"], availability=pack["availability"])
    write_receipt(output_dir, {"schemaVersion": 1, "runId": pack["runId"], "status": "completed", "sourceRun": str(source_run), "counts": pack["availability"], "outputs": ["facts/qianchuan-script-source-pack.json", "status.json"]})
    return result_path


__all__ = ["import_verified_run"]
