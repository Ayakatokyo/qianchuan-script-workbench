"""Offline metric picker; only the current report's scalar metrics are selectable."""
from html import escape
import json

# The meta report also defaults to the material name, duration, creation time,
# and source. The workbench keeps the name as a fixed column; the other three
# dimensions are not present in its verified summary, so select the available
# metric portion of the same default list.
DEFAULT_IDS = ('stat_cost_for_overall_roi2',
               'total_prepay_and_pay_settle_roi2_1h',
               'total_order_settle_amount_for_roi2_1h')
SINGLE_DEFAULT_IDS = ('stat_cost_for_overall_roi2', 'stat_cost_for_roi2',
                      'total_pay_order_count_for_roi2', 'total_order_settle_amount_for_roi2_1h',
                      'total_prepay_and_pay_settle_roi2_1h', 'live_show_count_for_roi2_v2',
                      'live_watch_count_for_roi2_v2', 'live_cvr_rate_for_roi2_v2')
GROUPS = ('整体指标', '净成交指标', '周期结算', '追投调控', '视频互动', '其他指标')


def default_columns(columns):
    by_key = {column['key']: column for column in columns}
    chosen = [by_key[key] for key in DEFAULT_IDS if key in by_key]
    return chosen if chosen else columns[:6]


def default_single_columns(columns):
    """Match the meta skill's eight preferred delivery fields and sparse fallback."""
    preferred = [column for column in columns if column['key'] in SINGLE_DEFAULT_IDS]
    return preferred if preferred else columns[:8]


def render_picker(columns, defaults, single_columns=()):
    esc = lambda value: escape(str(value), quote=True)
    selected = {column['key'] for column in defaults}
    leaderboard_keys = {column['key'] for column in columns}
    all_columns = [*columns, *(column for column in single_columns if column['key'] not in leaderboard_keys)]
    available_groups = {column.get('group', '其他指标') for column in all_columns}
    groups = [group for group in GROUPS if group in available_groups]
    groups.extend(sorted(available_groups.difference(groups)))
    default_order = esc(json.dumps([column['key'] for column in defaults], ensure_ascii=False))
    parts = [f'<dialog id="metric-dialog" aria-labelledby="metric-dialog-title" data-default-selection="{default_order}"><header class="metric-dialog-header"><div><h2 id="metric-dialog-title">自定义指标</h2><p id="metric-dialog-description" class="muted">选择后将按照自定义指标顺序呈现表格列</p></div><button type="button" data-metric-action="cancel" aria-label="关闭自定义指标">×</button></header><div class="metric-dialog-body"><nav class="metric-groups" aria-label="指标分组">']
    for group in groups:
        parts.append(f'<button type="button" data-metric-group="{esc(group)}">{esc(group)}<span>{sum(c.get("group", "其他指标") == group for c in columns)}</span></button>')
    parts.append('</nav><section class="metric-options-pane" aria-label="可选指标"><div class="metric-search-wrap"><input id="metric-search" type="search" placeholder="搜索指标" aria-label="搜索指标"></div><div class="metric-options-scroll"><h3 id="metric-current-group"></h3><div class="metric-options">')
    for index, column in enumerate(all_columns):
        key, label, group = column['key'], column['label'], column.get('group', '其他指标')
        checked = ' checked' if key in selected else ''
        unit = f'（{column["unit"]}）' if column.get('unit') else ''
        hidden = '' if key in leaderboard_keys else ' hidden'
        parts.append(f'<label class="metric-option" data-option-group="{esc(group)}"{hidden}><input type="checkbox" data-pick-metric="{esc(key)}" data-label="{esc(label)}" data-unit="{esc(unit)}" data-column-index="{index if key in leaderboard_keys else -1}" data-leaderboard-choice="{str(key in leaderboard_keys).lower()}"{checked}><span>{esc(label)}</span></label>')
    parts.append('</div><p id="metric-no-match" class="empty" hidden>没有匹配指标</p></div></section><aside class="metric-selected" aria-label="已选择指标"><div class="metric-selected-header"><strong>已选择 <span id="metric-count"></span></strong><div><button type="button" data-metric-action="all">全选</button><button type="button" data-metric-action="clear">全不选</button></div></div><p class="metric-fixed" id="metric-fixed">素材名称 / ID <span>固定</span></p><ol id="metric-selected-list"></ol></aside></div><footer class="metric-dialog-footer"><p id="metric-footer-note">素材名称为固定列，其他列按自定义指标顺序排列</p><div><button type="button" data-metric-action="reset">恢复默认</button><button type="button" data-metric-action="cancel">取消</button><button type="button" class="primary" data-metric-action="confirm">确定</button></div></footer></dialog>')
    return ''.join(parts)


