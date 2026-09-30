"""Self-contained single-page phase-one script workbench UI.

The caller projects only verified run facts into the model. No external assets or
network requests are used by the page.
"""
from __future__ import annotations

from html import escape
import json


_OPERATORS = {'eq': '=', 'ne': '≠', 'gt': '>', 'gte': '≥', 'lt': '<', 'lte': '≤',
              'in': '属于', 'not_in': '不属于', 'contains': '包含'}


def _scope_value(value) -> str:
    if value is None or value == '':
        return '—'
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return '、'.join(map(str, value)) or '无'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _scope_filters(filters, label='本地筛选条件') -> list[tuple[str, str]]:
    if not isinstance(filters, list) or not filters:
        return [(label, '无')]
    result = []
    for index, item in enumerate(filters, 1):
        if not isinstance(item, dict):
            result.append((f'{label} {index}', _scope_value(item)))
            continue
        field = item.get('label') or item.get('fieldLabel') or item.get('field') or item.get('fieldId') or '字段未提供'
        operator = _OPERATORS.get(str(item.get('operator')), item.get('operator') or '')
        value = item.get('value') if 'value' in item else item.get('values')
        result.append((f'{label} {index}', f'{field} {operator} {_scope_value(value)}'.strip()))
    return result


def _platform_scope_params(params: dict) -> list[tuple[str, str]]:
    labels = {'ages': '年龄筛选', 'genders': '性别筛选', 'crowd_groups': '人群筛选'}
    baseline = {'industry', 'date_type', 'custom_start_date', 'custom_end_date',
                'ranking_limit_type', 'brand_scope_type', 'brands'}
    private_tokens = ('shop', 'account', 'advertiser', 'token', 'secret', 'credential', 'auth')
    return [(labels.get(key, f'平台取数参数：{key}'), _scope_value(value))
            for key, value in params.items()
            if key not in baseline and not any(token in key.lower() for token in private_tokens)
            and value not in (None, '', [], {})]


