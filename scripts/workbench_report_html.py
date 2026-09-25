"""Self-contained HTML projection of verified phase-one script facts.

All facts are rendered on the server. JavaScript only filters existing content;
there are no network requests, external assets, or embedded executable data.
"""
from __future__ import annotations

from html import escape
import json
from typing import Any, Mapping
from urllib.parse import quote

from workbench_formula_overview import render_formula_overview, CSS as FORMULA_CSS, SCRIPT as FORMULA_SCRIPT
from workbench_script_interactions import render_linked_script, CSS as LINKED_CSS, SCRIPT as LINKED_SCRIPT
from workbench_quote_library import render_quote_library, CSS as LIBRARY_CSS, SCRIPT as LIBRARY_SCRIPT


_STATUS_LABELS = {
    "available": "已核验，可用", "missing": "平台未返回可用正文", "failed": "采集或解析失败",
    "identityMismatch": "返回内容身份不一致，未采信", "identityUnverified": "缺少独立身份依据，未采信",
    "submissionUnknown": "任务状态未确认", "unsubmitted": "未提交采集",
}
_FIELD_LABELS = {"text": "脚本正文", "formula": "内容公式 · formula", "detail": "脚本细节 · detail", "data": "结构数据 · data"}


def _display(value: Any) -> str:
    if value is None or value == "":
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _e(value: Any) -> str:
    return escape(_display(value), quote=True)


def _structured(value: Any) -> str:
    """Preserve nested field content and numeric zero without interpreting it."""
    if value is None or value == "" or value == [] or value == {}:
        return '<span class="muted">未提供</span>'
    if isinstance(value, Mapping):
        return '<dl class="structure">' + ''.join(
            f'<div><dt>{_e(key)}</dt><dd>{_structured(item)}</dd></div>' for key, item in value.items()
        ) + '</dl>'
    if isinstance(value, list):
        return '<ol class="structure-list">' + ''.join(f'<li>{_structured(item)}</li>' for item in value) + '</ol>'
    return f'<span class="value">{_e(value)}</span>'


def _local_href(value: Any) -> str | None:
    # Incoming references are relative to the run root; the HTML lives in overview/.
    # Reject encoded traversal, URL schemes, Windows paths and URL suffixes as well
    # as ordinary ../ traversal. Encoding happens only after validation.
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    if any(char in value for char in ('\\', ':', '?', '#', '%')):
        return None
    if any(part in {'', '.', '..'} for part in value.split('/')):
        return None
    return '../' + quote(value, safe='/')


def _source_link(value: Any, label: str | None = None) -> str:
    path = value.get('path') if isinstance(value, Mapping) else value
    digest = value.get('sha256') if isinstance(value, Mapping) else None
    href = _local_href(path)
    name = label or _display(path)
    link = f'<a href="{escape(href, quote=True)}">{_e(name)}</a>' if href else f'<span>{_e(name)}</span>'
    if digest:
        link += f' <code class="digest">SHA-256 {_e(digest)}</code>'
    return link


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
        columns.append({'key': key, 'label': definition.get('label') or key, 'unit': definition.get('unit')})
    return columns


def _status(script: Mapping[str, Any]) -> str:
    return script.get('statusLabel') or _STATUS_LABELS.get(script.get('deliveryStatus'), '未提供')


