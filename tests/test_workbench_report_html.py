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
        from workbench_report_html import render_html
        return render_html(example() if summary is None else summary)

    @staticmethod
    def model(html):
        import re
        data = re.search(r'<script id="workbench-model" type="application/json">(.*?)</script>', html)
        assert data, 'embedded workbench model missing'
        return json.loads(data.group(1))

    def test_single_page_uses_only_details_and_keeps_full_script_fallback(self):
        summary = example()
        summary['leaderboard'] = {'materials': [{'materialId': 'full-only', 'materialName': '仅全量素材'}]}
        html = self.render(summary)
        doc = Document(html)
        model = self.model(html)
        self.assertEqual([item['id'] for item in model['materials']], ['m1', 'm2'])
        self.assertEqual(doc.find('pre')[0]['text'], summary['materials'][0]['script']['text'])
        self.assertNotIn('仅全量素材', html)
        self.assertNotIn('来源原句', html)
        self.assertNotIn('脚本片段库', html)
        self.assertNotIn('查找名称或 ID', html)
        self.assertEqual([node['attrs'].get('id') for node in doc.find('nav')], ['quote-pagination'])
        self.assertFalse(doc.find('table'))
        self.assertEqual(len(doc.find('dialog')), 1)

    def test_identity_mismatch_never_enters_script_or_formula(self):
        summary = example()
        summary['materials'][1]['script'].update(text='不能信任的正文', data='不能信任的数据',
                                                  detail='不能信任的细节', textAvailable=True)
        html = self.render(summary)
        model = self.model(html)
        self.assertEqual(model['materials'][1]['text'], '')
        self.assertEqual(model['materials'][1]['formula'], [])
        self.assertNotIn('不能信任', html)
        self.assertNotIn('partialFailed', html)

    def test_metrics_keep_defaults_actual_fields_and_display_zero(self):
        from workbench_metric_picker import SINGLE_DEFAULT_IDS
        summary = example()
        first_values = {key: index + 1000 for index, key in enumerate(SINGLE_DEFAULT_IDS)}
        first_values.update(extra_metric=0, video_play_count_for_roi2_v2=77)
        second_values = {'other_a': 0, 'other_b': 2, 'other_c': None}
        summary['materials'][0]['metrics'] = {'script_only': 42}
        summary['materials'][1]['metrics'] = {}
        summary['metricDefinitions']['script_only'] = {'label': '仅脚本素材指标', 'sourceKey': 'script_only'}
        summary['leaderboard'] = {
            'materials': [
                {'materialId': 'm1', 'metrics': first_values,
                 'metricDisplay': {**first_values, 'stat_cost_for_overall_roi2': '1,234.50',
                                   'stat_cost_for_roi2': None, 'total_pay_order_count_for_roi2': '',
                                   'extra_metric': '0.00%'}},
                {'materialId': 'm2', 'metrics': second_values},
            ],
            'metricDefinitions': {key: {'label': f'指标 {key}', 'group': '整体指标'}
                                  for key in (*first_values, *second_values)},
        }
        model = self.model(self.render(summary))
        first, second = model['materials']
        default = [field['id'] for field in first['metrics'] if field['default']]
        self.assertEqual(default, [
            'stat_cost_for_overall_roi2', 'total_order_settle_amount_for_roi2_1h',
            'stat_cost_for_roi2', 'total_prepay_and_pay_settle_roi2_1h',
            'total_pay_order_count_for_roi2', 'live_show_count_for_roi2_v2',
            'live_cvr_rate_for_roi2_v2', 'live_watch_count_for_roi2_v2'])
        self.assertEqual(len(first['metrics']), 11)
        by_id = {field['id']: field for field in first['metrics']}
        self.assertEqual(by_id['stat_cost_for_overall_roi2']['value'], '1,234.50')
        self.assertEqual(by_id['stat_cost_for_roi2']['value'], '1,001')
        self.assertEqual(by_id['extra_metric']['value'], '0.00%')
        self.assertFalse(by_id['extra_metric']['default'])
        self.assertEqual([field['value'] for field in second['metrics']], ['0', '2', '—'])
        self.assertTrue(all(field['default'] for field in second['metrics']))

    def test_formula_labels_are_trusted_and_terms_exact(self):
        summary = example()
        first = summary['materials'][0]['script']
        first['text'] = '真实正文中的折扣原句。'
        first['data'] = [
            {'level_1_label': {'value': 1, 'label': '价格优惠'},
             'level_2_labels': [{'value': 21, 'label': '降价/折扣'}]},
            {'level_1_label': {'value': 1, 'label': '价格优惠'},
             'level_2_labels': [{'value': 21, 'label': '降价/折扣'}]},
        ]
        first['detail'] = {'21': {'label': '降价/折扣', 'list': ['折扣原句', '不在正文']}}
        model = self.model(self.render(summary))
        groups = model['materials'][0]['formula']
        self.assertEqual([group['label'] for group in groups], ['价格优惠', '价格优惠'])
        self.assertEqual(groups[0]['children'][0]['terms'], ['折扣原句'])
        self.assertEqual(model['materials'][1]['formula'], [])
        first['data'] = [{'level_1_label': {'value': 999}, 'level_2_labels': [{'value': 888}]}]
        self.assertEqual(self.model(self.render(summary))['materials'][0]['formula'], [])

    def test_empty_and_missing_body_keep_honest_fallback(self):
        summary = example()
        summary['materials'] = []
        html = self.render(summary)
        self.assertEqual(self.model(html)['materials'], [])
        self.assertNotIn('class="script-text"', html)
        summary = example()
        script = summary['materials'][0]['script']
        script.update(deliveryStatus='missing', text=None, textAvailable=False,
                      data=[{'level_1_label': {'value': 1, 'label': '商品卖点'},
                             'level_2_labels': [{'value': 2, 'label': '适用场景'}]}])
        script['fieldAvailability']['text'] = False
        model = self.model(self.render(summary))
        self.assertEqual(model['materials'][0]['text'], '')
        self.assertEqual(model['materials'][0]['formula'][0]['label'], '商品卖点')

    def test_scope_supports_additional_filters_and_single_row_chart(self):
        summary = example()
        summary['selection']['filters'].append({'label': '点击率', 'operator': 'gt', 'value': 0.03})
        html = self.render(summary)
        scope = self.model(html)['scope']
        self.assertIn(['选材筛选条件 1', 'plays ≥ 0'], scope)
        self.assertIn(['选材筛选条件 2', '点击率 > 0.03'], scope)
        self.assertIn('width:max-content;min-width:100%;margin:0 auto', html)
        self.assertNotIn('点二级步骤可在中间完整脚本中定位已核对的原句。', html)
        self.assertNotIn('source-filter', html)
        self.assertNotIn('item-search', html)

    def test_embedded_values_cannot_create_elements_or_expose_paths(self):
        summary = example()
        attack = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
        summary['materials'][0]['materialName'] = attack
        summary['materials'][0]['script']['text'] = attack
        summary['metricDefinitions']['cost']['label'] = attack
        summary['materials'][0]['sourceRefs'] = [{'path': 'https://evil.invalid/secret'}]
        html = self.render(summary)
        doc = Document(html)
        self.assertFalse(doc.find('img'))
        self.assertEqual(len(doc.find('script')), 2)
        self.assertFalse(any(key.startswith('on') for item in doc.elements for key in item['attrs']))
        self.assertEqual(self.model(html)['materials'][0]['text'], attack)
        self.assertNotIn('https://evil.invalid', html)
        self.assertNotIn('facts/materials/', html)

    def test_page_script_has_valid_syntax(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js unavailable')
        from script_workbench_page import SCRIPT
        with subprocess.Popen([node, '--check'], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            _, stderr = process.communicate(SCRIPT)
            self.assertEqual(process.returncode, 0, stderr)


if __name__ == '__main__':
    unittest.main()
