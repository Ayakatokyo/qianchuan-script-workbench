"""Offline formula/text links, using only explicit labels and exact quotations.

Every quotation occurrence is linked. Overlapping quotes are split at their
boundaries; each resulting span keeps all memberships, without losing text.
"""
from __future__ import annotations

from html import escape
from typing import Any, Mapping


_COLORS = {"商品卖点": "#db5e65", "价格优惠": "#8053ce", "行动号召": "#536d91", "商品信息": "#2563c5", "用户痛点": "#bf791c", "品牌信息": "#168465", "服务卖点": "#00858b"}


def _e(value: Any) -> str:
    # Character references preserve CR too: literal CR is normalized by HTML.
    return escape(str(value), quote=True).replace("\r", "&#13;")


def _ordered_groups(script: Mapping, groups: list) -> list[dict]:
    readable = []
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("label"), str) or not group["label"].strip():
            continue
        children = [dict(child) for child in group.get("children", [])
                    if isinstance(child, Mapping) and isinstance(child.get("label"), str) and child["label"].strip()]
        readable.append({**group, "children": children})
    formula = script.get("formula") if (script.get("fieldAvailability") or {}).get("formula") else None
    labels = formula.get("labels") if isinstance(formula, Mapping) else None
    if not isinstance(labels, list):
        return readable
    remaining = list(readable)
    ordered = []
    for entry in labels:
        if not isinstance(entry, Mapping) or entry.get("level_1_label") is None:
            continue
        candidates = [item for item in remaining if item.get("id") is not None and str(item["id"]) == str(entry["level_1_label"])]
        if not candidates:
            continue  # A numeric formula ID alone is never a readable label.
        child_ids = entry.get("level_2_labels")
        child_ids = [str(item) for item in child_ids] if isinstance(child_ids, list) else []
        # Distinct occurrences of the same primary can have different children.
        group = next((item for item in candidates if sorted(str(child.get("id")) for child in item["children"]) == sorted(child_ids)), candidates[0])
        remaining.remove(group)
        children = list(group["children"])
        selected = []
        for child_id in child_ids:
            child = next((item for item in children if item.get("id") is not None and str(item["id"]) == child_id), None)
            if child is not None:
                selected.append(child)
                children.remove(child)
        ordered.append({**group, "children": selected + children})
    return ordered + remaining


def _linked_text(text: str, groups: list[dict]) -> str:
    intervals = []
    for group_index, group in enumerate(groups):
        for child_index, child in enumerate(group["children"]):
            quotes = child.get("quotes")
            if not isinstance(quotes, list):
                continue
            for quote in dict.fromkeys(item for item in quotes if isinstance(item, str) and item.strip()):
                start = text.find(quote)
                while start >= 0:
                    intervals.append((start, start + len(quote), f"p{group_index}", f"c{group_index}-{child_index}", group["color"], child["label"]))
                    start = text.find(quote, start + 1)
    boundaries = sorted({0, len(text), *(point for interval in intervals for point in interval[:2])})
    parts = []
    for start, end in zip(boundaries, boundaries[1:]):
        body = _e(text[start:end])
        matches = [item for item in intervals if item[0] <= start and item[1] >= end]
        if not matches:
            parts.append(body)
            continue
        keys = list(dict.fromkeys(key for item in matches for key in item[2:4]))
        labels = list(dict.fromkeys(item[5] for item in matches))
        parts.append(f'<mark class="linked-quote" tabindex="0" role="button" aria-pressed="false" data-linked-keys="{" ".join(keys)}" '
                     f'style="--linked-color:{matches[0][4]}" title="定位公式：{_e("、".join(labels))}">{body}</mark>')
    return ''.join(parts)