CSS = '''
#metric-dialog{display:flex;flex-direction:column;width:min(1180px,calc(100vw - 48px));height:min(760px,calc(100dvh - 48px));max-height:none;padding:0;border:1px solid var(--line);border-radius:16px;color:var(--text);box-shadow:0 24px 70px rgba(15,23,42,.24);overflow:hidden}
#metric-dialog::backdrop{background:rgba(15,23,42,.42);backdrop-filter:blur(2px)}#metric-dialog:not([open]){display:none}
.metric-dialog-header{display:flex;justify-content:space-between;align-items:start;gap:20px;padding:22px 24px 16px;border-bottom:1px solid var(--line)}
.metric-dialog-header h2{margin:0;font-size:20px}.metric-dialog-header p{font-size:13px;margin:6px 0 0}.metric-dialog-header>button{min-width:36px;min-height:36px;padding:0;border:0;border-radius:50%;color:var(--muted);font-size:24px;line-height:1}
.metric-dialog-body{display:grid;grid-template-columns:190px minmax(0,1fr) 290px;flex:1;min-height:0}
.metric-groups{padding:14px 10px;background:#f8fafc;border-right:1px solid var(--line);overflow:auto}
.metric-groups button{display:flex;justify-content:space-between;width:100%;min-height:38px;text-align:left;border:0;background:none;color:#45546b;font-size:13px;gap:12px;margin-bottom:4px;padding:8px 10px}
.metric-groups button span{color:var(--muted);font-size:12px}.metric-groups button.active{background:var(--accent-soft);color:#1d4ed8;font-weight:650;box-shadow:inset 3px 0 0 var(--accent)}
.metric-options-pane{display:flex;flex-direction:column;min-width:0;min-height:0}
.metric-search-wrap{padding:14px 20px;border-bottom:1px solid var(--line)}.metric-search-wrap input{height:40px;min-height:40px;font-size:14px}
.metric-options-scroll{min-height:0;padding:18px 22px 24px;overflow:auto}.metric-options-scroll h3{margin:0 0 10px;font-size:14px;color:#263752}
.metric-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 12px}
.metric-option{display:flex;gap:9px;align-items:flex-start;min-height:40px;padding:9px 10px;border:1px solid transparent;border-radius:8px;font-size:14px;color:#34445e;line-height:1.35;cursor:pointer}
.metric-option:hover{background:#f8fafc;border-color:#e6ebf3}.metric-option:has(input:checked){background:var(--accent-soft);border-color:#bfdbfe;color:#1e3a8a}.metric-option input{flex:none;width:16px;height:16px;margin:1px 0 0;accent-color:var(--accent)}
.metric-selected{display:flex;flex-direction:column;min-width:0;min-height:0;border-left:1px solid var(--line);background:#fbfcfe}
.metric-selected-header{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:16px 16px 12px;border-bottom:1px solid var(--line);font-size:14px}
.metric-selected-header button{font-size:12px;min-height:28px;border:0;padding:4px 7px;color:var(--accent)}.metric-fixed{display:flex;justify-content:space-between;gap:8px;margin:12px 12px 0;padding:7px 8px;background:#f1f3f7;border-radius:7px;font-size:13px;color:#34445e}
.metric-fixed span{color:var(--muted);font-size:11px}#metric-selected-list{min-height:0;list-style:none;padding:0 12px 12px;margin:0;overflow:auto}
#metric-selected-list li{display:flex;align-items:center;gap:5px;min-height:38px;padding:7px 8px;background:#f1f3f7;border-radius:7px;margin:7px 0;font-size:13px;color:#34445e}
#metric-selected-list li>span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#metric-selected-list button{padding:2px 5px;min-height:26px;border:0;background:none;font-size:13px;color:var(--muted)}
.metric-dialog-footer{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 24px;border-top:1px solid var(--line)}
.metric-dialog-footer p{margin:0;color:var(--muted);font-size:12px}.metric-dialog-footer>div{display:flex;gap:10px}.metric-dialog-footer .primary{background:var(--accent);color:white;border-color:var(--accent)}
@media(max-width:900px){.metric-dialog-body{grid-template-columns:160px minmax(0,1fr) 230px}}
@media(max-width:700px){#metric-dialog{width:calc(100vw - 20px);height:calc(100dvh - 20px)}.metric-dialog-body{display:flex;flex-direction:column;overflow:auto}.metric-groups{display:flex;gap:6px;flex:none;padding:10px;overflow-x:auto;overflow-y:hidden;border-right:0;border-bottom:1px solid var(--line)}.metric-groups button{white-space:nowrap;width:auto;margin:0}.metric-options-scroll{overflow:visible}.metric-options{grid-template-columns:1fr}.metric-selected{flex:none;max-height:190px;border-left:0;border-top:1px solid var(--line)}.metric-dialog-header{padding:16px}.metric-dialog-footer{padding:12px;align-items:flex-end;flex-direction:column}.metric-dialog-footer p{align-self:flex-start}.metric-dialog-footer>div{width:100%}.metric-dialog-footer button{flex:1;font-size:12px}}
'''