def _identity(script: Mapping[str, Any]) -> str:
    evidence = script.get('identityEvidence') or []
    if not evidence:
        return '<p class="muted">未提供逐次身份核对记录。</p>'
    items = []
    states = {'matched': '一致', 'mismatch': '不一致', 'unverified': '未核实'}
    for attempt in evidence:
        items.append(f'<section class="attempt"><h4>第 {_e(attempt.get("attempt"))} 次核对 · {_e(states.get(attempt.get("identityState"), attempt.get("identityState")))}</h4>')
        items.append('<div class="identity-grid"><div><h5>预期素材</h5>' + _structured(attempt.get('expected')) + '</div>')
        items.append('<div><h5>实际返回</h5>' + _structured(attempt.get('observed')) + '</div></div>')
        mismatches = attempt.get('mismatchedFields')
        if mismatches:
            items.append('<p>不一致字段：' + _e('、'.join(str(item) for item in mismatches)) + '</p>')
        presence = attempt.get('scriptContentPresent')
        present_label = '已返回脚本内容' if presence is True else '未检测到脚本内容' if presence is False else '脚本内容存在性未记录'
        items.append(f'<p>{present_label}</p><details class="technical"><summary>本次来源与指纹</summary><ul>')
        if attempt.get('auditPath'):
            items.append('<li>' + _source_link(attempt['auditPath'], '身份核对记录') + '</li>')
        for key, label in [('scriptContentSha256', '脚本内容指纹'), ('observedIdentitySha256', '返回身份指纹')]:
            if attempt.get(key):
                items.append(f'<li>{label}：<code class="digest">{_e(attempt[key])}</code></li>')
        items.append('</ul></details></section>')
    return ''.join(items)

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


def _formula_overview(materials: list) -> str:
    return render_formula_overview(materials, _formula_groups)


def _card(material: Mapping[str, Any], index: int, columns: list[dict]) -> str:
    script = material.get('script') or {}
    delivery = script.get('deliveryStatus')
    tone = 'good' if delivery == 'available' else 'warning'
    title = material.get('materialName') or '素材名称未提供'
    parts = [f'<article class="material-card" id="material-{index}" data-index="{index}" data-status="{_e(delivery)}">',
             '<header class="material-heading"><div>',
             f'<p class="eyebrow">素材排名 {_e(material.get("rank"))}</p><h2 class="material-name">{_e(title)}</h2>',
             f'<p class="material-id">素材 ID：{_e(material.get("materialId"))}</p></div>',
             f'<span class="badge {tone}">{_e(_status(script))}</span></header>']
    parts.append('<section class="single-block"><h3>核心指标</h3><div class="metric-grid">')
    metrics = material.get('metrics') or {}
    for column in columns:
        unit = f' · {_e(column["unit"])}' if column['unit'] else ''
        parts.append(f'<div class="metric-card"><span>{_e(column["label"])}{unit}</span><strong>{_e(metrics.get(column["key"]))}</strong></div>')
    if not columns:
        parts.append('<p class="muted">未提供指标。</p>')
    parts.append('</div></section>')
    parts.append(render_linked_script(script, _formula_groups(script), material_index=index))
    parts.append('<details class="raw-fields"><summary>平台原始结构 · formula / detail / data</summary>')
    for field in ('formula', 'detail', 'data'):
        parts.append(f'<details><summary>{_FIELD_LABELS[field]}</summary>{_structured(_trusted_field(script, field))}</details>')
    parts.append('</details><details class="evidence"><summary>身份核对与数据来源</summary>')
    parts.append(_identity(script))
    refs = list(material.get('sourceRefs') or []) + list(script.get('sourceRefs') or [])
    if script.get('materialFactPath'):
        refs.insert(0, {'path': script['materialFactPath']})
    parts.append('<details class="technical"><summary>已落盘事实与来源文件</summary>')
    parts.append('<ul>' + ''.join('<li>' + _source_link(ref) + '</li>' for ref in refs) + '</ul>' if refs else '<p class="muted">未提供来源文件。</p>')
    if material.get('errorCode'):
        parts.append('<p>错误码：<code>' + _e(material['errorCode']) + '</code></p>')
    parts.append('</details></details></article>')
    return ''.join(parts)