def render_linked_script(script: Mapping[str, Any], groups: list[dict], *, material_index: int) -> str:
    """Render two sections; the caller includes CSS and SCRIPT once per page."""
    if isinstance(material_index, bool) or not isinstance(material_index, int) or material_index < 0:
        raise ValueError("material_index must be a nonnegative integer")
    trusted = script.get("deliveryStatus") in {"available", "missing"}
    groups = _ordered_groups(script, groups) if trusted else []
    text = script.get("text") if script.get("deliveryStatus") == "available" and script.get("textAvailable") else None
    text = text if isinstance(text, str) and text else None
    for group in groups:
        group["color"] = _COLORS.get(group["label"], "#536d91")
    copy_text = '\n'.join('\n'.join([group['label'], *('  - ' + child['label'] for child in group['children'])]) for group in groups)
    parts = [f'<div class="linked-script-workspace" data-linked-script="{material_index}">',
             '<h3 class="linked-analysis-title">脚本分析</h3>',
             '<section class="single-block"><div class="linked-heading"><h3>本视频内容公式</h3>']
    if copy_text:
        parts.append('<button type="button" class="linked-copy" data-linked-copy="formula" aria-label="复制本视频内容公式">复制公式</button>')
    parts.append('</div><p class="linked-status" data-linked-status aria-live="polite">点击内容公式或下方脚本文案，可双向定位。</p>')
    if groups:
        parts.append('<div class="linked-formula-legend" aria-label="按顺序排列的一级内容公式">')
        for group in groups:
            parts.append(f'<span class="linked-legend-item"><i class="linked-legend-dot" style="background:{group["color"]}" aria-hidden="true"></i>{_e(group["label"])}</span>')
        parts.append('</div>')
        parts.append('<div class="linked-formula-flow" aria-label="内容公式层级链路">')
        for index, group in enumerate(groups):
            if index:
                parts.append('<span class="linked-flow-arrow" aria-hidden="true">→</span>')
            parts.append(f'<div class="linked-formula-group" style="--linked-color:{group["color"]}">')
            parts.append(f'<button type="button" class="linked-formula-node linked-primary" data-linked-node="p{index}" data-linked-label="{_e(group["label"])}" aria-pressed="false">'
                         f'<span class="linked-level">一级内容公式</span><strong>{_e(group["label"])}</strong></button>')
            parts.append('<div class="linked-secondary-list">')
            for child_index, child in enumerate(group["children"]):
                parts.append(f'<button type="button" class="linked-formula-node linked-secondary" data-linked-node="c{index}-{child_index}" data-linked-label="{_e(child["label"])}" aria-pressed="false">'
                             f'<span class="linked-level">二级</span><strong>{_e(child["label"])}</strong></button>')
            if not group["children"]:
                parts.append('<span class="muted">暂无二级内容公式</span>')
            parts.append('</div></div>')
        parts.append('</div><pre data-linked-copy-value="formula" hidden>' + _e(copy_text) + '</pre>')
    else:
        parts.append('<p class="muted">未提供可读的内容公式标签。</p>')
    parts.append('</section><section class="single-block"><div class="linked-heading"><h3>本视频脚本文案</h3>')
    if text is not None:
        parts.append('<button type="button" class="linked-copy" data-linked-copy="script" aria-label="复制本视频完整脚本文案">复制文案</button>')
    parts.append('</div>')
    if text is not None:
        if groups:
            parts.append('<p class="linked-hint">彩色片段对应已解析的内容公式</p>')
        parts.append('<div class="script-text">' + _linked_text(text, groups) + '</div>')
    else:
        parts.append('<p class="missing-script">可信脚本正文：未提供。' + _e(script.get('statusLabel') or '暂无已核验的正文') + '。</p>')
    parts.append('</section></div>')
    return ''.join(parts)


CSS = """
.linked-script-workspace{min-width:0}.linked-analysis-title{border-left:4px solid #2563eb;padding-left:11px;margin:24px 0 0;font-size:18px;line-height:1.4}.linked-formula-legend{display:flex;gap:10px 16px;flex-wrap:wrap;margin:10px 0 14px}.linked-legend-item{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted,#63708a)}.linked-legend-dot{width:8px;height:8px;border-radius:2px;flex:none}.linked-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.linked-heading h3{margin:0}.linked-copy{font-size:12px;white-space:nowrap}.linked-status,.linked-hint{font-size:12px;color:var(--muted,#63708a);line-height:1.65}.linked-formula-flow{display:flex;align-items:stretch;gap:9px;overflow-x:auto;padding:4px 2px 14px;scrollbar-width:thin}.linked-formula-group{flex:0 0 168px;min-width:0;padding:10px;border:1px solid #dce5f0;border-radius:12px;background:#fff}.linked-formula-node{display:flex;flex-direction:column;align-items:flex-start;width:100%;text-align:left;padding:12px;border:1px solid var(--linked-color)!important;border-radius:10px;background:color-mix(in srgb,var(--linked-color) 7%,white)!important;color:var(--text,#172033);line-height:1.5;overflow-wrap:anywhere}.linked-formula-node strong{font-size:14px}.linked-level{font-size:10px;letter-spacing:.035em;color:var(--muted,#63708a);margin-bottom:4px}.linked-primary{border-top-width:3px!important;align-items:center;text-align:center}.linked-secondary-list{display:grid;gap:8px;padding-top:9px}.linked-secondary{border-style:dashed!important}.linked-flow-arrow{display:flex;align-items:center;flex:none;color:#94a3b8;font-size:22px}.linked-formula-node.linked-active{background:color-mix(in srgb,var(--linked-color) 18%,white)!important;box-shadow:0 0 0 2px var(--linked-color);border-style:solid!important}.linked-quote{padding:2px 0;background:color-mix(in srgb,var(--linked-color) 14%,transparent);border-bottom:2px solid var(--linked-color);border-radius:2px;cursor:pointer;color:inherit;scroll-margin:100px}.linked-script-workspace.has-linked-selection .linked-quote:not(.linked-active){background:transparent;border-bottom-color:transparent}.linked-quote.linked-active{background:color-mix(in srgb,var(--linked-color) 28%,transparent);box-shadow:0 1px 0 var(--linked-color)}.linked-quote:focus-visible,.linked-formula-node:focus-visible{outline:3px solid #2563eb;outline-offset:3px}.linked-formula-node{scroll-margin:60px}.linked-script-workspace [hidden]{display:none!important}@media(max-width:700px){.linked-formula-group{flex-basis:158px}.linked-heading{align-items:flex-start}.linked-heading h3{font-size:16px}}
"""


