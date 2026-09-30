"""Self-contained HTML projection of verified phase-one Qianchuan script facts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from workbench_metric_picker import default_single_columns
from script_workbench_page import render_page, _scope_filters


def _single_metric_value(value: Any) -> str:
    """Use the platform display string, or the meta report's numeric style."""
    if value is None or value == "":
        return "—"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _metric_columns(summary: Mapping[str, Any], materials: list) -> list[dict]:
    selection = summary.get('selection') or {}
    ranking = selection.get('rankingMetric') or {}
    definitions = summary.get('metricDefinitions') or {}
    keys = []
    ranking_key = ranking.get('sourceKey') or selection.get('rankingField')
    if ranking_key:
        keys.append(ranking_key)
    for material in materials:
        for key in (material.get('metrics') or {}):
            if key not in keys:
                keys.append(key)
    columns = []
    for key in keys:
        definition = definitions.get(key) or next((item for item in definitions.values() if item.get('sourceKey') == key), {})
        if key == ranking_key:
            definition = {**ranking, **definition}
        columns.append({'key': key, 'label': definition.get('label') or key, 'unit': definition.get('unit'), 'group': definition.get('group', '其他指标')})
    return columns


def _single_metric_order(columns: list[dict]) -> list[dict]:
    """Use the same field registry order as the meta skill's detail cards."""
    path = Path(__file__).resolve().parent.parent / 'config/report-metric-labels.json'
    fields = json.loads(path.read_text(encoding='utf-8'))['fields']
    order = {field['id']: index for index, field in enumerate(fields)}
    return [column for _, column in sorted(enumerate(columns),
                                           key=lambda pair: (order.get(pair[1]['key'], len(order)), pair[0]))]


def _trusted_field(script: Mapping[str, Any], field: str) -> Any:
    if script.get('deliveryStatus') not in {'available', 'missing'}:
        return None
    return script.get(field) if (script.get('fieldAvailability') or {}).get(field) else None


def _formula_groups(script: Mapping[str, Any]) -> list[dict]:
    """Interpret only explicit platform labels; numeric IDs are not labels."""
    data = _trusted_field(script, 'data')
    if not isinstance(data, list):
        return []
    groups = []
    detail = _trusted_field(script, 'detail')
    detail = detail if isinstance(detail, Mapping) else {}
    for item in data:
        if not isinstance(item, Mapping):
            continue
        primary = item.get('level_1_label')
        if not isinstance(primary, Mapping) or not isinstance(primary.get('label'), str) or not primary['label'].strip():
            continue
        children = []
        raw_children = item.get('level_2_labels')
        for child in raw_children if isinstance(raw_children, list) else []:
            if not isinstance(child, Mapping) or not isinstance(child.get('label'), str) or not child['label'].strip():
                continue
            child_detail = detail.get(str(child.get('value')))
            child_detail = child_detail if isinstance(child_detail, Mapping) else {}
            children.append({'label': child['label'], 'id': child.get('value'),
                             'detailLabel': child_detail.get('label') or child['label'],
                             'quotes': child_detail.get('list')})
        groups.append({'label': primary['label'], 'id': primary.get('value'), 'children': children})
    return groups


def render_html(summary: Mapping[str, Any]) -> str:
    """Render the verified detail materials as one script workbench page."""
    materials = summary.get('materials') or []
    leaderboard = summary.get('leaderboard') or {}
    by_id = {str(row.get('materialId')): row for row in leaderboard.get('materials') or []}
    merged = [{**row, 'metrics': {**(row.get('metrics') or {}),
               **(by_id.get(str(row.get('materialId'))) or {}).get('metrics', {})}}
              for row in materials]
    definitions = {**(summary.get('metricDefinitions') or {}),
                   **(leaderboard.get('metricDefinitions') or {})}
    columns = _single_metric_order(_metric_columns({**summary, 'metricDefinitions': definitions}, merged))
    page_materials = []
    for row in materials:
        material_id = str(row.get('materialId'))
        script = row.get('script') or {}
        text = _trusted_field(script, 'text')
        text = text if isinstance(text, str) else ''
        report_row = by_id.get(material_id) or {}
        raw_metrics = {**(row.get('metrics') or {}), **(report_row.get('metrics') or {})}
        display_metrics = {**raw_metrics, **(row.get('metricDisplay') or {}),
                           **(report_row.get('metricDisplay') or {})}
        available = [column for column in columns if column['key'] in raw_metrics]
        default_ids = {column['key'] for column in default_single_columns(available)}
        metric_items = []
        for column in available:
            key = column['key']
            shown = display_metrics.get(key)
            if shown is None or shown == '':
                shown = raw_metrics.get(key)
            metric_items.append({'id': key, 'label': column['label'],
                                 'value': _single_metric_value(shown), 'default': key in default_ids})
        formula = []
        for group in _formula_groups(script):
            children = []
            for child in group.get('children') or []:
                terms = [value for value in child.get('quotes') or []
                         if isinstance(value, str) and value and value in text]
                children.append({'label': child['label'], 'terms': list(dict.fromkeys(terms))})
            formula.append({'label': group['label'], 'children': children})
        page_materials.append({'id': material_id, 'title': row.get('materialName') or '素材名称未提供',
                               'rank': row.get('rank'), 'text': text,
                               'source': '已核验平台脚本' if text else '脚本缺口',
                               'sourceNote': '', 'metrics': metric_items,
                               'formula': formula, 'brands': []})
    selection = summary.get('selection') or {}
    period = summary.get('period') or {}
    ranking = selection.get('rankingMetric') or {}
    scope = [('开始日期', period.get('startDate')), ('结束日期', period.get('endDate')),
             ('选材排序指标', ranking.get('label') or selection.get('rankingLabel') or selection.get('rankingField')),
             ('排序方向', {'asc': '升序', 'desc': '降序'}.get(selection.get('direction'), selection.get('direction'))),
             ('脚本素材数 TopN', selection.get('topN'))]
    if ranking.get('unit'):
        scope.append(('指标单位', ranking['unit']))
    scope.extend(_scope_filters(selection.get('filters'), '选材筛选条件'))
    start = period.get('startDate') or '—'
    end = period.get('endDate') or '—'
    model = {'platform': '千川', 'title': '千川素材脚本工作台',
             'summary': f'{start} 至 {end} · 详情素材 {len(page_materials)} 条 · 按{selection.get("rankingLabel") or "本次指标"}排序',
             'scope': scope, 'brandTabs': [], 'materials': page_materials}
    return render_page(model)
