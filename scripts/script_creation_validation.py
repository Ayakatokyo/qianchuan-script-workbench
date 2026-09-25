"""Deterministic publication checks for model-produced script drafts."""

from __future__ import annotations

import math
from typing import Any, Mapping

from script_creation_contracts import validate_payload


class PublishError(ValueError):
    pass


def _fact_ids(customer_facts: Mapping[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in customer_facts.get("facts", []) if isinstance(item, Mapping) and item.get("id")}


def audit_claim_refs(draft: Mapping[str, Any], customer_facts: Mapping[str, Any]) -> None:
    fact_ids = _fact_ids(customer_facts)
    for script in draft.get("scripts", []):
        for claim in script.get("claims", []):
            refs = claim.get("customerFactRefs", [])
            if not refs or not set(refs).issubset(fact_ids):
                raise PublishError("customer fact claim reference is missing or unknown")


def audit_reference_refs(draft: Mapping[str, Any], reference_selection: Mapping[str, Any]) -> None:
    reference_ids = {str(item.get("scriptId")) for item in reference_selection.get("scripts", []) if isinstance(item, Mapping)}
    if not reference_ids:
        raise PublishError("no parsed reference scripts are available")
    for script in draft.get("scripts", []):
        refs = script.get("referenceRefs", [])
        if not refs or not set(refs).issubset(reference_ids):
            raise PublishError("draft must cite parsed reference scripts")


def audit_reference_analyses(draft: Mapping[str, Any], reference_selection: Mapping[str, Any]) -> None:
    """Require source-bound, per-material formula/text comparisons in completed results."""
    if draft.get("status") != "completed":
        return
    selected = {
        str(item.get("scriptId")): item
        for item in reference_selection.get("scripts", [])
        if isinstance(item, Mapping) and item.get("materialFacts")
    }
    if not selected:
        return
    analyses = draft.get("referenceAnalyses")
    if not isinstance(analyses, list):
        raise PublishError("completed output must include per-material referenceAnalyses")
    analysis_by_ref = {}
    for analysis in analyses:
        if not isinstance(analysis, Mapping) or not analysis.get("referenceRef"):
            raise PublishError("reference analysis has no valid referenceRef")
        reference_id = str(analysis["referenceRef"])
        if reference_id in analysis_by_ref:
            raise PublishError("duplicate reference analysis")
        analysis_by_ref[reference_id] = analysis
    if set(analysis_by_ref) != set(selected):
        raise PublishError("reference analyses must cover each selected platform reference exactly once")

    fields = ("formula", "detail", "data", "text")
    categories = ("opening", "sellingPointProgression", "evidence", "callToAction")
    for reference_id, source in selected.items():
        facts = {str(item.get("materialId")): item for item in source["materialFacts"] if isinstance(item, Mapping)}
        item_analyses = analysis_by_ref[reference_id].get("materialAnalyses")
        if not isinstance(item_analyses, list) or len(item_analyses) != len(facts):
            raise PublishError("reference analysis must include every material-specific formula")
        seen_materials = set()
        for analysis in item_analyses:
            if not isinstance(analysis, Mapping):
                raise PublishError("material analysis must be an object")
            material_id = str(analysis.get("materialId") or "")
            if material_id not in facts or material_id in seen_materials:
                raise PublishError("material analyses contain a missing, duplicate, or unknown materialId")
            seen_materials.add(material_id)
            fact = facts[material_id]
            completeness = fact.get("completeness") or {}
            has_structure = any(bool(completeness.get(key)) for key in ("formulaLabels", "detailLabels", "structuredData"))
            expected_mode = "structuredAndText" if has_structure else "textOnly"
            if analysis.get("evidenceMode") != expected_mode:
                raise PublishError("material analysis evidenceMode does not match available platform fields")
            observations = analysis.get("platformObservations")
            if not isinstance(observations, Mapping):
                raise PublishError("material analysis omits platformObservations")
            for field, completeness_key in (("formula", "formulaLabels"), ("detail", "detailLabels"), ("data", "structuredData")):
                observation = observations.get(field)
                if completeness.get(completeness_key):
                    if not isinstance(observation, str) or not observation.strip():
                        raise PublishError(f"available {field} must have a reviewable platform observation")
                elif observation is not None:
                    raise PublishError(f"missing {field} cannot be represented as an observed platform label")
            if not isinstance(observations.get("transcript"), str) or not observations["transcript"].strip():
                raise PublishError("material analysis omits its transcript observation")
            field_sources = analysis.get("fieldSources")
            expected_sources = fact.get("fieldSourceRefs") or {}
            if not isinstance(field_sources, Mapping) or set(field_sources) != set(fields):
                raise PublishError("material analysis must cite each platform field source separately")
            for field in fields:
                actual_refs = field_sources.get(field)
                expected_refs = list(expected_sources.get(field) or [])
                if not isinstance(actual_refs, list) or len(actual_refs) != len(set(actual_refs)) or set(actual_refs) != set(expected_refs):
                    raise PublishError(f"material analysis has missing or unsupported {field} source references")
                completeness_key = {"formula": "formulaLabels", "detail": "detailLabels", "data": "structuredData", "text": "transcript"}[field]
                if completeness.get(completeness_key) and not actual_refs:
                    raise PublishError(f"available {field} has no traceable source reference")
            comparison = analysis.get("comparison")
            if not isinstance(comparison, Mapping) or set(comparison) != set(categories):
                raise PublishError("material analysis must compare opening, selling-point progression, evidence, and CTA")
            for dimension in categories:
                result = comparison[dimension]
                if not isinstance(result, Mapping) or any(not isinstance(result.get(key), str) or not result[key].strip() for key in ("alignment", "platformBasis", "transcriptBasis", "modelInference")):
                    raise PublishError(f"{dimension} comparison must separate platform basis, transcript basis, and model inference")
                if expected_mode == "textOnly" and result["alignment"] != "textOnly":
                    raise PublishError("text-only references must not claim formula/text alignment")
                if expected_mode == "structuredAndText" and result["alignment"] == "textOnly":
                    raise PublishError("available formula/detail/data must be jointly compared with the transcript")
            if not isinstance(analysis.get("borrowableMethod"), str) or not analysis["borrowableMethod"].strip():
                raise PublishError("material analysis must record a borrowable structure method")


def audit_reference_analysis_citations(draft: Mapping[str, Any]) -> None:
    """Ensure each completed creative/rewrite result cites its analyzed material(s)."""
    if draft.get("status") != "completed":
        return
    valid_pairs = {
        (str(group.get("referenceRef")), str(item.get("materialId")))
        for group in draft.get("referenceAnalyses", []) if isinstance(group, Mapping)
        for item in group.get("materialAnalyses", []) if isinstance(item, Mapping)
    }
    if not valid_pairs:
        return
    targets = draft.get("scripts") or [draft]
    for target in targets:
        citations = target.get("referenceAnalysisRefs")
        reference_ids = set(str(value) for value in target.get("referenceRefs", []))
        if not isinstance(citations, list) or not citations:
            raise PublishError("completed creative output must cite a reference analysis conclusion")
        seen = set()
        for citation in citations:
            if not isinstance(citation, Mapping):
                raise PublishError("referenceAnalysisRefs entries must identify a reference and material")
            pair = (str(citation.get("referenceRef") or ""), str(citation.get("materialId") or ""))
            if pair not in valid_pairs or pair in seen:
                raise PublishError("referenceAnalysisRefs cites a missing or duplicate material analysis")
            if pair[0] not in reference_ids:
                raise PublishError("reference analysis citation is not included in the output's referenceRefs")
            seen.add(pair)


def audit_single_test_variable(draft: Mapping[str, Any]) -> None:
    scripts = draft.get("scripts") or []
    if not 2 <= len(scripts) <= 3:
        raise PublishError("generation must contain 2-3 script variants")
    for script in scripts:
        if not isinstance(script.get("primaryVariable"), str) or not script["primaryVariable"].strip():
            raise PublishError("each script variant must declare one primary variable")


def validate_generation_draft(draft: dict[str, Any], customer_facts: Mapping[str, Any], reference_selection: Mapping[str, Any], *, allow_unreferenced: bool = False) -> None:
    # Give the operator the domain-specific missing-evidence reason before the
    # lower-level schema renderer reports the same empty reference array.
    audit_claim_refs(draft, customer_facts)
    if allow_unreferenced and not reference_selection.get("scripts"):
        if (draft.get("status") != "draftOnly" or draft.get("checks", {}).get("referencesAvailable") is not False
                or draft.get("referenceScripts") or not draft.get("missing")
                or any(script.get("referenceRefs") for script in draft.get("scripts", []))):
            raise PublishError("no references: only an explicitly unreferenced draftOnly draft is allowed")
    else:
        audit_reference_refs(draft, reference_selection)
    audit_single_test_variable(draft)
    try:
        validate_payload(draft, "generated-scripts.schema.json")
    except Exception as exc:
        raise PublishError(f"generated script schema validation failed: {exc}") from exc
    audit_reference_analyses(draft, reference_selection)
    audit_reference_analysis_citations(draft)
    if allow_unreferenced:
        selected = {item["scriptId"]: item for item in reference_selection.get("scripts", [])}
        cited = {ref for script in draft["scripts"] for ref in script["referenceRefs"]}
        summaries = draft["referenceScripts"]
        if {item["scriptId"] for item in summaries} != cited or len(summaries) != len(cited):
            raise PublishError("brand reference summaries must match cited references")
        for summary in summaries:
            source = selected[summary["scriptId"]]
            if any(summary[key] != source[key] for key in ("materialIds", "sourceRefs")):
                raise PublishError("brand reference provenance differs from prepared evidence")
    checks = draft.get("checks", {})
    if draft.get("status") == "completed" and (not customer_facts.get("complete", False) or not all(checks.get(key) for key in ("customerFactsComplete", "referencesAvailable", "constraintsPassed"))):
        raise PublishError("completed generation requires complete customer facts and passed checks")


def audit_rewrite_constraints(draft: Mapping[str, Any], request: Mapping[str, Any], customer_facts: Mapping[str, Any], reference_selection: Mapping[str, Any]) -> None:
    original = str(request.get("originalText") or "")
    if draft.get("originalText") != original:
        raise PublishError("original text is immutable and must be preserved")
    rewritten = str(draft.get("rewrittenText") or "")
    if rewritten == original:
        raise PublishError("rewrite must contain paragraph-level changes")
    if any(str(item) not in rewritten for item in request.get("immutableItems", [])):
        raise PublishError("immutable item was removed")
    if any(str(item) in rewritten for item in request.get("deleteItems", [])):
        raise PublishError("delete item was retained")
    if draft.get("strength") != request.get("strength"):
        raise PublishError("rewrite strength does not match request")
    if not draft.get("changes"):
        raise PublishError("rewrite must include a change log")
    reference_ids = {str(item.get("scriptId")) for item in reference_selection.get("scripts", []) if isinstance(item, Mapping)}
    if not reference_ids or not set(draft.get("referenceRefs", [])).issubset(reference_ids) or not draft.get("referenceRefs"):
        raise PublishError("rewrite must cite parsed reference scripts")
    target = request.get("target", {})
    original_length, new_length = spoken_length(original), spoken_length(rewritten)
    if target.get("shorten") is True and new_length >= original_length:
        raise PublishError("shorten request requires a shorter rewritten script")
    maximum = target.get("maxCharacters")
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1 or new_length > maximum):
        raise PublishError("rewritten script exceeds valid target maxCharacters")
    checks = draft.get("checks", {})
    if draft.get("status") == "completed" and (not customer_facts.get("complete", False) or not all(checks.get(key) for key in ("immutableItemsPreserved", "deleteItemsRemoved", "customerFactsComplete", "constraintsPassed"))):
        raise PublishError("completed rewrite requires passed immutable, customer fact, and constraint checks")


