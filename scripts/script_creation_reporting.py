"""Write synchronized human-readable and machine-readable generation evidence."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
from typing import Any, Mapping

from qianchuan_script_acquisition_receipt import atomic_json


def _overlap_warnings(draft: Mapping[str, Any], references: Mapping[str, Any]) -> list[str]:
    reference_texts = [str(item.get("text") or "") for item in references.get("scripts", []) if isinstance(item, Mapping)]
    warnings = []
    for index, script in enumerate(draft.get("scripts", []), 1):
        text = str(script.get("text") or "")
        if any(SequenceMatcher(None, text, reference).ratio() >= 0.8 for reference in reference_texts if reference):
            warnings.append(f"variant {index} has high text-overlap risk with a Qianchuan reference")
    return warnings


def reference_analysis_report_lines(draft: Mapping[str, Any]) -> list[str]:
    analyses = draft.get("referenceAnalyses") or []
    if not analyses:
        return []
    lines = ["", "## Platform formula and transcript analysis", "", "Platform labels are observations, not customer-confirmed product facts; comparisons and borrowing methods are model inferences, not causal performance claims."]
    labels = {
        "opening": "Opening", "sellingPointProgression": "Selling point progression",
        "evidence": "Evidence expression", "callToAction": "Call to action",
    }
    for reference in analyses:
        lines.extend(["", f"### Reference `{reference['referenceRef']}`", ""])
        for item in reference.get("materialAnalyses", []):
            observations = item["platformObservations"]
            lines.extend([
                f"#### Material `{item['materialId']}` · `{item['evidenceMode']}`",
                "",
                f"- Platform formula: {observations['formula'] if observations['formula'] is not None else 'missing'}",
                f"- Platform detail: {observations['detail'] if observations['detail'] is not None else 'missing'}",
                f"- Platform data: {observations['data'] if observations['data'] is not None else 'missing'}",
                f"- Transcript: {observations['transcript']}",
                "",
                "| Dimension | Alignment | Platform basis | Transcript basis | Model inference |",
                "| --- | --- | --- | --- | --- |",
            ])
            for key, label in labels.items():
                result = item["comparison"][key]
                values = [label, result["alignment"], result["platformBasis"], result["transcriptBasis"], result["modelInference"]]
                lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", "<br>") for value in values) + " |")
            lines.extend([
                "",
                f"- Borrowable structure method: {item['borrowableMethod']}",
                "- Field sources: " + json.dumps(item["fieldSources"], ensure_ascii=False, sort_keys=True),
            ])
    return lines


def write_generation_evidence(analysis_dir: Path, draft: dict[str, Any]) -> None:
    analysis_dir = Path(analysis_dir)
    references = json.loads((analysis_dir / "reference-selection.json").read_text(encoding="utf-8"))
    warnings = _overlap_warnings(draft, references)
    status = draft["status"]
    report_lines = ["# Generated script report", "", f"- status: `{status}`", f"- analysisId: `{draft['analysisId']}`", "- result: model-produced draft remains subject to human review.", "", "## Checks", "", f"- variants: {len(draft.get('scripts', []))}", f"- customer facts: {draft.get('checks', {}).get('customerFactsComplete')}", f"- reference scripts: {draft.get('checks', {}).get('referencesAvailable')}", f"- non-causal boundary: {draft.get('nonCausalBoundary', '')}"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", "<br>")
    report_lines.extend(reference_analysis_report_lines(draft))
    if (analysis_dir / "brand-profile.json").is_file():
        request = json.loads((analysis_dir / "request.json").read_text(encoding="utf-8"))
        target = request["target"]
        report_lines.extend(["", "## 产品与创作方向", "",
                             f"- 产品：{target.get('productName', '待确认')}；人群：{target.get('audience', '待确认')}",
                             f"- 创作模式：{target.get('generationMode', 'exploration')}；促销状态：{target.get('promotionStatus', 'unknown')}",
                             "- 画面、音效和 BGM 均为拍摄建议；参考学习仅有文本依据。"])
        report_lines.extend(["", "## 参考文本学习", ""])
        for learning in draft.get("referenceLearnings", []):
            report_lines.append(f"- {learning['referenceRef']}：{learning['technique']}；品牌改造：{learning['adaptation']}")
        report_lines.extend(f"- 参考缺口：{warning}" for warning in references.get("warnings", []))
    if draft.get("missing"):
        report_lines.extend(["", "## 待确认", "", *[f"- {item}" for item in draft["missing"]]])
    for script in draft["scripts"]:
        report_lines.extend(["", "## " + script["title"], "", script["text"], ""])
        if script.get("sellingPointMappings"):
            report_lines.extend(["| 卖点事实 ID | 表达方式 | 落地镜头 | 画面/动作 | 字幕 |", "| --- | --- | --- | --- | --- |"])
            shots_by_id = {shot["shotId"]: shot for shot in script["shots"]}
            for mapping in script["sellingPointMappings"]:
                matched = [shots_by_id[identifier] for identifier in mapping["shotIds"]]
                values = [mapping["customerFactRef"], mapping["expression"], ", ".join(mapping["shotIds"]), "\n".join(shot["visual"] for shot in matched), "\n".join(shot["subtitle"] for shot in matched)]
                report_lines.append("| " + " | ".join(cell(value) for value in values) + " |")
            report_lines.append("")
        if script.get("shots"):
            report_lines.extend(["| 镜头序号 | 时间轴（秒） | 画面/动作 | 口播逐字稿 | 字幕/贴纸/特效 | 音效/BGM |", "| --- | --- | --- | --- | --- | --- |"])
            for shot in script["shots"]:
                values = [shot["shotId"], f"{shot['startSec']}–{shot['endSec']}", shot["visual"], shot["voiceover"], shot["subtitle"], shot["audio"]]
                report_lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    if warnings:
        report_lines.extend(["", "## Text-overlap warnings", "", *[f"- {warning}" for warning in warnings]])
    (analysis_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    atomic_json(analysis_dir / "receipt.json", {"schemaVersion": 1, "runId": draft["runId"], "analysisId": draft["analysisId"], "status": status, "inputHashes": draft["inputHashes"], "outputs": ["generated-scripts.json", "report.md", "receipt.json", "status.json"]})
    atomic_json(analysis_dir / "status.json", {"schemaVersion": 1, "runId": draft["runId"], "analysisId": draft["analysisId"], "state": status})


__all__ = ["reference_analysis_report_lines", "write_generation_evidence"]
