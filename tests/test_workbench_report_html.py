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

    def test_full_script_remains_readable_without_raw_or_audit_panels(self):
        summary = example()
        doc = Document(self.render(summary))
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], summary["materials"][0]["script"]["text"])
        self.assertNotIn("平台原始结构", doc.find("body")[0]["text"])
        self.assertNotIn("身份核对与数据来源", doc.find("body")[0]["text"])
        self.assertNotIn("结构化细节", doc.find("body")[0]["text"])
        self.assertFalse(doc.find("details", **{"class": "raw-fields"}))
        self.assertFalse(doc.find("details", **{"class": "evidence"}))
        self.assertFalse(any("hidden" in e["attrs"] for e in doc.find("article")))

    def test_zero_and_absent_metrics_are_distinct_in_comparison(self):
        doc = Document(self.render())
        cells = doc.find("td", **{"data-metric": "cost"})
        self.assertEqual([e["text"].strip() for e in cells], ["0", "未提供"])
        self.assertIn("元", doc.find("thead")[0]["text"])
        self.assertIn("2026-09-01", doc.find("body")[0]["text"])

    def test_leaderboard_defaults_use_available_meta_metric_columns_in_meta_order(self):
        summary = example()
        summary["leaderboard"] = {
            "materials": [{"materialId": "m1", "materialName": "素材一", "metrics": {
                "stat_cost_for_roi2": 9,
                "total_order_settle_amount_for_roi2_1h": 3,
                "stat_cost_for_overall_roi2": 7,
                "total_prepay_and_pay_settle_roi2_1h": 2,
            }}],
            "metricDefinitions": {key: {"label": key, "group": "整体指标"} for key in (
                "stat_cost_for_roi2", "total_order_settle_amount_for_roi2_1h",
                "stat_cost_for_overall_roi2", "total_prepay_and_pay_settle_roi2_1h")},
        }
        doc = Document(self.render(summary))
        expected = ["stat_cost_for_overall_roi2", "total_prepay_and_pay_settle_roi2_1h",
                    "total_order_settle_amount_for_roi2_1h"]
        self.assertEqual([item["attrs"]["data-column"] for item in doc.find("th") if "data-column" in item["attrs"]], expected)
        self.assertEqual(json.loads(doc.find("dialog")[0]["attrs"]["data-default-selection"]), expected)
        self.assertEqual(len(doc.find("a", **{"data-section": "quote-library"})), 1)

    def test_single_delivery_matches_meta_defaults_and_current_material_fields(self):
        from workbench_metric_picker import SINGLE_DEFAULT_IDS
        summary = example()
        first_values = {key: index + 1000 for index, key in enumerate(SINGLE_DEFAULT_IDS)}
        first_values.update(extra_metric=0, video_play_count_for_roi2_v2=77)
        second_values = {"other_a": 0, "other_b": 2, "other_c": None}
        summary["materials"][0]["metrics"] = {"script_only": 42}
        summary["materials"][1]["metrics"] = {}
        summary["metricDefinitions"]["script_only"] = {"label": "仅脚本素材指标", "sourceKey": "script_only"}
        summary["leaderboard"] = {
            "materials": [
                {"materialId": "m1", "metrics": first_values,
                 "metricDisplay": {**first_values, "stat_cost_for_overall_roi2": "1,234.50",
                                   "stat_cost_for_roi2": None, "total_pay_order_count_for_roi2": "",
                                   "extra_metric": "0.00%"}},
                {"materialId": "m2", "metrics": second_values},
            ],
            "metricDefinitions": {key: {"label": f"指标 {key}", "group": "整体指标"}
                                  for key in (*first_values, *second_values)},
        }
        doc = Document(self.render(summary))
        cards = doc.find("article", **{"class": "material-card"})

        def within(card, data_key):
            result = []
            for element in doc.elements:
                parent = element.get("parent")
                while parent:
                    if parent is card:
                        if data_key in element["attrs"]:
                            result.append(element)
                        break
                    parent = parent.get("parent")
            return result

        self.assertEqual(json.loads(cards[0]["attrs"]["data-single-defaults"]), [
            "stat_cost_for_overall_roi2", "total_order_settle_amount_for_roi2_1h",
            "stat_cost_for_roi2", "total_prepay_and_pay_settle_roi2_1h",
            "total_pay_order_count_for_roi2", "live_show_count_for_roi2_v2",
            "live_cvr_rate_for_roi2_v2", "live_watch_count_for_roi2_v2",
        ])
        first_metrics = within(cards[0], "data-single-metric")
        self.assertEqual(len(first_metrics), 11)
        self.assertEqual(sum("hidden" not in item["attrs"] for item in first_metrics), 8)
        self.assertIn("已展示指标 8 / 11", cards[0]["text"])
        self.assertEqual(next(item for item in first_metrics if item["attrs"]["data-single-metric"] == "stat_cost_for_overall_roi2")["text"],
                         "指标 stat_cost_for_overall_roi21,234.50")
        for key, raw in (("stat_cost_for_roi2", "1,001"), ("total_pay_order_count_for_roi2", "1,002")):
            self.assertEqual(next(item for item in first_metrics if item["attrs"]["data-single-metric"] == key)["text"],
                             f"指标 {key}{raw}")
        self.assertIn("hidden", next(item for item in first_metrics if item["attrs"]["data-single-metric"] == "extra_metric")["attrs"])
        extra_choice = doc.find("input", **{"data-pick-metric": "script_only"})[0]
        self.assertEqual(extra_choice["attrs"]["data-leaderboard-choice"], "false")
        self.assertIn("hidden", extra_choice["parent"]["attrs"])
        self.assertEqual(json.loads(cards[1]["attrs"]["data-single-defaults"]), list(second_values))
        self.assertEqual(len(within(cards[1], "data-single-metric")), 3)
        self.assertIn("已展示指标 3 / 3", cards[1]["text"])
        self.assertEqual(next(item for item in within(cards[1], "data-single-metric")
                              if item["attrs"]["data-single-metric"] == "other_c")["text"], "指标 other_c—")
        self.assertEqual(len(within(cards[0], "data-single-metric-button")), 1)
        self.assertNotIn("核心指标", cards[0]["text"])

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
        self.assertNotIn("素材一", html)

    def test_missing_body_keeps_readable_formula_without_raw_structure(self):
        summary = example()
        script = summary["materials"][0]["script"]
        script.update(deliveryStatus="missing", statusLabel="平台未返回可用正文", parseStatus="missing",
                      text=None, textAvailable=False)
        script["fieldAvailability"]["text"] = False
        script["data"] = [{"level_1_label": {"value": 1, "label": "商品卖点"}, "level_2_labels": [{"value": 2, "label": "适用场景"}]}]
        doc = Document(self.render(summary))
        article = doc.find("article")[0]["text"]
        self.assertIn("可信脚本正文：未提供", article)
        self.assertIn("商品卖点", article)
        self.assertIn("适用场景", article)
        self.assertNotIn("结构化细节", article)
        self.assertNotIn("片段数", article)
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

    def test_source_and_audit_paths_are_not_exposed_in_report(self):
        summary = example()
        rejected = ["javascript:alert(1)", "https://evil.invalid/x", "//evil.invalid/x", "/etc/passwd", "../secret.json",
                    "source-data/../../secret.json", "source-data/%2e%2e/secret", "source-data\\..\\secret", "source-data/x?next=//evil", "source-data/x#target"]
        summary["materials"][0]["sourceRefs"] = [{"path": path} for path in rejected] + [{"path": "source-data/中文 报表.json"}]
        doc = Document(self.render(summary))
        hrefs = [e["attrs"]["href"] for e in doc.find("a")]
        self.assertTrue(all(href.startswith("#") for href in hrefs))
        self.assertNotIn("source-data/", doc.find("body")[0]["text"])
        self.assertNotIn("facts/materials/", doc.find("body")[0]["text"])
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
        self.assertEqual(doc.find("div", id="scope-switch")[0]["attrs"]["aria-label"], "素材数据口径")
        self.assertEqual([(button["attrs"]["data-scope"], button["text"], button["attrs"]["aria-pressed"])
                          for button in doc.find("button") if "data-scope" in button["attrs"]],
                         [("all", "全量素材", "true"), ("detail", "详情素材", "false")])
        self.assertEqual({e["attrs"]["data-section"] for e in doc.find("a") if "data-detail-section" in e["attrs"]},
                         {"scripts", "single-material", "quote-library"})
        self.assertTrue(doc.find("select", id="single-material-search") or doc.find("input", id="single-material-search"))
        self.assertTrue(doc.find("button", id="next-page"))
        self.assertTrue(doc.find("button", **{"data-sort-metric": "cost"}))
        self.assertFalse(doc.find("select", id="status-filter"))
        self.assertNotIn("脚本状态", doc.find("thead")[0]["text"])
        self.assertNotIn("排名", doc.find("thead")[0]["text"])
        self.assertEqual(len(doc.find("th")), 3)

    def test_formula_coverage_uses_verified_unique_materials_and_source_labels(self):
        summary = example()
        first = summary["materials"][0]["script"]
        first["data"] = [
            {"level_1_label": {"value": 1, "label": "价格优惠"}, "level_2_labels": [{"value": 21, "label": "降价/折扣"}]},
            {"level_1_label": {"value": 1, "label": "价格优惠"}, "level_2_labels": [{"value": 21, "label": "降价/折扣"}]},
        ]
        first["detail"] = {"21": {"label": "降价/折扣", "list": ["折扣原句"]}}
        first["text"] = "真实正文中的折扣原句。"
        second = summary["materials"][1]["script"]
        second.update(data=first["data"], detail=first["detail"], fieldAvailability=first["fieldAvailability"])
        doc = Document(self.render(summary))
        self.assertTrue(doc.find("section", **{"data-section-panel": "scripts"}))
        panel = doc.find("section", **{"data-section-panel": "scripts"})[0]["text"]
        self.assertNotIn("1 个素材的内容公式", panel)
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
        self.assertNotIn("999", doc.find("article")[0]["text"])
        self.assertNotIn("888", doc.find("article")[0]["text"])

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
            if index == 0:
                item["materialName"] = "Café 全角Ａ素材"
            item["script"]["text"] = f"正文专属关键词{index}"
            if index == 10:
                item["script"].update(deliveryStatus="identityMismatch", statusLabel="身份不一致", text=None, textAvailable=False)
            summary["materials"].append(item)
        summary["leaderboard"] = {"materials": [
            {"materialId": item["materialId"], "materialName": item["materialName"], "metrics": item["metrics"]}
            for item in summary["materials"]] + [
            {"materialId": "full-only", "materialName": "未采集详情", "metrics": {"cost": None}}
        ]}
        doc = Document(self.render(summary))
        self.assertEqual([row["attrs"]["data-detail-material"] for row in doc.find("tr", **{"class": "material-row"})],
                         ["true"] * 12 + ["false"])
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
        cards = [{"attrs": element["attrs"], "search": descendants(element, {"material-name", "material-id"})} for element in doc.find("article")]
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
const queries = {"[data-section-panel]":panels,"[data-section]":nav,"[data-detail-section]":nav.filter(link => "detailSection" in link.dataset),"[data-scope]":elements.filter(item => "scope" in item.dataset),".material-card":cards,".material-row":rows,".material-option":options,"[data-open-material]":openers,"[data-sort-metric]":sortButtons};
global.document = {getElementById:id => controls.get(id),querySelectorAll:selector => queries[selector] || []};
SCRIPT
const check = (value, message) => {if (!value) throw Error(message);};
const visibleRows = () => order.filter(row => !row.hidden).map(row => Number(row.dataset.index));
check(panels.find(panel => panel.dataset.sectionPanel === "filters").hidden === false, "Default section");
check(rows.filter(row => !row.hidden).length === 10, "Initial ten rows");
check(nav.filter(link => "detailSection" in link.dataset).every(link => link.hidden), "Full scope hides detail tabs");
nav.find(link => link.dataset.section === "materials").onclick({preventDefault(){}});
check(!panels.find(panel => panel.dataset.sectionPanel === "materials").hidden, "Full leaderboard opened");
controls.get("next-page").onclick();
check(JSON.stringify(visibleRows()) === "[10,11,12]", "Full scope includes uncollected report row");
controls.get("scope-detail").onclick();
check(controls.get("scope-detail").attrs["aria-pressed"] === "true" && controls.get("scope-all").attrs["aria-pressed"] === "false", "Detail scope selected");
check(!panels.find(panel => panel.dataset.sectionPanel === "materials").hidden, "Switch retains leaderboard section");
check(nav.filter(link => "detailSection" in link.dataset).every(link => !link.hidden), "Detail scope shows existing tabs");
check(controls.get("materials-tab").textContent === "详情素材榜单", "Detail leaderboard label");
controls.get("next-page").onclick();
check(JSON.stringify(visibleRows()) === "[10,11]", "Detail scope includes only collected materials");
controls.get("scope-all").onclick();
check(controls.get("scope-all").attrs["aria-pressed"] === "true" && controls.get("scope-detail").attrs["aria-pressed"] === "false", "Full scope restored");
check(!panels.find(panel => panel.dataset.sectionPanel === "materials").hidden, "Returning to full retains leaderboard section");
controls.get("material-search").value = "ｃａｆé";controls.get("material-search").oninput();
check(JSON.stringify(visibleRows()) === "[0]", "Unicode search");
controls.get("material-search").value = "";controls.get("material-search").oninput();
check(!controls.has("status-filter"), "No status control");
controls.get("material-search").value = "正文专属关键词";controls.get("material-search").oninput();
check(visibleRows().length === 0, "Title and ID search only");
controls.get("material-search").value = "";controls.get("material-search").oninput();
sortButtons.find(button => button.dataset.sortMetric === "cost").onclick();
check(visibleRows()[0] === 0 && !visibleRows().includes(11), "Zero survives ascending and null-last sorting");
sortButtons.find(button => button.dataset.sortMetric === "cost").onclick();
check(visibleRows()[0] === 10 && !visibleRows().includes(11), "Descending and null-last sorting");
openers.find(button => button.dataset.openMaterial === "4").onclick({preventDefault(){}});
check(cards.filter(card => !card.hidden).length === 1 && !cards[4].hidden, "Single material selection");
check(!panels.find(panel => panel.dataset.sectionPanel === "single-material").hidden, "Selection enters detail");
check(controls.get("scope-detail").attrs["aria-pressed"] === "true", "Leaderboard link switches to detail scope");
controls.get("single-material-search").value = "中文素材11";controls.get("single-material-search").oninput();
check(options.filter(option => !option.hidden).length === 1 && !options[11].hidden, "Sidebar search");
controls.get("scope-all").onclick();
check(!panels.find(panel => panel.dataset.sectionPanel === "filters").hidden, "Returning to full scope shows shared filters");
check(nav.filter(link => "detailSection" in link.dataset).every(link => link.hidden), "Returning to full hides detail tabs");
controls.get("material-search").value = "不存在";controls.get("material-search").oninput();
check(!controls.get("no-results").hidden && visibleRows().length === 0, "Empty search state");
""".replace("PAYLOAD", json.dumps(payload, ensure_ascii=False)).replace("SCRIPT", doc.find("script")[0]["text"])
        result = subprocess.run([node, "-e", runner], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == "__main__":
    unittest.main()
