"""Offline metric picker; only the current report's scalar metrics are selectable."""
from html import escape

DEFAULT_IDS = ('stat_cost_for_roi2', 'stat_cost_for_overall_roi2',
               'total_prepay_and_pay_settle_roi2_1h', 'total_order_settle_amount_for_roi2_1h',
               'video_play_count_for_roi2_v2', 'video_play_finish_rate_for_roi2_v2')
SINGLE_DEFAULT_IDS = ('stat_cost_for_overall_roi2', 'stat_cost_for_roi2',
                      'total_pay_order_count_for_roi2', 'total_order_settle_amount_for_roi2_1h',
                      'total_prepay_and_pay_settle_roi2_1h', 'live_show_count_for_roi2_v2',
                      'live_watch_count_for_roi2_v2', 'live_cvr_rate_for_roi2_v2')
GROUPS = ('整体指标', '净成交指标', '周期结算', '追投调控', '视频互动', '其他指标')


def default_columns(columns):
    keys = {column['key'] for column in columns}
    chosen = [column for column in columns if column['key'] in DEFAULT_IDS]
    if columns and columns[0] not in chosen:
        chosen.insert(0, columns[0])
    return chosen if keys.intersection(DEFAULT_IDS) else columns[:6]


def default_single_columns(columns):
    """Match the meta skill's eight preferred delivery fields and sparse fallback."""
    preferred = [column for column in columns if column['key'] in SINGLE_DEFAULT_IDS]
    return preferred if preferred else columns[:8]


def render_picker(columns, defaults, single_columns=()):
    esc = lambda value: escape(str(value), quote=True)
    selected = {column['key'] for column in defaults}
    leaderboard_keys = {column['key'] for column in columns}
    all_columns = [*columns, *(column for column in single_columns if column['key'] not in leaderboard_keys)]
    groups = [group for group in GROUPS if any(column.get('group', '其他指标') == group for column in all_columns)]
    parts = ['<dialog id="metric-dialog" aria-labelledby="metric-dialog-title"><header class="metric-dialog-header"><div><h2 id="metric-dialog-title">自定义指标</h2><p id="metric-dialog-description" class="muted">选择需要展示的指标，按右侧顺序排列</p></div><button type="button" data-metric-action="cancel" aria-label="关闭自定义指标">×</button></header><div class="metric-dialog-body"><nav class="metric-groups" aria-label="指标分组">']
    for group in groups:
        parts.append(f'<button type="button" data-metric-group="{esc(group)}">{esc(group)}<span>{sum(c.get("group", "其他指标") == group for c in columns)}</span></button>')
    parts.append('</nav><section class="metric-options-pane" aria-label="可选指标"><input id="metric-search" type="search" placeholder="搜索指标" aria-label="搜索指标"><div class="metric-options">')
    for index, column in enumerate(all_columns):
        key, label, group = column['key'], column['label'], column.get('group', '其他指标')
        checked = ' checked' if key in selected else ''
        unit = f'（{column["unit"]}）' if column.get('unit') else ''
        hidden = '' if key in leaderboard_keys else ' hidden'
        parts.append(f'<label class="metric-option" data-option-group="{esc(group)}"{hidden}><input type="checkbox" data-pick-metric="{esc(key)}" data-label="{esc(label)}" data-unit="{esc(unit)}" data-column-index="{index if key in leaderboard_keys else -1}" data-leaderboard-choice="{str(key in leaderboard_keys).lower()}"{checked}><span>{esc(label)}</span></label>')
    parts.append('</div><p id="metric-no-match" class="empty" hidden>没有匹配指标</p></section><aside class="metric-selected" aria-label="已选择指标"><div class="metric-selected-header"><strong>已选择 <span id="metric-count"></span></strong><div><button type="button" data-metric-action="all">全选</button><button type="button" data-metric-action="clear">全不选</button></div></div><p class="metric-fixed" id="metric-fixed">素材名称 / ID <span>固定</span></p><ol id="metric-selected-list"></ol></aside></div><footer class="metric-dialog-footer"><button type="button" data-metric-action="reset">恢复默认</button><div><button type="button" data-metric-action="cancel">取消</button><button type="button" class="primary" data-metric-action="confirm">确定</button></div></footer></dialog>')
    return ''.join(parts)


