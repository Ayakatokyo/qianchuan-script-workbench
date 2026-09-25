"""Atomic, local receipts for script acquisition runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def atomic_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def write_status(output_dir: Path, state: str, **extra: Any) -> Path:
    return atomic_json(Path(output_dir) / "status.json", {"schemaVersion": 1, "runId": Path(output_dir).name, "state": state, **extra})


def write_receipt(output_dir: Path, payload: dict[str, Any]) -> Path:
    return atomic_json(Path(output_dir) / "acquisition-receipt.json", payload)


__all__ = ["atomic_json", "write_receipt", "write_status"]