def validate_rewrite_draft(draft: dict[str, Any], request: Mapping[str, Any], customer_facts: Mapping[str, Any], reference_selection: Mapping[str, Any]) -> None:
    audit_rewrite_constraints(draft, request, customer_facts, reference_selection)
    try:
        validate_payload(draft, "rewritten-script.schema.json")
    except Exception as exc:
        raise PublishError(f"rewritten script schema validation failed: {exc}") from exc
    audit_reference_analyses(draft, reference_selection)
    audit_reference_analysis_citations(draft)


__all__ = ["PublishError", "audit_claim_refs", "audit_reference_refs", "audit_reference_analyses", "audit_reference_analysis_citations", "audit_single_test_variable", "audit_rewrite_constraints", "validate_generation_draft", "validate_rewrite_draft"]


def spoken_length(text):
    """Count non-whitespace characters consistently in gates and reports."""
    return sum(not character.isspace() for character in text)


def confirmed_brand_facts(request):
    facts = request.get("customerFacts", {}).get("facts", [])
    if not isinstance(facts, list) or any(not isinstance(fact, dict) for fact in facts):
        raise PublishError("brand customer facts must be a list of objects")
    identifiers = [fact.get("id") for fact in facts]
    if any(not isinstance(identifier, str) or not identifier.strip() for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise PublishError("brand customer fact IDs must be nonempty and unique")
    return {fact["id"] for fact in facts if fact.get("confirmed") is True
            and isinstance(fact.get("text"), str) and fact["text"].strip()
            and isinstance(fact.get("evidence"), str) and fact["evidence"].strip()}


def brand_brief_missing(request):
    target = request.get("target", {})
    if target.get("generationMode", "exploration") not in {"exploration", "hook-ab"}:
        raise PublishError("generationMode must be exploration or hook-ab")
    if type(target.get("scriptCount", 3)) is not int or target.get("scriptCount", 3) not in (2, 3):
        raise PublishError("brand scriptCount must be 2 or 3")
    duration = target.get("durationSec", 45)
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 3:
        raise PublishError("brand durationSec must be finite and greater than 3")
    confirmed = confirmed_brand_facts(request)
    missing = []
    for key in ("productName", "audience"):
        if not isinstance(target.get(key), str) or not target[key].strip():
            missing.append(f"target.{key}")
    for key in ("sellingPointRefs", "promotionFactRefs"):
        refs = target.get(key, [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
            raise PublishError(f"target.{key} must contain unique fact IDs")
        if not set(refs).issubset(confirmed):
            missing.append(f"target.{key}: confirmed facts with evidence required")
    if not target.get("sellingPointRefs"):
        missing.append("target.sellingPointRefs")
    promotion = target.get("promotionStatus", "unknown")
    if promotion not in {"confirmed", "none", "unknown"}:
        raise PublishError("promotionStatus must be confirmed, none, or unknown")
    if promotion == "unknown" or (promotion == "confirmed" and not target.get("promotionFactRefs")):
        missing.append("target.promotion: confirm mechanism or explicitly no promotion")
    if promotion == "none" and target.get("promotionFactRefs"):
        raise PublishError("no-promotion brief cannot contain promotion fact references")
    if request.get("customerFacts", {}).get("complete") is not True:
        missing.append("customerFacts.complete")
    return missing


def audit_brand_storyboard(draft, request, profile):
    if request.get("target", {}).get("brand") != profile["brand"]:
        raise PublishError("brand target mismatch")
    missing = brand_brief_missing(request)
    if missing and (draft["status"] != "draftOnly" or not draft.get("missing")):
        raise PublishError("incomplete brand brief requires draftOnly with missing items")
    target = request["target"]
    hook_ab = target.get("generationMode", "exploration") == "hook-ab"
    confirmed = confirmed_brand_facts(request)
    required_points = (set(target.get("sellingPointRefs", [])) | set(target.get("promotionFactRefs", []))) & confirmed
    scripts = draft["scripts"]
    learnings = draft.get("referenceLearnings")
    cited = {ref for script in scripts for ref in script["referenceRefs"]}
    if not isinstance(learnings, list) or {item["referenceRef"] for item in learnings} != cited:
        raise PublishError("brand referenceLearnings must explain each cited text reference")
    duration = request.get("target", {}).get("durationSec", 45)
    if len(scripts) != request.get("target", {}).get("scriptCount", 3):
        raise PublishError("brand variant count must match target scriptCount")
    hook_types = [script.get("hookType") for script in scripts]
    if any(hook not in profile["hookTypes"] for hook in hook_types) or len(set(hook_types)) != len(scripts):
        raise PublishError("brand variants must use distinct supported hook types")
    bodies = []
    for script in scripts:
        shots = script.get("shots", [])
        if not shots or script["primaryVariable"] != ("hook" if hook_ab else "creative-direction"):
            raise PublishError("brand requires storyboard shots and the variable matching generationMode")
        for claim in script["claims"]:
            if not set(claim["customerFactRefs"]).issubset(confirmed):
                raise PublishError("brand claims must cite confirmed facts with evidence")
        cursor = 0
        segments, ids = [], set()
        for shot in shots:
            if shot["shotId"] in ids or shot["startSec"] != cursor or shot["endSec"] <= cursor:
                raise PublishError("storyboard timeline must be continuous with unique shot IDs")
            ids.add(shot["shotId"])
            cursor = shot["endSec"]
            if not segments or segments[-1] != shot["segment"]:
                segments.append(shot["segment"])
            if shot["segment"] == "hook" and cursor > 3:
                raise PublishError("brand hook must end within the first 3 seconds")
        if segments != ["hook", "product", "proof", "cta"] or cursor != duration:
            raise PublishError("storyboard must cover four ordered segments and target duration")
        if duration == 45:
            for segment, boundaries in {"hook": (0, 3), "product": (3, 20), "proof": (20, 35), "cta": (35, 45)}.items():
                part = [shot for shot in shots if shot["segment"] == segment]
                if (part[0]["startSec"], part[-1]["endSec"]) != boundaries:
                    raise PublishError("default 45-second storyboard must follow brand timing")
        if script["text"] != "\n".join(shot["voiceover"] for shot in shots):
            raise PublishError("script text must match storyboard voiceover exactly")
        mappings = script.get("sellingPointMappings")
        if not isinstance(mappings, list) or not required_points.issubset({item["customerFactRef"] for item in mappings}):
            raise PublishError("sellingPointMappings must cover every confirmed selling point")
        for mapping in mappings:
            if mapping["customerFactRef"] not in confirmed or not set(mapping["shotIds"]).issubset(ids):
                raise PublishError("selling point mapping must cite confirmed facts and existing shots")
            if not mapping["expression"].strip() or any(not shot["visual"].strip() or not shot["subtitle"].strip() for shot in shots if shot["shotId"] in mapping["shotIds"]):
                raise PublishError("selling point mapping requires an expression, visual and subtitle")
        bodies.append([{k: v for k, v in shot.items() if k != "shotId"} for shot in shots if shot["segment"] != "hook"])
    if hook_ab and any(body != bodies[0] for body in bodies[1:]):
        raise PublishError("hook comparison requires the same product/proof/cta body")