_STYLE = """
:root{color-scheme:light;--bg:#f4f7fb;--surface:#fff;--soft:#f8fafc;--line:#dfe6f0;--line-strong:#c9d5e5;--text:#172033;--muted:#63708a;--accent:#2563eb;--accent-soft:#eff6ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:var(--text);background:var(--bg)}
*{box-sizing:border-box}body{margin:0;padding:32px}main{max-width:1120px;margin:auto}h1{margin:0 0 12px;font-size:30px;line-height:1.25;letter-spacing:-.02em}h2{font-size:20px;margin:0 0 16px}h3{font-size:16px;margin:0 0 12px}h4{font-size:14px;margin:0 0 10px}h5{margin:0 0 8px}p,li{line-height:1.65}p{margin:8px 0 16px}a{color:var(--accent)}button,input,select{font:inherit}button,.section-nav a{min-height:40px;padding:8px 14px;border:1px solid var(--line-strong);border-radius:9px;background:var(--surface);color:var(--text);cursor:pointer;font-size:14px;text-decoration:none}button:hover:not(:disabled),.section-nav a:hover{border-color:var(--accent);background:var(--accent-soft)}button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #93b4ef;outline-offset:2px}.muted,.subtitle,.summary{color:var(--muted)}.subtitle{font-size:13px;margin-bottom:20px}.section-nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}.section-nav a.active{border-color:var(--accent);background:var(--accent);color:#fff}.panel,.material-card{min-width:0;padding:22px;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(34,64,112,.05);margin:16px 0}.quality-alert{margin:0 0 18px;padding:14px 16px;border:1px solid #c9d9f4;border-radius:12px;background:var(--accent-soft);font-size:13px;line-height:1.6}.quality-alert.warning{border-color:#f5c26d;background:#fffbeb;color:#78350f}.quality-alert p{margin:4px 0 0}.filter-config-layout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.filter-config-column{min-width:0;padding:16px;border:1px solid var(--line);border-radius:12px}.context{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0}.context>div{padding:12px;background:var(--soft);border:1px solid var(--line);border-radius:10px}.context dt{font-size:12px;color:var(--muted)}.context dd{margin:6px 0 0;font-size:14px;line-height:1.55;overflow-wrap:anywhere}.toolbar,.pager{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.toolbar{padding:14px;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(34,64,112,.06)}.toolbar label:first-child{flex:1;min-width:250px}label{font-size:12px;color:var(--muted)}input[type=search],select{width:100%;min-width:0;min-height:44px;padding:10px 13px;border:1px solid var(--line-strong);border-radius:9px;background:var(--surface);color:var(--text);font-size:14px}input[type=search]:focus{border-color:var(--accent)}.summary{font-size:13px;margin:16px 2px 10px}.table-wrap{overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:14px;margin:16px 0}.table-wrap table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--soft);white-space:nowrap;font-size:13px}th button{padding:4px 0;min-height:28px;border:0;background:none;font-weight:650}th small{display:block;color:var(--muted);font-weight:400;font-size:11px}caption{padding:12px 14px;text-align:left;color:var(--muted);font-size:12px;line-height:1.6}.material-name-column{min-width:300px;width:300px;position:sticky;left:0;z-index:1;background:white}th.material-name-column{z-index:2;background:var(--soft)}.material-title{overflow-wrap:anywhere;line-height:1.65}.table-material-id,.material-id{font-size:12px;color:var(--muted);overflow-wrap:anywhere;margin-top:6px}.table-status{min-width:170px}td[data-metric]{white-space:nowrap;font-variant-numeric:tabular-nums}.pager{justify-content:space-between;margin:14px 0;color:var(--muted);font-size:13px}.pager>div{display:flex;align-items:center;gap:8px}.single-material-main{min-width:0}.single-material-shell{display:grid;grid-template-columns:230px minmax(0,1fr);gap:16px;align-items:start}.single-material-selector{position:sticky;top:18px;padding:16px;background:white;border:1px solid var(--line);border-radius:14px;max-height:70vh;overflow:auto}.single-material-selector h2{font-size:17px}.single-material-selector input{font-size:12px;padding:9px;margin-bottom:10px}.material-option{display:block;width:100%;text-align:left;min-width:0;margin-top:7px;padding:10px 11px;border:1px solid var(--line);border-radius:9px;color:var(--text);background:white;font-size:12px;overflow-wrap:anywhere;line-height:1.55;text-decoration:none}.material-option:hover{border-color:var(--accent);background:var(--accent-soft)}.option-name{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.material-option small{display:block;color:var(--muted);margin-top:4px}.material-option.active{background:var(--accent-soft);border-color:var(--accent);color:#1d4ed8}.material-card{margin:0 0 16px}.material-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}.material-heading>div{min-width:0}.material-name{overflow-wrap:anywhere;line-height:1.6;font-size:20px;margin:4px 0}.eyebrow{font-size:12px;color:var(--muted);margin:0}.badge{display:inline-block;padding:6px 9px;border-radius:7px;font-size:12px;line-height:1.6;max-width:230px}.good{color:#16634e;background:#edf8f2}.warning{color:#835817;background:#fff5e4}.single-block{margin:20px 0;padding-top:18px;border-top:1px solid var(--line)}.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.metric-card{min-width:0;padding:14px;border:1px solid var(--line);border-radius:10px;background:#fbfdff}.metric-card span{display:block;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.metric-card strong{display:block;font-size:23px;line-height:1.5;font-weight:650;margin-top:6px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.formula-flow{display:flex;gap:10px;flex-wrap:wrap}.formula-group{min-width:150px;flex:1;padding:12px;border:1px solid #c9daf8;border-radius:10px;background:#f6f9ff}.formula-group>strong{font-size:14px;color:#234e95}.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.tags span{font-size:12px;background:white;border:1px solid var(--line);padding:5px 8px;border-radius:7px}.script-text{white-space:pre-wrap;line-height:1.95;overflow-wrap:anywhere;padding:16px;border:1px solid var(--line);border-radius:10px;background:#fbfdff;font-size:14px}.detail-fragment{padding:12px 14px;background:var(--soft);border-radius:9px;margin:10px 0}.detail-fragment h4{color:#315995}.formula-summary{padding:18px;border:1px solid var(--line);border-radius:12px;margin:14px 0;background:#fbfdff}.bar-label{display:flex;justify-content:space-between;gap:10px;font-size:14px;margin-bottom:12px}.bar-label span{color:var(--muted);font-size:12px}.bar-track{height:12px;background:#e9eef7;border-radius:6px;overflow:hidden}.bar-track span{display:block;height:100%;background:var(--accent);border-radius:6px}.coverage-list{list-style:none;padding:0}.coverage-list li{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}.coverage-list li span:last-child{color:var(--muted)}details{border-top:1px solid var(--line);padding:14px 0}summary{font-size:13px;font-weight:600;line-height:1.7;cursor:pointer}details[open]>summary{margin-bottom:12px}.structure{margin:0}.structure>div{margin:9px 0}.structure dt{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.structure dd{margin:5px 0 0;padding-left:10px;border-left:2px solid var(--line);overflow-wrap:anywhere}.structure-list{padding-left:22px;margin:6px 0}.value{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.75;font-size:13px}.identity-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.attempt{background:var(--soft);padding:16px;border-radius:8px;margin:10px 0}.attempt p,.technical{font-size:12px}.technical summary{font-size:12px;color:var(--muted)}.technical li{overflow-wrap:anywhere;margin:8px 0}code{font-size:11px;overflow-wrap:anywhere}.digest{display:block;color:var(--muted);margin-top:5px}.recovery{font-size:13px;color:#176355}.missing-script{font-size:14px;color:var(--muted)}.empty{text-align:center;color:var(--muted);padding:30px;line-height:1.7}.footer{font-size:12px;color:var(--muted);line-height:1.7;margin:22px 0}.run-id{overflow-wrap:anywhere}.status-counts{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px;color:var(--muted);font-size:13px}[hidden]{display:none!important}
@media(max-width:760px){body{padding:18px 12px}h1{font-size:24px}.section-nav{gap:6px}.section-nav a{font-size:12px;padding:8px 10px}.filter-config-layout,.single-material-shell,.identity-grid{grid-template-columns:minmax(0,1fr)}.single-material-selector{position:static;max-height:320px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.panel,.material-card{padding:16px}.material-heading{display:block}.material-heading .badge{margin-bottom:8px}.bar-label{display:block}.bar-label span{display:block;margin-top:5px}.toolbar label{width:100%}.toolbar label:first-child{min-width:0}.material-name-column{min-width:240px;width:240px}.pager{align-items:flex-start}.pager>div{gap:4px;flex-wrap:wrap}.pager button{font-size:12px;padding:7px 9px}.context{grid-template-columns:1fr}}
@media(max-width:400px){.metric-grid{grid-template-columns:1fr}}
@media print{body{background:white;padding:0}.section-nav,.toolbar,.pager,.single-material-selector{display:none!important}.single-material-shell{display:block}.panel,.material-card{box-shadow:none}.footer{margin-bottom:0}}
"""