STYLE = r"""
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:#172033;background:#f4f7fb;--blue:#2563eb;--soft:#eff6ff;--line:#dfe6f0;--muted:#63708a}*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #93b4ef;outline-offset:2px}[hidden]{display:none!important}.app{max-width:1520px;margin:auto;padding:28px 24px 80px}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:18px}.eyebrow{font-size:11px;letter-spacing:.1em;color:#4974a6;font-weight:700;margin:0 0 8px}.top h1{font-size:28px;line-height:1.25;margin:0 0 8px}.top p{margin:0;color:var(--muted);font-size:13px;line-height:1.6}.preview-badge{flex:none;border-radius:9px;padding:8px 11px;background:#e7f0ff;color:#245bb3;font-size:12px;font-weight:700}.panel{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(34,64,112,.05)}.top-tools{display:flex;gap:10px;align-items:center;margin:0 0 16px}.top-tools details,.overview{padding:0 16px}.top-tools details{flex:1}.top-tools summary,.overview summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 0;font-weight:650;cursor:pointer}.top-tools summary::-webkit-details-marker,.overview summary::-webkit-details-marker{display:none}.top-tools summary::after,.overview summary::after{content:"展开";font-size:12px;color:var(--blue);font-weight:500}details[open]>summary::after{content:"收起"}.scope-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:9px;padding:0 0 14px}.scope-grid div{background:#f8fafc;border:1px solid var(--line);border-radius:9px;padding:9px}.scope-grid small{display:block;color:var(--muted)}.scope-grid strong{display:block;font-size:12px;margin-top:4px;overflow-wrap:anywhere}.overview{margin:0 0 16px}.overview-body{padding:3px 0 18px}.overview-note{font-size:12px;color:var(--muted);margin:0 0 16px}.chart-row{min-height:190px;overflow-x:auto;overflow-y:hidden;padding:6px 4px 2px}.bar-track{display:flex;justify-content:center;align-items:flex-end;gap:18px;width:max-content;min-width:100%;margin:0 auto}.bar-cell{display:flex;flex:none;flex-direction:column;justify-content:flex-end;align-items:center;min-width:92px;width:110px;height:180px;border:0;background:transparent;padding:0 2px;color:#42536e}.bar-cell:hover .bar,.bar-cell.active .bar{background:#1d4ed8}.bar-cell .count{font-size:12px;font-weight:700;margin:3px}.bar-cell .bar{display:block;width:42px;min-height:4px;border-radius:7px 7px 0 0;background:#5b8def}.bar-cell .label{font-size:11px;line-height:1.35;height:35px;margin-top:5px;white-space:nowrap}.overview-secondary{display:grid;grid-template-columns:232px minmax(0,1fr);align-items:center;justify-content:center;gap:20px;max-width:980px;padding:18px 22px;border:1px solid var(--line);border-radius:10px;background:#fbfdff;margin:16px auto 0}.overview-secondary-ring{display:flex;justify-content:center}.overview-secondary svg{display:block;width:232px;height:270px}.donut-segment{cursor:pointer;transition:transform .2s ease,opacity .2s ease;transform-origin:center}.donut-segment:hover,.donut-segment.active{transform:translate(var(--shift-x),var(--shift-y))}.donut-segment:focus-visible{outline:3px solid #172033;outline-offset:2px}.donut-center-label{fill:#63708a;font-size:11px;text-anchor:middle;pointer-events:none}.donut-center-value{fill:#172033;font-size:25px;font-weight:700;text-anchor:middle;pointer-events:none}.overview-secondary-detail>strong{display:block;margin:0 0 12px;font-size:15px}.overview-secondary-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.legend-item{display:flex;align-items:center;gap:10px;min-height:50px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;color:#172033;text-align:left;font-size:12px;line-height:1.4}.legend-item:hover,.legend-item.active{border-color:#93b4ef;background:#eff6ff}.legend-swatch{flex:none;width:10px;height:10px;border-radius:2px}.legend-detail{display:block;color:var(--muted);font-size:11px;margin-top:3px}.workspace{display:grid;grid-template-columns:252px minmax(0,1fr) 328px;gap:16px;align-items:start}.selector,.insight{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto}.selector{padding:15px}.selector h2,.insight h2{font-size:16px;margin:0 0 11px}.selector label{display:block;font-size:11px;color:var(--muted);margin:8px 0 5px}.selector select{width:100%;padding:9px 10px;min-height:39px;border:1px solid #c9d5e5;border-radius:8px;background:#fff;color:#172033;font-size:12px}.list-note{font-size:11px;color:var(--muted);margin:12px 0 7px}.item-list{display:grid;gap:6px}.item-list button{width:100%;border:1px solid var(--line);border-radius:9px;background:#fff;color:#172033;text-align:left;padding:10px;line-height:1.45;font-size:12px}.item-list button.active{border-color:var(--blue);background:var(--soft)}.item-list button:hover{border-color:#93b4ef}.item-list .name{display:block;font-weight:650;overflow-wrap:anywhere}.item-list .meta{display:block;color:var(--muted);font-size:10px;margin-top:5px;overflow-wrap:anywhere}.reader{padding:21px;min-width:0}.reader-head{border-bottom:1px solid var(--line);padding-bottom:13px}.reader-head h2{font-size:20px;line-height:1.45;margin:3px 0 8px;overflow-wrap:anywhere}.reader-head .meta{font-size:12px;color:var(--muted);line-height:1.6}.status{display:inline-block;background:#edf8f2;color:#16634e;padding:4px 7px;border-radius:6px;font-size:11px}.status.gap{background:#fff5e4;color:#835817}.block-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:22px 0 10px}.block-head h3{font-size:15px;margin:0}.subtle-button{border:1px solid #c9d5e5;border-radius:8px;background:#fff;color:#315e96;font-size:11px;min-height:32px;padding:5px 9px}.subtle-button:hover{background:var(--soft)}.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.metric{padding:10px;border:1px solid var(--line);border-radius:8px;background:#fbfdff;min-width:0}.metric small{display:block;color:var(--muted);font-size:10px;line-height:1.4}.metric strong{display:block;font-size:16px;margin-top:5px;overflow-wrap:anywhere}.script-copy{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.95;font-size:14px;padding:18px;border:1px solid var(--line);border-radius:10px;background:#fbfdff;min-height:220px}.script-copy mark{background:#ffe7a2;color:#172033;border-radius:3px;padding:1px 0}.source-note{font-size:11px;color:var(--muted);line-height:1.6;margin:7px 0}.layered{font-size:12px;border-top:1px solid var(--line);margin-top:16px;padding-top:12px}.layered summary{cursor:pointer;color:#315e96}.layered h4{margin:12px 0 5px}.insight{padding:15px}.insight-block+ .insight-block{border-top:1px solid var(--line);margin-top:16px;padding-top:16px}.insight-note{font-size:11px;color:var(--muted);line-height:1.55;margin:0 0 10px}.formula-group{border:1px solid var(--line);border-radius:9px;margin:8px 0;padding:10px}.formula-group strong{font-size:12px;color:#295899}.formula-steps{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.formula-steps button{border:1px solid #cbdaf2;background:#f6f9ff;color:#315e96;border-radius:6px;padding:5px 7px;font-size:11px;line-height:1.35}.formula-steps button:hover{background:#e7f0ff;border-color:#93b4ef}.empty{font-size:12px;color:var(--muted);padding:16px;background:#fafcff;border:1px dashed var(--line);border-radius:8px;line-height:1.6}.metric-dialog{border:1px solid var(--line);border-radius:14px;padding:20px;max-width:600px;width:min(92vw,600px);max-height:80vh}.metric-dialog::backdrop{background:#10213b99}.metric-dialog h2{margin:0 0 5px;font-size:18px}.metric-options{max-height:45vh;overflow:auto;display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0}.metric-options label{font-size:12px;line-height:1.4;padding:8px;border:1px solid var(--line);border-radius:8px}.metric-actions{display:flex;justify-content:flex-end;gap:7px}.metric-actions button{border:1px solid #c9d5e5;border-radius:8px;background:#fff;padding:7px 10px}.metric-actions .primary{background:var(--blue);border-color:var(--blue);color:#fff}.fallback{max-width:1100px;margin:30px auto;padding:20px}.fallback details{margin:8px 0}.fallback pre{white-space:pre-wrap;line-height:1.7;overflow-wrap:anywhere;font:inherit}@media(max-width:1180px){.workspace{grid-template-columns:230px minmax(0,1fr)}.insight{grid-column:2;position:static;max-height:none}.selector{top:16px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.overview-secondary{grid-template-columns:1fr;padding:14px}.overview-secondary-list{grid-template-columns:repeat(auto-fit,minmax(135px,1fr))}.bar-track{gap:10px}.bar-cell{width:100px;min-width:92px}.app{padding:18px 12px 50px}.top h1{font-size:22px}.workspace{grid-template-columns:1fr}.selector,.insight{grid-column:1;position:static;max-height:none}.selector .item-list{max-height:250px;overflow:auto}.scope-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.reader{padding:16px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.metric-options{grid-template-columns:1fr}}@media print{body{background:#fff}.selector,.overview,.top-tools,.subtle-button,.preview-badge{display:none!important}.workspace{display:block}.reader,.insight{box-shadow:none;max-height:none;overflow:visible}.app{padding:0}}
"""

