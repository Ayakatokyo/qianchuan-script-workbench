"""The phase-one HTML must preserve trusted facts and work safely offline."""
from html.parser import HTMLParser
import importlib.util
from copy import deepcopy
import json
import shutil
import subprocess
import unittest


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": "", "parent": self.stack[-1] if self.stack else None}
        self.elements.append(element)
        if tag not in {"meta", "input", "br", "hr", "link"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for element in self.stack:
            element["text"] += data

    def find(self, tag=None, **attrs):
        return [e for e in self.elements if (not tag or e["tag"] == tag)
                and all(e["attrs"].get(key) == value for key, value in attrs.items())]


def example():
    text = "开场讲清痛点。\n" + "完整脚本内容，保留段落与细节。" * 25 + "尾句：请看看这款新品。"
    return {
        "runId": "run-中文", "acquisitionState": "partialFailed",
        "period": {"startDate": "2026-09-01", "endDate": "2026-09-07"},
        "selection": {"rankingField": "cost", "rankingLabel": "消耗", "direction": "desc", "topN": 2,
                      "rankingMetric": {"fieldId": "cost", "sourceKey": "cost", "label": "消耗", "unit": "元"},
                      "filters": [{"field": "plays", "operator": "gte", "value": 0}]},
        "counts": {"reportRows": 12, "selectedMaterials": 2, "requestedScripts": 2,
                   "availableScripts": 1, "missingScripts": 0, "failedScripts": 1,
                   "identityMismatchScripts": 1, "identityRecoveredScripts": 0},
        "fieldAvailability": {key: {"available": 1, "missing": 1} for key in ("text", "formula", "detail", "data")},
        "metricDefinitions": {"cost": {"label": "消耗", "unit": "元", "sourceKey": "cost"},
                              "plays": {"label": "播放次数", "unit": "次", "sourceKey": "plays"}},
        "materials": [
            {"materialId": "m1", "materialName": "中文 全角Ａ素材", "rank": 1, "metrics": {"cost": 0, "plays": 12},
             "sourceRefs": [{"path": "source-data/report.json", "sha256": "a" * 64}],
             "script": {"deliveryStatus": "available", "statusLabel": "已核验，可用", "textAvailable": True,
                        "fieldAvailability": {key: True for key in ("text", "formula", "detail", "data")},
                        "text": text, "textExcerpt": "开场讲清痛点。", "formula": [{"一级": "痛点", "二级": ["场景"]}],
                        "detail": {"片段": [{"正文": "结构化细节", "开始": 0}]}, "data": {"片段数": 0, "缺口": None},
                        "materialFactPath": "facts/materials/m1.json", "sourceRefs": [], "identityEvidence": []}},
            {"materialId": "m2", "materialName": "素材二", "rank": 2, "metrics": {"cost": None}, "sourceRefs": [],
             "errorCode": "material_identity_mismatch", "script": {"deliveryStatus": "identityMismatch",
                "statusLabel": "已返回脚本内容，但素材身份不一致，未采信", "textAvailable": False,
                "text": None, "formula": None, "detail": None, "data": None,
                "fieldAvailability": {key: False for key in ("text", "formula", "detail", "data")},
                "identityEvidence": [{"attempt": 1, "identityState": "mismatch", "expected": {"materialName": "素材二"},
                    "observed": {"materialName": ["素材一"]}, "mismatchedFields": ["materialName"],
                    "auditPath": "source-data/identity/m2.json", "scriptContentPresent": True,
                    "scriptContentSha256": "b" * 64}]}}
        ],
        "duplicateTextGroups": [{"materialIds": ["m1", "m2"], "textSha256": "c" * 64}],
        "gaps": [{"materialId": "m2", "message": "身份不一致，未采信", "errorCode": "material_identity_mismatch"}],
        "sourcePack": {"path": "facts/qianchuan-script-source-pack.json", "sha256": "d" * 64},
    }


class WorkbenchReportHtmlTests(unittest.TestCase):
    def render(self, summary=None):
        self.assertIsNotNone(importlib.util.find_spec("workbench_report_html"), "HTML renderer is missing")
        from workbench_report_html import render_html
        return render_html(example() if summary is None else summary)

    def test_full_script_and_structures_remain_readable_without_javascript(self):
        summary = example()
        doc = Document(self.render(summary))
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], summary["materials"][0]["script"]["text"])
        self.assertIn("结构化细节", doc.find("body")[0]["text"])
        self.assertIn("场景", doc.find("body")[0]["text"])
        self.assertTrue(doc.find("details"))
        self.assertFalse(any("hidden" in e["attrs"] for e in doc.find("article")))

    def test_zero_and_absent_metrics_are_distinct_in_comparison(self):
        doc = Document(self.render())
        cells = doc.find("td", **{"data-metric": "cost"})
        self.assertEqual([e["text"].strip() for e in cells], ["0", "未提供"])
        self.assertIn("元", doc.find("thead")[0]["text"])
        self.assertIn("2026-09-01", doc.find("body")[0]["text"])

    def test_mismatched_payload_is_never_shown_as_trusted_script(self):
        summary = example()
        script = summary["materials"][1]["script"]
        script.update(text="不能信任的正文", formula="不能信任的公式", detail="不能信任的细节", data="不能信任的数据", textAvailable=True)
        html = self.render(summary)
        self.assertNotIn("不能信任", html)
        self.assertIn("已返回脚本内容，但素材身份不一致，未采信", html)
        self.assertNotIn("partialFailed", html)
        self.assertNotIn("等待第二阶段输入", html)
        self.assertNotIn("完整性与缺口", html)
        self.assertIn("素材一", html)

    def test_missing_body_preserves_verified_structure_fields(self):
        summary = example()
        script = summary["materials"][0]["script"]
        script.update(deliveryStatus="missing", statusLabel="平台未返回可用正文", parseStatus="missing",
                      text=None, textAvailable=False)
        script["fieldAvailability"]["text"] = False
        doc = Document(self.render(summary))
        article = doc.find("article")[0]["text"]
        self.assertIn("可信脚本正文：未提供", article)
        self.assertIn("结构化细节", article)
        self.assertIn("场景", article)
        self.assertIn("片段数", article)
        self.assertFalse(doc.find("div", **{"class": "script-text"}))

    def test_html_and_script_values_cannot_create_elements_or_events(self):
        summary = example()
        attack = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
        summary["runId"] = attack
        summary["materials"][0]["materialName"] = attack
        summary["materials"][0]["script"]["text"] = attack
        summary["materials"][0]["script"]["formula"] = {attack: [attack]}
        summary["metricDefinitions"]["cost"]["label"] = attack
        html = self.render(summary)
        doc = Document(html)
        self.assertFalse(doc.find("img"))
        self.assertEqual(len(doc.find("script")), 1)
        self.assertFalse(any(key.startswith("on") for e in doc.elements for key in e["attrs"]))
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], attack)

    def test_evidence_links_are_only_encoded_paths_inside_run(self):
        summary = example()
        rejected = ["javascript:alert(1)", "https://evil.invalid/x", "//evil.invalid/x", "/etc/passwd", "../secret.json",
                    "source-data/../../secret.json", "source-data/%2e%2e/secret", "source-data\\..\\secret", "source-data/x?next=//evil", "source-data/x#target"]
        summary["materials"][0]["sourceRefs"] = [{"path": path} for path in rejected] + [{"path": "source-data/中文 报表.json"}]
        doc = Document(self.render(summary))
        hrefs = [e["attrs"]["href"] for e in doc.find("a")]
        self.assertIn("../source-data/%E4%B8%AD%E6%96%87%20%E6%8A%A5%E8%A1%A8.json", hrefs)
        self.assertIn("../facts/materials/m1.json", hrefs)
        self.assertFalse(any(href.startswith(("http:", "https:", "javascript:", "//", "/")) for href in hrefs))
        self.assertFalse(any("secret" in href or "?" in href for href in hrefs))

    def test_empty_report_keeps_honest_counts_and_no_invented_script(self):
        summary = example()
        summary.update(materials=[], counts={}, duplicateTextGroups=[], gaps=[], fieldAvailability={})
        html = self.render(summary)
        self.assertIn("暂无素材数据", html)
        self.assertIn("未提供", html)
        self.assertNotIn("class=\"script-text\"", html)

    def test_duplicate_groups_preserve_per_material_entries(self):
        doc = Document(self.render())
        self.assertEqual(len(doc.find("article")), 2)
        self.assertIn("m1", doc.find("body")[0]["text"])
        self.assertIn("m2", doc.find("body")[0]["text"])

    def test_workbench_sections_have_both_leaderboard_and_single_material_views(self):
        doc = Document(self.render())
        panels = {e["attrs"].get("data-section-panel") for e in doc.elements if "data-section-panel" in e["attrs"]}
        self.assertEqual(panels, {"filters", "materials", "scripts", "single-material", "quote-library"})
        self.assertTrue(doc.find("select", id="single-material-search") or doc.find("input", id="single-material-search"))
        self.assertTrue(doc.find("button", id="next-page"))
        self.assertTrue(doc.find("button", **{"data-sort-metric": "cost"}))

    def test_formula_coverage_uses_verified_unique_materials_and_source_labels(self):
        summary = example()
        first = summary["materials"][0]["script"]
        first["data"] = [
            {"level_1_label": {"value": 1, "label": "价格优惠"}, "level_2_labels": [{"value": 21, "label": "降价/折扣"}]},
            {"level_1_label": {"value": 1, "label": "价格优惠"}, "level_2_labels": [{"value": 21, "label": "降价/折扣"}]},
        ]
        first["detail"] = {"21": {"label": "降价/折扣", "list": ["折扣原句"]}}
        second = summary["materials"][1]["script"]
        second.update(data=first["data"], detail=first["detail"], fieldAvailability=first["fieldAvailability"])
        doc = Document(self.render(summary))
        self.assertTrue(doc.find("section", **{"data-section-panel": "scripts"}))
        panel = doc.find("section", **{"data-section-panel": "scripts"})[0]["text"]
        self.assertIn("1 个素材的内容公式", panel)
        self.assertIn("价格优惠", panel)
        self.assertIn("1 个素材 · 100%", panel)
        self.assertNotIn("2 个素材 ·", panel)
        articles = doc.find("article")
        self.assertIn("折扣原句", articles[0]["text"])
        self.assertNotIn("折扣原句", articles[1]["text"])

    def test_unknown_formula_shapes_are_readable_without_inventing_id_labels(self):
        summary = example()
        script = summary["materials"][0]["script"]
        script["formula"] = {"labels": [{"level_1_label": 999, "level_2_labels": [888]}]}
        script["data"] = [{"level_1_label": {"value": 999}, "level_2_labels": [{"value": 888}]}]
        doc = Document(self.render(summary))
        self.assertTrue(doc.find("section", **{"data-section-panel": "scripts"}))
        panel = doc.find("section", **{"data-section-panel": "scripts"})[0]["text"]
        self.assertIn("暂无可展示的内容公式标签", panel)
        self.assertIn("999", doc.find("article")[0]["text"])

    def test_rendered_interactions_filter_sort_page_and_select_material(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable for offline interaction execution")
        summary = example()
        original = summary["materials"][0]
        summary["materials"] = []
        for index in range(12):
            item = deepcopy(original)
            item.update(materialId=f"m{index}", materialName=f"中文素材{index}", rank=index + 1,
                        metrics={"cost": index if index < 11 else None})
            item["script"]["text"] = "Café 全角Ａ正文" if index == 0 else f"完整正文{index}"
            if index == 10:
                item["script"].update(deliveryStatus="identityMismatch", statusLabel="身份不一致", text=None, textAvailable=False)
            summary["materials"].append(item)
        doc = Document(self.render(summary))
        def descendants(parent, classes):
            values = []
            for element in doc.elements:
                cursor = element.get("parent")
                while cursor:
                    if cursor is parent:
                        if element["attrs"].get("class") in classes:
                            values.append(element["text"])
                        break
                    cursor = cursor.get("parent")
            return values
        cards = [{"attrs": element["attrs"], "search": descendants(element, {"material-name", "material-id", "script-text"})} for element in doc.find("article")]
        rows = []
        for row in doc.find("tr", **{"class": "material-row"}):
            cells = [e for e in doc.elements if e.get("parent") is row and "data-metric" in e["attrs"]]
            rows.append({"attrs": row["attrs"], "cells": [{"attrs": e["attrs"], "text": e["text"]} for e in cells]})
        payload = {"cards": cards, "rows": rows, "elements": [{"attrs": e["attrs"], "text": e["text"]} for e in doc.elements if e["tag"] != "script"]}
        runner = r"""
const payload = PAYLOAD;
function element(attrs = {}, text = "") {
  const classes = new Set((attrs.class || "").split(" "));
  const el = {attrs, dataset: {}, textContent: text, hidden: "hidden" in attrs, value: "", disabled: false,
    classList: {toggle(name, on) {on ? classes.add(name) : classes.delete(name);}, contains(name) {return classes.has(name);}},
    setAttribute(name, value) {this.attrs[name] = value;}, removeAttribute(name) {delete this.attrs[name];}};
  for (const [key, value] of Object.entries(attrs)) if (key.startsWith("data-")) el.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
  return el;
}
const elements = payload.elements.map(item => element(item.attrs, item.text));
const controls = new Map(elements.filter(item => item.attrs.id).map(item => [item.attrs.id, item]));
controls.get("status-filter").value = "all";
const cards = payload.cards.map(item => {const el = element(item.attrs);el.querySelectorAll = () => item.search.map(textContent => ({textContent}));return el;});
const rows = payload.rows.map(item => {const el = element(item.attrs);el.querySelectorAll = () => item.cells.map(cell => element(cell.attrs, cell.text));return el;});
const nav = elements.filter(item => "section" in item.dataset);
const panels = elements.filter(item => "sectionPanel" in item.dataset);
const options = elements.filter(item => item.attrs.class === "material-option");
const openers = elements.filter(item => "openMaterial" in item.dataset);
const sortButtons = elements.filter(item => "sortMetric" in item.dataset);
for (const button of sortButtons) {const marker={textContent:""};button.querySelector = () => marker;}
let order = [];
controls.get("material-rows").appendChild = row => {order = order.filter(item => item !== row);order.push(row);};
const queries = {"[data-section-panel]":panels,"[data-section]":nav,".material-card":cards,".material-row":rows,".material-option":options,"[data-open-material]":openers,"[data-sort-metric]":sortButtons};
global.document = {getElementById:id => controls.get(id),querySelectorAll:selector => queries[selector] || []};
SCRIPT
const check = (value, message) => {if (!value) throw Error(message);};
const visibleRows = () => order.filter(row => !row.hidden).map(row => Number(row.dataset.index));
check(panels.find(panel => panel.dataset.sectionPanel === "filters").hidden === false, "Default section");
check(rows.filter(row => !row.hidden).length === 10, "Initial ten rows");
controls.get("next-page").onclick();
check(JSON.stringify(visibleRows()) === "[10,11]", "Next page");
controls.get("material-search").value = "ｃａｆé";controls.get("material-search").oninput();
check(JSON.stringify(visibleRows()) === "[0]", "Unicode search");
controls.get("material-search").value = "";controls.get("material-search").oninput();
controls.get("status-filter").value = "identityMismatch";controls.get("status-filter").onchange();
check(JSON.stringify(visibleRows()) === "[10]", "Status filter");
controls.get("status-filter").value = "all";controls.get("status-filter").onchange();
sortButtons.find(button => button.dataset.sortMetric === "cost").onclick();
check(visibleRows()[0] === 10 && !visibleRows().includes(11), "Descending and null-last sorting");
sortButtons.find(button => button.dataset.sortMetric === "cost").onclick();
check(visibleRows()[0] === 0, "Zero survives ascending sort");
openers.find(button => button.dataset.openMaterial === "4").onclick({preventDefault(){}});
check(cards.filter(card => !card.hidden).length === 1 && !cards[4].hidden, "Single material selection");
check(!panels.find(panel => panel.dataset.sectionPanel === "single-material").hidden, "Selection enters detail");
controls.get("single-material-search").value = "中文素材11";controls.get("single-material-search").oninput();
check(options.filter(option => !option.hidden).length === 1 && !options[11].hidden, "Sidebar search");
controls.get("material-search").value = "不存在";controls.get("material-search").oninput();
check(!controls.get("no-results").hidden && visibleRows().length === 0, "Empty search state");
""".replace("PAYLOAD", json.dumps(payload, ensure_ascii=False)).replace("SCRIPT", doc.find("script")[0]["text"])
        result = subprocess.run([node, "-e", runner], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == "__main__":
    unittest.main()