CSS = '''
#metric-dialog{width:min(1050px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:0;border:1px solid var(--line);border-radius:16px;color:var(--text);box-shadow:0 24px 80px #20375430;overflow:auto}
#metric-dialog::backdrop{background:#172b4d60}#metric-dialog:not([open]){display:none}.metric-dialog-header{display:flex;justify-content:space-between;align-items:start;padding:22px 24px;border-bottom:1px solid var(--line)}.metric-dialog-header h2{margin:0}.metric-dialog-header p{font-size:13px;margin:8px 0 0}.metric-dialog-header>button{font-size:22px;padding:2px 12px}.metric-dialog-body{display:grid;grid-template-columns:145px minmax(0,1fr) 310px;height:430px;min-height:0}.metric-groups{padding:16px 10px;background:var(--soft);overflow:auto}.metric-groups button{display:flex;justify-content:space-between;width:100%;text-align:left;border:0;background:none;font-size:13px;gap:12px;margin-bottom:5px;padding:10px}.metric-groups button span{color:var(--muted)}.metric-groups button.active{background:var(--accent-soft);color:var(--accent)}.metric-options-pane{padding:18px;overflow:auto}.metric-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:15px}.metric-option{display:flex;gap:8px;align-items:start;padding:10px 5px;font-size:13px;color:var(--text);line-height:1.5;cursor:pointer}.metric-option input{margin-top:3px;accent-color:var(--accent)}.metric-selected{border-left:1px solid var(--line);padding:16px;overflow:auto;min-width:0}.metric-selected-header{display:flex;justify-content:space-between;align-items:center;gap:5px;font-size:13px}.metric-selected-header button{font-size:12px;min-height:28px;border:0;padding:4px}.metric-fixed{display:flex;justify-content:space-between;background:var(--soft);padding:11px;border-radius:8px;font-size:13px}.metric-fixed span{color:var(--muted);font-size:12px}#metric-selected-list{list-style:none;padding:0}#metric-selected-list li{display:flex;align-items:center;gap:5px;padding:9px 8px;border:1px solid var(--line);border-radius:8px;margin:7px 0;font-size:12px}#metric-selected-list li>span{flex:1;min-width:0;overflow-wrap:anywhere}#metric-selected-list button{padding:2px 5px;min-height:26px;border:0;font-size:13px}.metric-dialog-footer{display:flex;justify-content:space-between;gap:12px;padding:16px 24px;border-top:1px solid var(--line)}.metric-dialog-footer>div{display:flex;gap:10px}.metric-dialog-footer .primary{background:var(--accent);color:white;border-color:var(--accent)}
@media(max-width:760px){.metric-dialog-body{display:flex;flex-direction:column;height:auto;max-height:65dvh;overflow:auto}.metric-groups{display:flex;gap:6px;flex-shrink:0;padding:8px;overflow:auto}.metric-groups button{white-space:nowrap;width:auto;margin:0}.metric-options-pane{overflow:visible;padding:12px}.metric-selected{border-left:0;border-top:1px solid var(--line);max-height:210px;flex-shrink:0}.metric-dialog-header{padding:16px}.metric-dialog-footer{padding:12px}.metric-dialog-footer button{font-size:12px}.toolbar{flex-wrap:wrap}}
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
  const defaults = leaderboardChoices.filter(c => c.checked).map(c => c.dataset.pickMetric);
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
      ? '选择后将按照自定义指标顺序呈现当前素材的投放指标' : '选择需要展示的指标，按右侧顺序排列';
    $('metric-fixed').firstChild.textContent = card ? '当前素材名称已在详情标题中固定展示 ' : '素材名称 / ID ';
    refresh(); dialog.showModal(); button.setAttribute('aria-expanded', 'true'); search.focus();
  }
  $('metric-button').onclick = () => { open($('metric-button'), null);
  };
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