QUOTE_STYLE = r"""
.quote-explorer{margin:0 0 16px;padding:0 18px}
.quote-explorer>summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 0;font-weight:650;cursor:pointer}
.quote-explorer>summary::-webkit-details-marker{display:none}
.quote-explorer>summary::after{content:"展开";font-size:12px;color:var(--blue);font-weight:500}
.quote-explorer[open]>summary::after{content:"收起"}
.quote-explorer-body{padding:0 0 18px}
.quote-level{border-radius:11px;padding:13px 15px;margin-bottom:11px}
.quote-level-primary{background:#edf4ff;border:1px solid #d2e2ff}
.quote-level-secondary{background:#f8fafc;border:1px solid var(--line)}
.quote-level h3{margin:0 0 11px;font-size:13px;line-height:1.4}
.quote-level-primary h3{color:#174996}.quote-level-secondary h3{color:#42536e}
.quote-level h3 small{font-size:11px;font-weight:500;color:var(--muted);margin-left:8px}
.quote-primary,.quote-secondary{display:flex;flex-wrap:wrap;gap:8px}
.quote-primary button,.quote-secondary button{border-radius:8px;text-align:left;line-height:1.4}
.quote-primary button{border:1px solid #b4cffd;background:#fff;padding:9px 12px;color:#174996;font-weight:650}
.quote-secondary button{border:1px solid #d4deeb;background:#fff;padding:7px 10px;color:#42536e;font-size:12px}
.quote-primary button:hover,.quote-primary button.active{border-color:#2563eb;background:#dbeafe;color:#163d83}
.quote-secondary button:hover,.quote-secondary button.active{border-color:#6aa7aa;background:#e5f5f3;color:#16605d}
.quote-primary button.active,.quote-secondary button.active{font-weight:700}
.quote-results-head{font-size:13px;font-weight:650;margin:16px 0 10px}
.quote-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.quote-card{min-width:0;border:1px solid var(--line);border-radius:10px;background:#fafcff;padding:14px}
.quote-card blockquote{margin:0 0 12px;font-size:14px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere}
.quote-card-meta{font-size:12px;color:var(--muted);line-height:1.5;overflow-wrap:anywhere}
.quote-card button,.quote-pagination button{margin-top:10px;border:1px solid #cbdaf2;border-radius:7px;background:#fff;padding:7px 10px;color:#315e96}
.quote-card button:hover,.quote-pagination button:not(:disabled):hover{background:#eff6ff}
.quote-pagination{display:flex;justify-content:center;align-items:center;gap:12px;margin-top:13px;font-size:12px;color:var(--muted)}
.quote-pagination button{margin-top:0}.quote-pagination button:disabled{opacity:.45;cursor:default}
@media(max-width:760px){.quote-results{grid-template-columns:1fr}.quote-explorer{padding:0 12px}}
"""


