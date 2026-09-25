"""Select parsed Qianchuan references while retaining per-material metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping


@dataclass(frozen=True)
class SelectedScript:
    script_id: str
    text: str
    normalized_text_sha256: str
    material_ids: tuple[str, ...]
    material_metrics: dict[str, dict[str, Any]]
    source_refs: tuple[str, ...]
    material_facts: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scriptId": self.script_id,
            "text": self.text,
            "normalizedTextSha256": self.normalized_text_sha256,
            "materialIds": list(self.material_ids),
            "materialMetrics": self.material_metrics,
            "sourceRefs": list(self.source_refs),
            "materialFacts": list(self.material_facts),
        }


@dataclass(frozen=True)
class ReferenceSelection:
    scripts: tuple[SelectedScript, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"scripts": [script.to_dict() for script in self.scripts], "warnings": list(self.warnings)}


def select_reference_scripts(source_pack: Mapping[str, Any], request: Mapping[str, Any] | Any) -> ReferenceSelection:
    materials = {str(item.get("materialId")): item for item in source_pack.get("materials", []) if isinstance(item, Mapping)}
    grouped: dict[str, dict[str, Any]] = {}
    for script in source_pack.get("scripts", []):
        if not isinstance(script, Mapping) or script.get("parseStatus") != "parsed" or not script.get("rawText"):
            continue
        key = str(script.get("normalizedTextSha256") or script.get("scriptId") or "")
        if not key:
            continue
        group = grouped.setdefault(key, {"script": script, "materialIds": [], "materialMetrics": {}, "sourceRefs": [], "materialFacts": []})
        material_id = str(script.get("materialId") or "")
        if material_id and material_id not in group["materialIds"]:
            group["materialIds"].append(material_id)
            group["materialMetrics"][material_id] = dict(materials.get(material_id, {}).get("metrics", {}))
            completeness = dict(script.get("completeness") or {})
            completeness.setdefault("formulaLabels", False)
            completeness.setdefault("detailLabels", False)
            completeness.setdefault("structuredData", False)
            completeness.setdefault("transcript", bool(script.get("rawText")))
            field_source_refs = script.get("fieldSourceRefs")
            group["materialFacts"].append({
                "materialId": material_id,
                "formula": script.get("formula"),
                "detail": script.get("detail"),
                "data": script.get("data"),
                "text": script.get("text", script.get("rawText")),
                "completeness": completeness,
                "fieldSourceRefs": dict(field_source_refs) if isinstance(field_source_refs, Mapping) else {
                    "formula": [], "detail": [], "data": [], "text": list(script.get("sourceRefs") or [])
                },
            })
        group["sourceRefs"].extend(ref for ref in script.get("sourceRefs", []) if ref not in group["sourceRefs"])
    selected = []
    for key, group in grouped.items():
        script = group["script"]
        selected.append(SelectedScript(
            str(script.get("scriptId") or "script:" + key),
            str(script["rawText"]),
            key,
            tuple(group["materialIds"]),
            group["materialMetrics"],
            tuple(group["sourceRefs"]),
            tuple(group["materialFacts"]),
        ))
    warnings = ("duplicate platform materials share one content reference; metrics remain per material",) if any(len(item.material_ids) > 1 for item in selected) else ()
    return ReferenceSelection(tuple(selected), warnings)


__all__ = ["ReferenceSelection", "SelectedScript", "select_reference_scripts"]


def add_provided_references(selection: ReferenceSelection, references: list[dict]) -> ReferenceSelection:
    """User text has provenance but no platform metrics or observed media."""
    scripts, warnings = list(selection.scripts), list(selection.warnings)
    seen = set()
    for reference in references:
        identifier = reference["id"]
        if identifier in seen:
            raise ValueError("provided reference IDs must be unique")
        seen.add(identifier)
        text = reference.get("text", "").strip()
        if not text:
            warnings.append(f"provided:{identifier}: link not parsed; no text/video/audio evidence")
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source_refs = [f"user-provided:{reference['kind']}:{reference['source']}"]
        if reference.get("url"):
            source_refs.append(reference["url"])
        scripts.append(SelectedScript(f"provided:{identifier}", text, digest, (), {}, tuple(source_refs)))
    return ReferenceSelection(tuple(scripts), tuple(warnings))