SCRIPT = r'''
function initMetricPicker(rows, cards, onApply) {
  const $ = id => document.getElementById(id);
  const choices = Array.from(document.querySelectorAll('[data-pick-metric]'));
  if (!choices.length) return;
  const dialog = $('metric-dialog'), search = $('metric-search');
  const groups = Array.from(document.querySelectorAll('[data-metric-group]'));
  const normalize = text => String(text || '').normalize('NFKC').toLocaleLowerCase().trim();
  const leaderboardChoices = choices.filter(c => c.dataset.leaderboardChoice === 'true');
  const defaults = JSON.parse(dialog.dataset.defaultSelection || '[]');
  let active = [...defaults], draft = [...active], group = groups[0]?.dataset.metricGroup || '';
  let scope = 'leaderboard', currentCard = null, opener = $('metric-button');
  const singleSelections = new Map();
  const lookup = new Map(choices.map(c => [c.dataset.pickMetric, c]));
  // Keep raw numeric values for sorting and ValueStr for exact platform display.
  const values = new Map(rows.map(row => [row, JSON.parse(row.dataset.values || '[]')]));
  const singleChoices = () => {
    if (!currentCard) return [];
    const available = new Set(JSON.parse(currentCard.dataset.singleFields || '[]'));
    return choices.filter(choice => available.has(choice.dataset.pickMetric));
  };
  const catalog = () => scope === 'single' ? singleChoices() : leaderboardChoices;
  const defaultSelection = () => scope === 'single'
    ? JSON.parse(currentCard.dataset.singleDefaults || '[]') : defaults;
  function selectGroup() {
    const available = catalog();
    groups.forEach(button => {
      const count = available.filter(choice => choice.parentElement.dataset.optionGroup === button.dataset.metricGroup).length;
      button.hidden = !count;
      button.querySelector('span').textContent = String(count);
    });
    if (!groups.some(button => !button.hidden && button.dataset.metricGroup === group))
      group = groups.find(button => !button.hidden)?.dataset.metricGroup || '';
  }
  function renderOptions() {
    const query = normalize(search.value);
    const available = new Set(catalog());
    let visible = 0;
    choices.forEach(choice => {
      choice.checked = draft.includes(choice.dataset.pickMetric);
      const match = available.has(choice) && (query ? normalize(choice.dataset.label + ' ' + choice.dataset.pickMetric).includes(query) : choice.parentElement.dataset.optionGroup === group);
      choice.parentElement.hidden = !match;
      if (match) visible++;
    });
    groups.forEach(button => {
      const selected = !query && button.dataset.metricGroup === group;
      button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
    });
    $('metric-current-group').textContent = query ? '搜索结果' : group;
    $('metric-no-match').hidden = visible > 0;
    $('metric-count').textContent = `(${draft.length})`;
  }
  function renderSelected() {
    const list = $('metric-selected-list'); list.replaceChildren();
    draft.forEach((key, index) => {
      const item = document.createElement('li'), text = document.createElement('span');
      text.textContent = lookup.get(key).dataset.label; item.appendChild(text);
      for (const [label, symbol, delta] of [['上移', '↑', -1], ['下移', '↓', 1], ['移除', '×', 0]]) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = symbol;
        button.setAttribute('aria-label', label + text.textContent);
        button.disabled = delta === -1 && index === 0 || delta === 1 && index === draft.length - 1;
        button.onclick = () => {
          if (!delta) draft.splice(index, 1);
          else [draft[index], draft[index + delta]] = [draft[index + delta], draft[index]];
          renderOptions(); renderSelected();
          const next = list.children[Math.min(index, draft.length - 1)];
          if (next) next.querySelector('button:not(:disabled)').focus();
        }; item.appendChild(button);
      }
      list.appendChild(item);
    });
  }
  function refresh() { selectGroup(); renderOptions(); renderSelected(); }
  function close() { dialog.close(); opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  function renderSingleCards(card, selected) {
    const grid = card.querySelector('[data-single-metric-grid]');
    const metrics = Array.from(grid.querySelectorAll('[data-single-metric]'));
    const byKey = new Map(metrics.map(metric => [metric.dataset.singleMetric, metric]));
    selected.forEach(key => { if (byKey.has(key)) grid.appendChild(byKey.get(key)); });
    metrics.forEach(metric => { metric.hidden = !selected.includes(metric.dataset.singleMetric); });
    card.querySelector('[data-single-metric-summary]').textContent = `已展示指标 ${selected.length} / ${metrics.length}`;
    card.querySelector('[data-single-metric-empty]').hidden = selected.length > 0;
  }
  function apply() {
    if (scope === 'single') {
      const selected = [...draft];
      singleSelections.set(currentCard.dataset.index, selected);
      renderSingleCards(currentCard, selected);
      close(); return;
    }
    active = [...draft];
    const header = $('material-header');
    Array.from(header.querySelectorAll('[data-column]')).forEach(cell => cell.remove());
    active.forEach(key => {
      const choice = lookup.get(key), th = document.createElement('th'), button = document.createElement('button');
      th.scope = 'col'; th.dataset.column = key;
      button.type = 'button'; button.dataset.sortMetric = key; button.dataset.label = choice.dataset.label;
      button.textContent = choice.dataset.label + choice.dataset.unit;
      const marker = document.createElement('span'); marker.className = 'sort-mark'; button.appendChild(marker);
      th.appendChild(button); header.appendChild(th);
    });
    rows.forEach(row => {
      Array.from(row.querySelectorAll('[data-metric]')).forEach(cell => cell.remove());
      active.forEach(key => {
        const pair = values.get(row)[Number(lookup.get(key).dataset.columnIndex)] || [null, null];
        const cell = document.createElement('td'); cell.dataset.metric = key;
        cell.dataset.sortValue = pair[0] == null ? '' : String(pair[0]);
        cell.textContent = pair[1] == null || pair[1] === '' ? '未提供' : String(pair[1]);
        row.appendChild(cell);
      });
    });
    onApply(active); close();
  }
  function open(button, card) {
    scope = card ? 'single' : 'leaderboard'; currentCard = card; opener = button;
    draft = card ? [...(singleSelections.get(card.dataset.index) || defaultSelection())] : [...active];
    search.value = ''; group = groups[0]?.dataset.metricGroup || '';
    $('metric-dialog-description').textContent = card
      ? '选择后将按照自定义指标顺序呈现当前素材的投放指标' : '选择后将按照自定义指标顺序呈现表格列';
    $('metric-fixed').firstChild.textContent = card ? '当前素材名称已在详情标题中固定展示 ' : '素材名称 / ID ';
    $('metric-footer-note').textContent = card
      ? '当前素材名称已在详情标题中固定展示，其他指标按自定义顺序排列'
      : '素材名称为固定列，其他列按自定义指标顺序排列';
    refresh(); dialog.showModal(); button.setAttribute('aria-expanded', 'true'); search.focus();
  }
  if ($('metric-button')) $('metric-button').onclick = () => open($('metric-button'), null);
  cards.forEach(card => {
    if (typeof card.querySelector !== 'function') return;
    const button = card.querySelector('[data-single-metric-button]');
    if (!button) return;
    renderSingleCards(card, JSON.parse(card.dataset.singleDefaults || '[]'));
    button.hidden = false;
    button.onclick = () => open(button, card);
  });
  dialog.oncancel = event => { event.preventDefault(); close(); };
  dialog.onclick = event => { if (event.target === dialog) close(); };
  search.oninput = renderOptions;
  groups.forEach(button => { button.onclick = () => { group = button.dataset.metricGroup; search.value = ''; renderOptions(); }; });
  choices.forEach(choice => { choice.onchange = () => {
    const key = choice.dataset.pickMetric;
    draft = choice.checked ? [...draft.filter(k => k !== key), key] : draft.filter(k => k !== key); refresh();
  }; });
  document.querySelectorAll('[data-metric-action]').forEach(button => { button.onclick = () => {
    const action = button.dataset.metricAction;
    if (action === 'confirm') return apply();
    if (action === 'cancel') return close();
    draft = action === 'all' ? catalog().map(c => c.dataset.pickMetric) : action === 'reset' ? [...defaultSelection()] : [];
    refresh();
  }; });
}
'''