SCRIPT = r"""
(() => {
  document.documentElement.classList.add('js');
  const model = JSON.parse(document.getElementById('workbench-model').textContent);
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const materialById = new Map(model.materials.map(m => [m.id, m]));
  const savedMetrics = new Map();
  const state = {selected: null, brand:'all', formula:null, secondary:null, highlight:null, quotePage:0, quoteItems:[]};
  const hashId = decodeURIComponent((location.hash.match(/^#material=(.*)$/) || [])[1] || '');
  state.selected = materialById.has(hashId) ? hashId : (model.materials[0]?.id || null);
  function current() { return materialById.get(state.selected); }
  function currentMetrics(m) { return savedMetrics.get(m.id) || new Set(m.metrics.filter(x => x.default).map(x => x.id)); }
  function applicable(m, secondary) {
    if (state.brand !== 'all' && !m.brands.includes(state.brand)) return false;
    if (state.formula && !m.formula.some(g => g.label === state.formula)) return false;
    if (secondary && !m.formula.some(g => g.label === state.formula && g.children.some(c => c.label === secondary))) return false;
    return true;
  }
  function renderList() {
    const group=formulaCounts().groups.find(g=>g.label===state.formula);
    const secondary=state.secondary==null ? null : group?.children[state.secondary]?.label;
    const visible = model.materials.filter(m=>applicable(m,secondary));
    if (!visible.some(m => m.id === state.selected)) { state.selected = visible[0]?.id || null; state.highlight = null; }
    $('list-count').textContent = `显示 ${visible.length} / ${model.materials.length} 条详情素材`;
    $('item-list').innerHTML = visible.length ? visible.map(m => `<button type="button" data-select="${esc(m.id)}" class="${m.id === state.selected ? 'active' : ''}" aria-pressed="${m.id === state.selected}"><span class="name">${esc(m.rank)}. ${esc(m.title)}</span><span class="meta">${esc(m.id)} · ${esc(m.source)}</span></button>`).join('') : '<p class="empty">没有匹配的详情素材，请调整筛选。</p>';
    $('active-filter').hidden = !state.formula;
    $('active-filter').textContent = state.formula ? `清除公式筛选：${state.formula}${secondary ? ' / '+secondary : ''}` : '';
  }
  function renderText() {
    const m = current(), box = $('script-text');
    box.replaceChildren();
    if (!m || !m.text) { box.textContent = m ? '本素材暂无可读脚本；保留已核验缺口，不补写正文。' : '请选择详情素材。'; return; }
    const term = state.highlight;
    const at = term ? m.text.indexOf(term) : -1;
    if (at < 0) { box.textContent = m.text; return; }
    box.append(document.createTextNode(m.text.slice(0, at)));
    const mark = document.createElement('mark'); mark.textContent = term; mark.id = 'active-quote';
    box.append(mark, document.createTextNode(m.text.slice(at + term.length)));
  }
  function renderSelected() {
    const m = current();
    $('reader-empty').hidden = !!m; $('reader-content').hidden = !m;
    if (!m) { $('formula-list').innerHTML = '<p class="empty">请选择详情素材。</p>'; return; }
    $('material-title').textContent = m.title;
    $('material-meta').textContent = `素材排名 ${m.rank} · 素材 ID ${m.id}`;
    $('material-source').textContent = m.source;
    $('material-source').classList.toggle('gap', !m.text);
    if ($('source-note')) $('source-note').textContent = m.sourceNote || '';
    const fields = currentMetrics(m);
    const showing = m.metrics.filter(x => fields.has(x.id));
    $('metric-count').textContent = `已展示 ${showing.length} / ${m.metrics.length}`;
    $('metric-grid').innerHTML = showing.length ? showing.map(x => `<div class="metric"><small>${esc(x.label)}</small><strong>${esc(x.value)}</strong></div>`).join('') : '<div class="empty">当前素材无可展示指标。</div>';
    renderText();
    $('formula-list').innerHTML = m.formula.length ? m.formula.map((g,groupIndex) => `<div class="formula-group"><strong>${esc(g.label)}</strong><div class="formula-steps">${g.children.length ? g.children.map((c,childIndex) => `<button type="button" data-formula-step="${groupIndex}:${childIndex}" title="${c.terms.length ? '定位脚本原句' : '无可定位的脚本原句'}">${esc(c.label)}${c.terms.length ? ` · ${c.terms.length}句` : ''}</button>`).join('') : '<span class="source-note">暂无二级标签</span>'}</div></div>`).join('') : '<p class="empty">本素材没有可读的平台内容公式；正文仍可独立阅读。</p>';
    const layered = m.layeredText || {};
    $('layered-text').hidden = !Object.values(layered).some(Boolean);
    $('layered-body').innerHTML = Object.entries(layered).map(([label, text]) => `<h4>${esc(label)}</h4><div class="source-note">${esc(text || '未提供')}</div>`).join('');
  }
  function jumpToTerm(term) {
    const m = current();
    if (!m || !term || !m.text.includes(term)) return;
    state.highlight = term;
    renderText(); requestAnimationFrame(() => ($('active-quote') || $('script-text')).scrollIntoView({behavior:'smooth',block:'center'}));
  }
  function selectMaterial(id, updateHash=true) {
    if (!materialById.has(id)) return;
    state.selected = id; state.highlight = null;
    if (updateHash) history.replaceState(null, '', '#material=' + encodeURIComponent(id));
    renderList(); renderSelected();
  }
  function formulaCounts() {
    const materials = model.materials.filter(m => state.brand === 'all' || m.brands.includes(state.brand));
    const groups = new Map();
    for (const m of materials) for (const g of m.formula) {
      if (!groups.has(g.label)) groups.set(g.label, {ids:new Set(),children:new Map()});
      const group = groups.get(g.label); group.ids.add(m.id);
      for (const c of g.children) { if (!group.children.has(c.label)) group.children.set(c.label,new Set()); group.children.get(c.label).add(m.id); }
    }
    return {materials,groups:[...groups].map(([label,value]) => ({label,count:value.ids.size,
      children:[...value.children].map(([child,ids]) => ({label:child,count:ids.size})).sort((a,b)=>b.count-a.count)})).sort((a,b)=>b.count-a.count)};
  }
  function donutPath(start, end, cx=116, cy=130, outer=96, inner=58) {
    const point=(r,a)=>`${(cx+r*Math.cos(a)).toFixed(2)} ${(cy+r*Math.sin(a)).toFixed(2)}`;
    if(end-start>=Math.PI*2-.0001){const mid=start+Math.PI;return `M ${point(outer,start)} A ${outer} ${outer} 0 1 1 ${point(outer,mid)} A ${outer} ${outer} 0 1 1 ${point(outer,start)} L ${point(inner,start)} A ${inner} ${inner} 0 1 0 ${point(inner,mid)} A ${inner} ${inner} 0 1 0 ${point(inner,start)} Z`;}
    const large=end-start>Math.PI?1:0;
    return `M ${point(outer,start)} A ${outer} ${outer} 0 ${large} 1 ${point(outer,end)} L ${point(inner,end)} A ${inner} ${inner} 0 ${large} 0 ${point(inner,start)} Z`;
  }
  function renderOverview() {
    const {materials,groups}=formulaCounts();
    $('overview-count').textContent = `${materials.length} 条详情素材 · ${materials.filter(m => m.formula.length).length} 条有可读公式`;
    if (!groups.length) { $('formula-chart').innerHTML='<p class="empty">当前范围暂无可读平台公式。</p>'; $('overview-secondary').hidden=true; return; }
    const max=Math.max(...groups.map(g=>g.count),1);
    $('formula-chart').innerHTML = `<div class="bar-track">${groups.map(g => `<button type="button" class="bar-cell ${state.formula===g.label?'active':''}" data-primary="${esc(g.label)}" aria-pressed="${state.formula===g.label}"><span class="count">${g.count}</span><span class="bar" style="height:${Math.max(5,Math.round(g.count/max*112))}px"></span><span class="label">${esc(g.label)}</span></button>`).join('')}</div>`;
    const selected=groups.find(g=>g.label===state.formula);
    $('overview-secondary').hidden=!selected;
    if (!selected) return;
    const total=selected.children.reduce((sum,c)=>sum+c.count,0);
    let angle=-Math.PI/2;
    const colors=['#5b8def','#14b8a6','#f59e0b','#8b5cf6','#ef6a6a','#64748b'];
    const slices=selected.children.map((c,i)=>{const end=angle+(total?c.count/total:0)*Math.PI*2;const mid=(angle+end)/2;const path=donutPath(angle,end);angle=end;const active=state.secondary===i;return `<path class="donut-segment ${active?'active':''}" data-secondary-index="${i}" d="${path}" fill="${colors[i%colors.length]}" style="--shift-x:${(Math.cos(mid)*8).toFixed(2)}px;--shift-y:${(Math.sin(mid)*8).toFixed(2)}px" tabindex="0" role="button" aria-pressed="${active}" aria-label="${esc(c.label)}，覆盖${c.count}个素材，占比${(c.count/total*100).toFixed(1)}%"></path>`}).join('');
    $('overview-secondary').innerHTML=`<div class="overview-secondary-ring"><svg viewBox="0 0 232 270" role="group" aria-label="${esc(selected.label)}二级内容公式环形图">${slices}<text class="donut-center-label" x="116" y="124">当前一级覆盖素材数</text><text class="donut-center-value" x="116" y="150">${selected.count}</text></svg></div><div class="overview-secondary-detail"><strong>${esc(selected.label)} · 二级内容公式分布</strong><div class="overview-secondary-list">${selected.children.map((c,i)=>`<button type="button" class="legend-item ${state.secondary===i?'active':''}" data-secondary-index="${i}" aria-pressed="${state.secondary===i}" aria-label="${esc(c.label)}，覆盖${c.count}个素材，占比${(c.count/total*100).toFixed(1)}%"><span class="legend-swatch" style="background:${colors[i%colors.length]}"></span><span>${esc(c.label)}<span class="legend-detail">${c.count} 个素材 · ${(c.count/total*100).toFixed(1)}%</span></span></button>`).join('') || '<span class="source-note">无二级标签</span>'}</div></div>`;
  }
  function quoteContext(text,term) {
    const at=text.indexOf(term),stops='。！？!?；;\n';
    if(at<0)return esc(term);
    let start=Math.max(0,at-100),end=Math.min(text.length,at+term.length+100);
    for(let i=at-1;i>=start;i--){if(stops.includes(text[i])){start=i+1;break;}}
    for(let i=at+term.length;i<end;i++){if(stops.includes(text[i])){end=i+1;break;}}
    return `${start?'…':''}${esc(text.slice(start,at))}<mark>${esc(term)}</mark>${esc(text.slice(at+term.length,end))}${end<text.length?'…':''}`;
  }
  function renderQuoteExplorer() {
    const {materials,groups}=formulaCounts();
    const selected=groups.find(g=>g.label===state.formula);
    $('quote-secondary-level').hidden=!selected;
    $('quote-primary').innerHTML=groups.map(g=>`<button type="button" class="${selected===g?'active':''}" data-quote-primary="${esc(g.label)}" aria-pressed="${selected===g}">${esc(g.label)} · ${g.count} 条素材</button>`).join('');
    $('quote-count').textContent=selected ? `${selected.label} · ${selected.count} 条素材` : `${materials.filter(m=>m.formula.length).length} 条素材有可读公式`;
    if (!groups.length) {
      $('quote-secondary').replaceChildren(); $('quote-results-head').textContent='';
      $('quote-results').innerHTML='<p class="empty">当前范围没有可读的平台内容公式。</p>';
      $('quote-pagination').hidden=true; state.quoteItems=[]; return;
    }
    if (!selected) {
      $('quote-secondary').replaceChildren(); $('quote-results-head').textContent='';
      $('quote-results').innerHTML='<p class="empty">选择一级内容公式后，可按二级公式查看逐字命中的脚本原句。</p>';
      $('quote-pagination').hidden=true; state.quoteItems=[]; return;
    }
    $('quote-secondary').innerHTML=selected.children.map((c,i)=>`<button type="button" class="${state.secondary===i?'active':''}" data-quote-secondary-index="${i}" aria-pressed="${state.secondary===i}">${esc(c.label)} · ${c.count} 条素材</button>`).join('');
    $('quote-secondary-title').textContent=`二级内容公式 · ${selected.label}`;
    const secondary=state.secondary==null ? null : selected.children[state.secondary]?.label;
    const items=[],seen=new Set();
    for (const m of materials) for (const g of m.formula) {
      if (g.label!==selected.label) continue;
      for (const c of g.children) {
        if (secondary && c.label!==secondary) continue;
        for (const term of c.terms) {
          if (!term || !m.text.includes(term)) continue;
          const key=JSON.stringify([m.id,g.label,c.label,term]);
          if (seen.has(key)) continue;
          seen.add(key); items.push({material:m,primary:g.label,secondary:c.label,term});
        }
      }
    }
    state.quoteItems=items;
    const materialCount=new Set(items.map(x=>x.material.id)).size;
    $('quote-results-head').textContent=`${secondary || selected.label} · ${items.length} 条逐字原句，来自 ${materialCount} 条素材`;
    const pageCount=Math.ceil(items.length/4);
    state.quotePage=Math.min(state.quotePage,Math.max(0,pageCount-1));
    const start=state.quotePage*4;
    $('quote-results').innerHTML=items.length ? items.slice(start,start+4).map((x,i)=>`<article class="quote-card"><blockquote>${quoteContext(x.material.text,x.term)}</blockquote><div class="quote-card-meta">${esc(x.primary)} / ${esc(x.secondary)} · 素材 ${esc(x.material.rank)}：${esc(x.material.title)}</div><button type="button" data-quote-index="${start+i}" aria-label="在素材${esc(x.material.title)}的完整脚本中定位此原句">定位完整脚本</button></article>`).join('') : '<p class="empty">当前公式有分类记录，但没有与完整脚本逐字命中的原句。</p>';
    $('quote-pagination').hidden=!items.length;
    $('quote-page-label').textContent=`第 ${state.quotePage+1} / ${pageCount} 页 · 共 ${items.length} 条`;
    $('quote-prev').disabled=state.quotePage===0;
    $('quote-next').disabled=state.quotePage>=pageCount-1;
  }
  function refresh() { renderOverview(); renderQuoteExplorer(); renderList(); renderSelected(); }
  $('brand-filter').innerHTML = model.brandTabs.map(tab => `<option value="${esc(tab.id)}">${esc(tab.label)}（${tab.ids.length}）</option>`).join('');
  $('brand-block').hidden = !model.brandTabs.length;
  $('brand-filter').addEventListener('change',e=>{state.brand=e.target.value;state.formula=null;state.secondary=null;state.quotePage=0;refresh();});
  $('active-filter').addEventListener('click',()=>{state.formula=null;state.secondary=null;state.quotePage=0;refresh();});
  document.addEventListener('click',e=>{
    const select=e.target.closest('[data-select]');if(select){selectMaterial(select.dataset.select);return;}
    const primary=e.target.closest('[data-primary],[data-quote-primary]');if(primary){const label=primary.dataset.primary || primary.dataset.quotePrimary;state.formula=state.formula===label?null:label;state.secondary=null;state.quotePage=0;$('quote-explorer').open=true;refresh();return;}
    const secondary=e.target.closest('[data-secondary-index],[data-quote-secondary-index]');if(secondary){const index=Number(secondary.dataset.secondaryIndex ?? secondary.dataset.quoteSecondaryIndex);state.secondary=state.secondary===index?null:index;state.quotePage=0;$('quote-explorer').open=true;refresh();return;}
    const quote=e.target.closest('[data-quote-index]');if(quote){const item=state.quoteItems[Number(quote.dataset.quoteIndex)];if(item){selectMaterial(item.material.id);jumpToTerm(item.term);}return;}
    const page=e.target.closest('#quote-prev,#quote-next');if(page){state.quotePage+=page.id==='quote-next'?1:-1;renderQuoteExplorer();return;}
    const term=e.target.closest('[data-formula-step]');if(term){const [g,c]=term.dataset.formulaStep.split(':').map(Number);jumpToTerm(current()?.formula?.[g]?.children?.[c]?.terms?.[0] || '');return;}
  });
  document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ') && e.target.matches('path[data-secondary-index]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  const dialog=$('metric-dialog');
  $('metric-open').addEventListener('click',()=>{
    const m=current();if(!m)return;
    const selected=currentMetrics(m);
    $('metric-options').innerHTML=m.metrics.map(x=>`<label><input type="checkbox" value="${esc(x.id)}" ${selected.has(x.id)?'checked':''}> ${esc(x.label)} <small>· ${esc(x.value)}</small></label>`).join('');
    dialog.showModal();
  });
  $('metric-reset').addEventListener('click',()=>{const m=current();if(!m)return;const ids=new Set(m.metrics.filter(x=>x.default).map(x=>x.id));$('metric-options').querySelectorAll('input').forEach(x=>x.checked=ids.has(x.value));});
  $('metric-cancel').addEventListener('click',()=>dialog.close());
  $('metric-apply').addEventListener('click',()=>{const m=current();if(!m)return;savedMetrics.set(m.id,new Set([...$('metric-options').querySelectorAll('input:checked')].map(x=>x.value)));dialog.close();renderSelected();});
  window.addEventListener('hashchange',()=>{const id=decodeURIComponent((location.hash.match(/^#material=(.*)$/)||[])[1]||'');if(materialById.has(id))selectMaterial(id,false);});
  refresh();
})();
"""