SCRIPT = r"""
(() => {
  document.querySelectorAll('[data-linked-script]').forEach(root => {
    const nodes = Array.from(root.querySelectorAll('[data-linked-node]'));
    const marks = Array.from(root.querySelectorAll('[data-linked-keys]'));
    const status = root.querySelector('[data-linked-status]');
    let selected = [];
    const keysOf = mark => mark.dataset.linkedKeys.split(' ');
    function activate(keys, fromText) {
      if (keys.join(' ') === selected.join(' ')) keys = [];
      selected = keys;
      const activeNodes = nodes.filter(node => keys.includes(node.dataset.linkedNode));
      // Text spans carry their primary for formula context, but text selection
      // must stay on the exact child memberships rather than sibling quotes.
      const quoteKeys = fromText ? keys.filter(key => key.startsWith('c')) : keys;
      const activeMarks = marks.filter(mark => keysOf(mark).some(key => quoteKeys.includes(key)));
      nodes.forEach(node => {
        const active = activeNodes.includes(node);
        node.classList.toggle('linked-active', active);
        node.setAttribute('aria-pressed', String(active));
      });
      marks.forEach(mark => {
        const active = activeMarks.includes(mark);
        mark.classList.toggle('linked-active', active);
        mark.setAttribute('aria-pressed', String(active));
      });
      root.classList.toggle('has-linked-selection', keys.length > 0);
      const labels = [...new Set(activeNodes.map(node => node.dataset.linkedLabel))].join('、');
      status.textContent = !keys.length ? '点击内容公式或下方脚本文案，可双向定位。' :
        activeMarks.length ? `已联动：${labels} · ${activeMarks.length} 处原文片段` : `已选择：${labels}；正文中没有精确匹配的引用。`;
      const target = fromText ? activeNodes[0] : activeMarks[0];
      if (target) {
        target.scrollIntoView({behavior:'smooth', block:'nearest', inline:'nearest'});
        target.focus({preventScroll:true});
      }
    }
    nodes.forEach(node => node.addEventListener('click', () => activate([node.dataset.linkedNode], false)));
    marks.forEach(mark => {
      mark.addEventListener('click', () => activate(keysOf(mark), true));
      mark.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {event.preventDefault();activate(keysOf(mark), true);}
      });
    });
    root.querySelectorAll('[data-linked-copy]').forEach(button => button.addEventListener('click', async () => {
      const content = root.querySelector(button.dataset.linkedCopy === 'formula' ? '[data-linked-copy-value="formula"]' : '.script-text');
      if (!content) return;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(content.textContent);
        else {
          const previous = document.activeElement;
          const input = document.createElement('textarea');
          input.value = content.textContent;
          input.style.position = 'fixed'; input.style.opacity = '0';
          document.body.appendChild(input);
          let success = false;
          try {input.select(); success = document.execCommand('copy');}
          finally {input.remove();if (previous) previous.focus({preventScroll:true});}
          if (!success) throw new Error('copy unavailable');
        }
        button.textContent = '已复制';
        status.textContent = button.dataset.linkedCopy === 'formula' ? '已复制完整内容公式。' : '已复制完整脚本文案。';
      } catch (error) {
        button.textContent = button.dataset.linkedCopy === 'formula' ? '复制公式' : '复制文案';
        status.textContent = '复制未成功，请手动选择需要的内容复制。';
      }
    }));
  });
})();
"""