_SCRIPT = """
(() => {
  const byId = id => document.getElementById(id);
  const all = selector => Array.from(document.querySelectorAll(selector));
  const panels = all("[data-section-panel]");
  const nav = all("[data-section]");
  const cards = all(".material-card");
  const rows = all(".material-row");
  const options = all(".material-option");
  const normalize = value => String(value || "").normalize("NFKC").toLocaleLowerCase().trim();
  const searchable = new Map(cards.map(card => [card.dataset.index, normalize(Array.from(card.querySelectorAll(".material-name, .material-id, .script-text")).map(item => item.textContent).join(" "))]));
  const statuses = new Map(cards.map(card => [card.dataset.index, card.dataset.status]));
  const pageSize = 10;
  let page = 1, sortMetric = null, direction = 0;
  function showSection(name) {
    panels.forEach(panel => { panel.hidden = panel.dataset.sectionPanel !== name; });
    nav.forEach(link => {
      const active = link.dataset.section === name;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
  }
  function selectMaterial(index, navigate) {
    cards.forEach(card => { card.hidden = card.dataset.index !== index; });
    options.forEach(option => {
      const selected = option.dataset.openMaterial === index;
      option.classList.toggle("active", selected);
      option.setAttribute("aria-pressed", String(selected));
    });
    if (navigate) showSection("single-material");
  }
  function metricValue(row) {
    const cell = Array.from(row.querySelectorAll("[data-metric]")).find(item => item.dataset.metric === sortMetric);
    const text = cell ? cell.textContent.trim().replace(/,/g, "") : "";
    if (!text || !/^[+-]?(?:\\d+\\.?\\d*|\\.\\d+)(?:e[+-]?\\d+)?$/i.test(text)) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  }
  function updateTable() {
    const query = normalize(byId("material-search").value);
    const status = byId("status-filter").value;
    const matching = rows.filter(row => (!query || (searchable.get(row.dataset.index) || "").includes(query)) && (status === "all" || statuses.get(row.dataset.index) === status));
    if (sortMetric && direction) matching.sort((a, b) => {
      const av = metricValue(a), bv = metricValue(b);
      if (av === null || bv === null) return av === bv ? Number(a.dataset.index) - Number(b.dataset.index) : av === null ? 1 : -1;
      return (av - bv) * direction || Number(a.dataset.index) - Number(b.dataset.index);
    });
    const pageCount = Math.max(1, Math.ceil(matching.length / pageSize));
    page = Math.max(1, Math.min(page, pageCount));
    rows.forEach(row => { row.hidden = true; });
    const visible = matching.slice((page - 1) * pageSize, page * pageSize);
    visible.forEach(row => { row.hidden = false; byId("material-rows").appendChild(row); });
    byId("visible-count").textContent = `共 ${matching.length} 条素材；当前显示 ${matching.length ? (page - 1) * pageSize + 1 : 0}–${Math.min(page * pageSize, matching.length)} 条`;
    byId("page-number").textContent = `${page} / ${pageCount}`;
    byId("first-page").disabled = byId("previous-page").disabled = page <= 1;
    byId("next-page").disabled = byId("last-page").disabled = page >= pageCount;
    byId("no-results").hidden = matching.length > 0;
    all("[data-sort-metric]").forEach(button => {
      const active = button.dataset.sortMetric === sortMetric && direction !== 0;
      button.setAttribute("aria-label", button.dataset.label + (active ? direction > 0 ? "，升序" : "，降序" : "，点击排序"));
      button.querySelector(".sort-mark").textContent = active ? direction > 0 ? " ↑" : " ↓" : " ↕";
    });
  }
  nav.forEach(link => { link.onclick = event => { event.preventDefault(); showSection(link.dataset.section); }; });
  all("[data-open-material]").forEach(button => { button.onclick = event => { event.preventDefault(); selectMaterial(button.dataset.openMaterial, true); }; });
  all("[data-library-open]").forEach(link => { link.onclick = event => {
    event.preventDefault(); selectMaterial(link.dataset.libraryOpen, true);
    const card = byId("material-" + link.dataset.libraryOpen);
    if (card) card.scrollIntoView({behavior:"smooth", block:"start"});
  }; });
  byId("material-search").oninput = () => { page = 1; updateTable(); };
  byId("status-filter").onchange = () => { page = 1; updateTable(); };
  all("[data-sort-metric]").forEach(button => { button.onclick = () => {
    direction = sortMetric !== button.dataset.sortMetric ? -1 : direction === -1 ? 1 : direction === 1 ? 0 : -1;
    sortMetric = button.dataset.sortMetric; page = 1; updateTable();
  }; });
  byId("first-page").onclick = () => { page = 1; updateTable(); };
  byId("previous-page").onclick = () => { page -= 1; updateTable(); };
  byId("next-page").onclick = () => { page += 1; updateTable(); };
  byId("last-page").onclick = () => { page = Number.MAX_SAFE_INTEGER; updateTable(); };
  byId("single-material-search").oninput = () => {
    const query = normalize(byId("single-material-search").value);
    options.forEach(option => { option.hidden = !normalize(option.textContent).includes(query); });
    byId("selector-empty").hidden = options.some(option => !option.hidden);
  };
  byId("report-controls").hidden = false;
  byId("table-pager").hidden = false;
  byId("selector-search").hidden = false;
  updateTable();
  if (cards.length) selectMaterial(cards[0].dataset.index, false);
  showSection("filters");
})();
"""