def render_page(model: dict) -> str:
    scope = ''.join(f'<div><small>{escape(str(label))}</small><strong>{escape(str(value if value not in (None, "") else "—"))}</strong></div>'
                    for label, value in model['scope'])
    fallback = ''.join('<details><summary>' + escape(str(m['rank'])) + '. ' + escape(m['title']) +
                       '</summary><pre>' + escape(m['text'] or '无可用脚本文本') + '</pre></details>'
                       for m in model['materials'])
    data = json.dumps(model, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    source_note = '<p class="source-note" id="source-note"></p>' if model['platform'] == '云图' else ''
    quote_section = ('<details class="quote-explorer panel" id="quote-explorer">'
                     '<summary>内容公式与原句 <small id="quote-count"></small></summary>'
                     '<div class="quote-explorer-body"><section class="quote-level quote-level-primary" aria-label="一级内容公式"><h3>一级内容公式</h3><div id="quote-primary" class="quote-primary"></div></section>'
                     '<section class="quote-level quote-level-secondary" id="quote-secondary-level" aria-label="二级内容公式" hidden><h3 id="quote-secondary-title">二级内容公式</h3><div id="quote-secondary" class="quote-secondary"></div></section>'
                     '<p id="quote-results-head" class="quote-results-head"></p>'
                     '<div id="quote-results" class="quote-results"></div>'
                     '<nav id="quote-pagination" class="quote-pagination" aria-label="原句翻页" hidden><button type="button" id="quote-prev">上一页</button><span id="quote-page-label" aria-live="polite"></span><button type="button" id="quote-next">下一页</button></nav>'
                     '</div></details>')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>{escape(model['title'])}</title><style>{STYLE}</style><style>{QUOTE_STYLE}</style><style>.js .fallback{{display:none}}</style></head><body><main class="app"><header class="top"><div><p class="eyebrow">{escape(model['platform'])} · 详情脚本</p><h1>{escape(model['title'])}</h1><p>{escape(model['summary'])}</p></div></header><div class="top-tools"><details class="panel"><summary>本次取数与选材条件</summary><div class="scope-grid">{scope}</div></details></div><details class="overview panel" id="overview"><summary>本批详情的内容公式分布 <small id="overview-count"></small></summary><div class="overview-body"><p class="overview-note">仅统计平台已核验的可读公式；点击一级柱图可查看二级分布，并筛选左侧详情素材。品牌筛选只作用于本批详情。</p><div class="chart-row" id="formula-chart"></div><div class="overview-secondary" id="overview-secondary" hidden></div></div></details>{quote_section}<div class="workspace"><aside class="selector panel"><h2>详情素材</h2><div id="brand-block"><label for="brand-filter">本轮标题规则品牌分类</label><select id="brand-filter"></select><p class="source-note">此分类不是平台权威品牌归属。</p></div><button id="active-filter" class="subtle-button" type="button" hidden></button><p class="list-note" id="list-count"></p><div id="item-list" class="item-list"></div></aside><section class="reader panel" aria-label="当前素材脚本"><p class="empty" id="reader-empty" hidden>请选择详情素材。</p><div id="reader-content"><div class="reader-head"><p class="eyebrow">当前详情素材</p><h2 id="material-title"></h2><span id="material-source" class="status"></span><p class="meta" id="material-meta"></p></div><div class="block-head"><h3>{'投放数据' if model['platform']=='千川' else '核心数据'}</h3><button class="subtle-button" type="button" id="metric-open">自定义指标 · <span id="metric-count"></span></button></div><div class="metric-grid" id="metric-grid"></div><div class="block-head"><h3>完整脚本正文</h3></div>{source_note}<div id="script-text" class="script-copy"></div><details class="layered" id="layered-text" hidden><summary>查看分层来源文本</summary><div id="layered-body"></div></details></div></section><aside class="insight panel" aria-label="当前素材内容公式"><div class="insight-block"><h2>当前素材的内容公式</h2><div id="formula-list"></div></div></aside></div></main><section class="fallback panel"><h2>全部详情脚本（无 JavaScript 阅读模式）</h2>{fallback}</section><dialog id="metric-dialog" class="metric-dialog"><h2>当前素材自定义指标</h2><p class="source-note">仅列出本素材实际返回的指标；本页选择仅在当前页面会话中生效。</p><div id="metric-options" class="metric-options"></div><div class="metric-actions"><button type="button" id="metric-reset">恢复默认</button><button type="button" id="metric-cancel">取消</button><button type="button" id="metric-apply" class="primary">确定</button></div></dialog><script id="workbench-model" type="application/json">{data}</script><script>{SCRIPT}</script></body></html>'''
