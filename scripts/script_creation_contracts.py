"""Versioned request/result contracts shared by the three script Skills."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from errors import ContractError


ANALYSIS_STATES = frozenset({"prepared", "awaitingModel", "draftOnly", "completed", "blocked", "failed"})
REWRITE_STRENGTHS = frozenset({"light", "medium", "strong"})
_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be a non-empty string")
    return value


@dataclass(frozen=True)
class GenerationRequest:
    run_id: str
    analysis_id: str
    source_pack: str | None
    customer_facts: dict[str, Any]
    business_method: str
    target: dict[str, Any]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, brand_mode: bool = False) -> "GenerationRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("generation request must be an object")
        if payload.get("schemaVersion", 1) != 1:
            raise ContractError("schemaVersion must be 1")
        for key in ("customerFacts", "target"):
            if not isinstance(payload.get(key), Mapping):
                raise ContractError(f"{key} must be an object")
        source_pack = payload.get("sourcePack") or payload.get("sourcePackPath")
        if not brand_mode and (not isinstance(source_pack, str) or not source_pack.strip()):
            raise ContractError("sourcePack must be a non-empty string")
        return cls(
            run_id=_text(payload, "runId"),
            analysis_id=_text(payload, "analysisId"),
            source_pack=source_pack,
            customer_facts=dict(payload["customerFacts"]),
            business_method=_text(payload, "businessMethod"),
            target=dict(payload["target"]),
        )


@dataclass(frozen=True)
class RewriteRequest:
    run_id: str
    analysis_id: str
    source_pack: str
    original_text: str
    customer_facts: dict[str, Any]
    business_method: str
    immutable_items: tuple[str, ...]
    delete_items: tuple[str, ...]
    strength: str
    target: dict[str, Any]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RewriteRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("rewrite request must be an object")
        if payload.get("schemaVersion", 1) != 1:
            raise ContractError("schemaVersion must be 1")
        source_pack = payload.get("sourcePack") or payload.get("sourcePackPath")
        if not isinstance(source_pack, str) or not source_pack.strip():
            raise ContractError("sourcePack must be a non-empty string")
        if not isinstance(payload.get("customerFacts"), Mapping) or not isinstance(payload.get("target"), Mapping):
            raise ContractError("customerFacts and target must be objects")
        original = payload.get("originalText")
        if not isinstance(original, str) or not original:
            raise ContractError("originalText must be non-empty and must be preserved")
        strength = payload.get("strength")
        if strength not in REWRITE_STRENGTHS:
            raise ContractError("strength must be light, medium, or strong")
        immutable = payload.get("immutableItems", [])
        deleted = payload.get("deleteItems", [])
        if not all(isinstance(item, str) and item for item in immutable + deleted):
            raise ContractError("immutableItems and deleteItems must contain non-empty strings")
        return cls(
            run_id=_text(payload, "runId"),
            analysis_id=_text(payload, "analysisId"),
            source_pack=source_pack,
            original_text=original,
            customer_facts=dict(payload["customerFacts"]),
            business_method=_text(payload, "businessMethod"),
            immutable_items=tuple(immutable),
            delete_items=tuple(deleted),
            strength=strength,
            target=dict(payload["target"]),
        )


def validate_payload(payload: dict[str, Any], schema_name: str) -> None:
    """Validate a Batch 3 payload against a repository-owned JSON Schema."""
    schema_path = _SCHEMA_ROOT / schema_name
    if schema_path.parent != _SCHEMA_ROOT or not schema_path.is_file():
        raise ContractError(f"unknown Batch 3 schema: {schema_name}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid Batch 3 schema: {schema_name}") from exc
    from jsonschema import validate

    validate(instance=payload, schema=schema)