def render_html(summary: Mapping[str, Any]) -> str:
    """Render an offline workbench with a fully readable no-JavaScript fallback."""
    materials = list(summary.get('materials') or [])
    counts, selection, period = (summary.get(key) or {} for key in ('counts', 'selection', 'period'))
    ranking = selection.get('rankingMetric') or {}
    columns = _metric_columns(summary, materials)
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>千川素材脚本数据工作台</title><style>' + _STYLE + FORMULA_CSS + LINKED_CSS + LIBRARY_CSS + '</style></head><body><main>',
             '<h1>千川素材脚本数据工作台</h1>',
             f'<p class="subtitle">{_e(period.get("startDate"))} 至 {_e(period.get("endDate"))} · {len(materials)} 个素材</p>']
    parts.append('<nav class="section-nav" aria-label="报告部分">')
    for key, label in [('filters', '素材筛选条件'), ('materials', '素材榜单'), ('scripts', '脚本内容公式'), ('single-material', '单素材脚本'), ('quote-library', '脚本片段库')]:
        parts.append(f'<a href="#{key}-panel" data-section="{key}">{label}</a>')
    parts.append('</nav><noscript><p class="quality-alert">浏览器未启用 JavaScript，已展开全部报告分区与素材，仍可阅读全文和折叠来源。</p></noscript>')
    parts.append('<section id="filters-panel" class="panel" data-section-panel="filters"><h2>素材筛选条件</h2><div class="filter-config-layout"><div class="filter-config-column"><h3>取数范围</h3><dl class="context">')
    for label, value in [('开始日期', period.get('startDate')), ('结束日期', period.get('endDate')), ('完整报表行数', counts.get('reportRows')), ('入选素材数', counts.get('selectedMaterials'))]:
        parts.append(f'<div><dt>{label}</dt><dd>{_e(value)}</dd></div>')
    parts.append('</dl></div><div class="filter-config-column"><h3>素材选取</h3><dl class="context">')
    direction = {'asc': '升序', 'desc': '降序'}.get(selection.get('direction'), selection.get('direction'))
    for label, value in [('排序指标', ranking.get('label') or selection.get('rankingLabel') or selection.get('rankingField')), ('排序方向', direction), ('详情素材数 TopN', selection.get('topN')), ('指标单位', ranking.get('unit'))]:
        parts.append(f'<div><dt>{label}</dt><dd>{_e(value)}</dd></div>')
    parts.append('</dl></div></div><details><summary>筛选条件与排序字段</summary>' + _structured(selection.get('filters')) + f'<p class="muted">排序字段：{_e(ranking.get("fieldId") or selection.get("rankingField"))}</p></details></section>')
    parts.append('<section id="materials-panel" data-section-panel="materials"><div class="toolbar" id="report-controls" hidden><label>搜索素材或正文<input id="material-search" type="search" placeholder="输入素材 ID、名称或脚本正文"></label><label>脚本状态<select id="status-filter"><option value="all">全部状态</option>')
    parts.extend(f'<option value="{key}">{label}</option>' for key, label in _STATUS_LABELS.items())
    parts.append('</select></label></div><p class="summary" id="visible-count"></p><div class="table-wrap"><table><caption>入选素材的报表指标。缺失显示“未提供”；可排序和翻页查看，点击名称进入单素材脚本。</caption><thead><tr><th scope="col" class="material-name-column">素材名称 / ID</th><th scope="col">排名</th>')
    for column in columns:
        parts.append(f'<th scope="col"><button type="button" data-sort-metric="{_e(column["key"])}" data-label="{_e(column["label"])}">{_e(column["label"])}<span class="sort-mark"></span></button><small>{_e(column["unit"]) if column["unit"] else "单位未提供"}</small></th>')
    parts.append('<th scope="col">脚本状态</th></tr></thead><tbody id="material-rows">')
    for index, material in enumerate(materials):
        parts.append(f'<tr class="material-row" data-index="{index}"><td class="material-name-column"><a class="material-title" href="#material-{index}" data-open-material="{index}">{_e(material.get("materialName") or "素材名称未提供")}</a><div class="table-material-id">素材 ID：{_e(material.get("materialId"))}</div></td><td>{_e(material.get("rank"))}</td>')
        for column in columns:
            parts.append(f'<td data-metric="{_e(column["key"])}">{_e((material.get("metrics") or {}).get(column["key"]))}</td>')
        parts.append('<td class="table-status">' + _e(_status(material.get('script') or {})) + '</td></tr>')
    parts.append('</tbody></table></div>')
    if not materials:
        parts.append('<div class="empty">暂无素材数据。</div>')
    parts.append('<div class="empty" id="no-results" hidden>没有符合当前搜索和状态条件的素材。</div><div class="pager" id="table-pager" hidden><span>每页 10 个素材</span><div><button type="button" id="first-page">首页</button><button type="button" id="previous-page">上一页</button><span id="page-number"></span><button type="button" id="next-page">下一页</button><button type="button" id="last-page">尾页</button></div></div></section>')
    parts.append('<section id="scripts-panel" data-section-panel="scripts">' + _formula_overview(materials) + '</section>')
    parts.append('<section id="single-material-panel" data-section-panel="single-material"><div class="single-material-shell"><aside class="single-material-selector"><h2>单素材脚本</h2><label id="selector-search" hidden>查找素材<input type="search" id="single-material-search" placeholder="搜索名称或 ID"></label>')
    for index, material in enumerate(materials):
        parts.append(f'<a class="material-option" href="#material-{index}" data-open-material="{index}" title="{_e(material.get("materialName") or "素材名称未提供")}"><span class="option-name">{_e(material.get("rank"))}. {_e(material.get("materialName") or "素材名称未提供")}</span><small>{_e(material.get("materialId"))}</small></a>')
    parts.append('<p class="muted" id="selector-empty" hidden>没有匹配素材。</p></aside><div class="single-material-main">')
    parts.extend(_card(material, index, columns) for index, material in enumerate(materials))
    if not materials:
        parts.append('<div class="panel empty">暂无素材数据。</div>')
    parts.append('</div></div></section>')
    parts.append('<section id="quote-library-panel" data-section-panel="quote-library">' + render_quote_library(materials, _formula_groups) + '</section>')
    parts.append('<p class="footer">千川素材脚本数据 · 指标按本次取数周期展示。</p></main><script>' + _SCRIPT + FORMULA_SCRIPT + LINKED_SCRIPT + LIBRARY_SCRIPT + '</script></body></html>')
    return ''.join(parts)
