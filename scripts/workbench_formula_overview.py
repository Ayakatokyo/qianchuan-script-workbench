"""Offline two-level formula charts for the verified script workbench.

The caller supplies its label projection. This module owns only presentation and
unique-material counts; it neither reads run files nor changes acquisition facts.
"""
from __future__ import annotations

from html import escape
import math
from typing import Any, Callable, Iterable, Mapping


_COLORS = ('#2563eb', '#60a5fa', '#14b8a6', '#f59e0b', '#ef6a6a', '#8b5cf6', '#64748b', '#22c55e')


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _label(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _percentage(count: int, total: int) -> str:
    return f'{100 * count / total:.2f}'.rstrip('0').rstrip('.') + '%' if total else '0%'


def _point(radius: float, angle: float) -> str:
    return f'{116 + radius * math.cos(angle):.4f} {130 + radius * math.sin(angle):.4f}'


def _ring_path(start: float, end: float) -> str:
    outer_start, inner_start = _point(96, start), _point(58, start)
    if end - start >= math.tau - 0.000001:
        outer_mid, inner_mid = _point(96, start + math.pi), _point(58, start + math.pi)
        return f'M {outer_start} A 96 96 0 1 1 {outer_mid} A 96 96 0 1 1 {outer_start} L {inner_start} A 58 58 0 1 0 {inner_mid} A 58 58 0 1 0 {inner_start} Z'
    large = int(end - start > math.pi)
    return f'M {outer_start} A 96 96 0 {large} 1 {_point(96, end)} L {_point(58, end)} A 58 58 0 {large} 0 {inner_start} Z'


def render_formula_overview(
    materials: Iterable[Mapping[str, Any]],
    groups_for_script: Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]],
) -> str:
    """Render all statistics statically; SCRIPT enhances them with drill-down.

    Accepted group shape: {label, children: [{label, ...}], ...}. Only available
    or missing-body scripts contribute. Counts deduplicate material IDs per label.
    """
    labeled: set[str] = set()
    primary: dict[str, set[str]] = {}
    secondary: dict[str, dict[str, set[str]]] = {}
    for material in materials:
        material_id = material.get('materialId')
        if material_id is None or not str(material_id).strip():
            continue
        material_id = str(material_id).strip()
        script = material.get('script') or {}
        if script.get('deliveryStatus') not in {'available', 'missing'}:
            continue
        for group in groups_for_script(script):
            label = _label(group.get('label'))
            if label is None:
                continue
            primary.setdefault(label, set()).add(material_id)
            labeled.add(material_id)
            children = secondary.setdefault(label, {})
            for child in group.get('children') or []:
                child_label = _label(child.get('label'))
                if child_label is not None:
                    children.setdefault(child_label, set()).add(material_id)
    buckets = sorted(primary.items(), key=lambda item: (-len(item[1]), item[0]))
    denominator = len(labeled)
    parts = ['<div class="workbench-formula-overview" data-workbench-formula>',
             f'<p class="formula-coverage-note">{denominator} 个素材的内容公式 · 按素材计数</p>',
             '<section class="script-formula-card"><div class="script-card-header"><h3>一级内容公式</h3>',
             '<span class="script-card-hint">点击一级内容公式柱状图可以显示二级内容公式分布</span></div>']
    if not buckets:
        parts.append('<div class="formula-empty">暂无可展示的内容公式标签。原始结构保留在单素材脚本中。</div></section></div>')
        return ''.join(parts)
    width, height, left, bottom = max(560, min(760, len(buckets) * 170)), 290, 42, 72
    plot_height = height - bottom - 20
    max_count = max(len(ids) for _, ids in buckets)
    band = (width - left - 18) / len(buckets)
    parts.append(f'<div class="script-formula-chart"><svg class="script-formula-svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="group" aria-label="一级内容公式柱状图"><line class="formula-chart-axis" x1="{left}" y1="{height-bottom}" x2="{width-12}" y2="{height-bottom}"></line>')
    for index, (label, ids) in enumerate(buckets):
        count = len(ids)
        bar_height = count / max_count * plot_height
        bar_width = band * .52
        x = left + index * band + (band - bar_width) / 2
        y = height - bottom - bar_height
        center = x + bar_width / 2
        name = label if len(label) <= 8 else label[:8] + '…'
        accessible = f'{label}，覆盖 {count} 个素材，占有公式素材 {_percentage(count, denominator)}'
        parts.append(f'<rect class="script-formula-bar" data-formula-primary="{index}" data-formula-count="{count}" data-formula-total="{denominator}" x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="5" tabindex="0" role="button" aria-pressed="false" aria-label="{_e(accessible)}"><title>{_e(accessible)}</title></rect>')
        parts.append(f'<text class="formula-chart-value" x="{center:.2f}" y="{max(14, y-6):.2f}" text-anchor="middle">{count}</text><text class="formula-chart-label" x="{center:.2f}" y="{height-42}" text-anchor="middle"><title>{_e(label)}</title>{_e(name)}</text>')
    parts.append('</svg></div></section>')
    for primary_index, (label, ids) in enumerate(buckets):
        total = len(ids)
        children = sorted(secondary[label].items(), key=lambda item: (-len(item[1]), item[0]))
        parts.append(f'<section class="script-formula-card" data-formula-secondary="{primary_index}"><div class="script-card-header"><h3>{_e(label)} · 二级内容公式分布</h3><button type="button" data-formula-close="{primary_index}" hidden>收起二级内容公式</button></div>')
        if not children:
            parts.append('<div class="formula-empty">暂无该一级内容公式的二级公式数据。</div></section>')
            continue
        occurrence_total = sum(len(child_ids) for _, child_ids in children)
        parts.append(f'<div class="script-formula-donut"><div class="script-formula-ring"><svg viewBox="0 0 232 270" role="group" aria-label="{_e(label)}二级内容公式环形图">')
        cursor = -math.pi / 2
        for index, (child, child_ids) in enumerate(children):
            count = len(child_ids)
            size = count / occurrence_total * math.tau
            end = cursor + size
            angle = (cursor + end) / 2
            description = f'{child}，覆盖 {count} 个素材，占当前一级覆盖素材 {_percentage(count, total)}'
            parts.append(f'<path class="script-formula-segment" data-formula-secondary-index="{index}" data-formula-angle-size="{size:.8f}" data-formula-shift-x="{8*math.cos(angle):.4f}" data-formula-shift-y="{8*math.sin(angle):.4f}" d="{_ring_path(cursor, end)}" fill="{_COLORS[index % len(_COLORS)]}" role="button" tabindex="0" aria-pressed="false" aria-label="{_e(description)}"><title>{_e(description)}</title></path>')
            cursor = end
        parts.append(f'<text class="formula-donut-center-label" x="116" y="124" text-anchor="middle">当前一级覆盖素材数</text><text class="formula-donut-center-value" x="116" y="150" text-anchor="middle">{total}</text></svg></div><div class="script-formula-legend" aria-label="二级内容公式图例">')
        for index, (child, child_ids) in enumerate(children):
            count = len(child_ids)
            description = f'{child}，覆盖 {count} 个素材，占当前一级覆盖素材 {_percentage(count, total)}'
            parts.append(f'<button type="button" class="formula-legend-item" data-formula-secondary-index="{index}" aria-pressed="false" aria-label="{_e(description)}"><span class="formula-legend-swatch" style="background:{_COLORS[index % len(_COLORS)]}"></span><span>{_e(child)}<span class="formula-legend-detail">{count} 个素材 · {_percentage(count, total)}</span></span></button>')
        parts.append(f'</div></div><p class="formula-coverage-note">覆盖比例以当前一级的 {total} 个素材为分母；同一素材可包含多个二级标签。环图面积按二级标签出现数之和（{occurrence_total}）归一，不代表互斥素材占比。</p></section>')
    parts.append('</div>')
    return ''.join(parts)


CSS = """
.workbench-formula-overview{display:grid;gap:16px}.workbench-formula-overview .formula-coverage-note{font-size:12px;line-height:1.65;color:var(--muted,#63708a);margin:0}.workbench-formula-overview .script-formula-card{min-width:0;background:#fff;border:1px solid var(--line,#dfe6f0);border-radius:14px;padding:20px;box-shadow:0 8px 24px rgba(34,64,112,.05)}.workbench-formula-overview .script-card-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.workbench-formula-overview .script-card-header h3{margin:0;font-size:17px}.workbench-formula-overview .script-card-hint{color:var(--muted,#63708a);font-size:12px}.workbench-formula-overview .script-card-header button{min-height:34px;padding:6px 10px;font-size:12px;border:1px solid #c9d5e5;border-radius:8px;background:#fff;color:#172033;cursor:pointer}.workbench-formula-overview .script-formula-chart{overflow-x:auto}.workbench-formula-overview .script-formula-svg{display:block;max-width:100%;height:auto;min-height:230px;margin:0 auto}.workbench-formula-overview .formula-chart-axis{stroke:#c9d5e5;stroke-width:1}.workbench-formula-overview .formula-chart-value{fill:#334155;font-size:12px}.workbench-formula-overview .formula-chart-label{fill:#63708a;font-size:12px}.workbench-formula-overview .script-formula-bar{fill:#5b8def;cursor:pointer}.workbench-formula-overview .script-formula-bar:hover,.workbench-formula-overview .script-formula-bar:focus,.workbench-formula-overview .script-formula-bar.active{fill:#2563eb;outline:none}.workbench-formula-overview .script-formula-bar:focus-visible{stroke:#172033;stroke-width:2}.workbench-formula-overview .script-formula-donut{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,1fr);align-items:center;gap:14px}.workbench-formula-overview .script-formula-ring svg{display:block;width:232px;height:270px;max-width:100%;margin:0 auto}.workbench-formula-overview .script-formula-segment{stroke:#fff;stroke-width:2;cursor:pointer;transform-box:view-box;transform-origin:116px 130px;transition:transform .24s cubic-bezier(.22,.61,.36,1),filter .24s ease,stroke-width .24s ease}.workbench-formula-overview .script-formula-segment.active{filter:brightness(.9);stroke-width:3}.workbench-formula-overview .script-formula-segment:focus-visible{outline:none;stroke:#172033;stroke-width:3}.workbench-formula-overview .formula-donut-center-label{fill:#63708a;font-size:11px;pointer-events:none}.workbench-formula-overview .formula-donut-center-value{fill:#172033;font-size:24px;font-weight:650;pointer-events:none}.workbench-formula-overview .script-formula-legend{display:grid;gap:4px;align-content:center}.workbench-formula-overview .formula-legend-item{display:flex;align-items:flex-start;gap:10px;text-align:left;padding:4px 10px;min-height:48px;border:1px solid transparent;border-radius:9px;background:transparent;color:#172033;font-size:14px;cursor:pointer;line-height:1.45}.workbench-formula-overview .formula-legend-item:hover,.workbench-formula-overview .formula-legend-item.active{border-color:#bfdbfe;background:#eff6ff}.workbench-formula-overview .formula-legend-item:focus-visible,.workbench-formula-overview [data-formula-close]:focus-visible{outline:3px solid #93b4ef;outline-offset:2px}.workbench-formula-overview .formula-legend-swatch{width:12px;height:12px;flex:0 0 12px;border-radius:3px;margin-top:4px}.workbench-formula-overview .formula-legend-detail{display:block;color:#63708a;font-size:12px;margin-top:2px}.workbench-formula-overview .formula-empty{padding:40px 16px;text-align:center;color:#63708a;font-size:14px}.workbench-formula-overview [hidden]{display:none!important}
@media(max-width:700px){.workbench-formula-overview .script-card-header{align-items:flex-start;flex-wrap:wrap}.workbench-formula-overview .script-formula-card{padding:16px}.workbench-formula-overview .script-formula-donut{grid-template-columns:1fr}.workbench-formula-overview .script-formula-svg{min-width:520px;max-width:none;min-height:0;height:290px}}
@media(prefers-reduced-motion:reduce){.workbench-formula-overview .script-formula-segment{transition:none}}
"""


SCRIPT = """
(() => {
  document.querySelectorAll("[data-workbench-formula]").forEach(root => {
    const primaryBars = Array.from(root.querySelectorAll("[data-formula-primary]"));
    const secondaryCards = Array.from(root.querySelectorAll("[data-formula-secondary]"));
    const closers = Array.from(root.querySelectorAll("[data-formula-close]"));
    const resetSelections = [];
    function showPrimary(index) {
      resetSelections.forEach(reset => reset());
      primaryBars.forEach(bar => {
        const active = bar.dataset.formulaPrimary === index;
        bar.classList.toggle("active", active);
        bar.setAttribute("aria-pressed", String(active));
      });
      secondaryCards.forEach(card => { card.hidden = card.dataset.formulaSecondary !== index; });
    }
    function keyboardActivate(element, action) {
      element.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); action(); }
      });
    }
    primaryBars.forEach(bar => {
      const select = () => showPrimary(bar.dataset.formulaPrimary);
      bar.addEventListener("click", select);
      keyboardActivate(bar, select);
    });
    secondaryCards.forEach(card => {
      const items = Array.from(card.querySelectorAll("[data-formula-secondary-index]"));
      let selected = null;
      function highlight(index) {
        items.forEach(item => {
          const active = item.dataset.formulaSecondaryIndex === index;
          item.classList.toggle("active", active);
          item.setAttribute("aria-pressed", String(item.dataset.formulaSecondaryIndex === selected));
          if (item.classList.contains("script-formula-segment")) {
            item.style.transform = active ? `translate(${Number(item.dataset.formulaShiftX)}px, ${Number(item.dataset.formulaShiftY)}px)` : "";
          }
        });
      }
      items.forEach(item => {
        const activate = () => {
          const index = item.dataset.formulaSecondaryIndex;
          selected = selected === index ? null : index;
          highlight(selected);
        };
        item.addEventListener("click", activate);
        if (item.tagName.toLowerCase() !== "button") keyboardActivate(item, activate);
        item.addEventListener("pointerenter", () => highlight(item.dataset.formulaSecondaryIndex));
        item.addEventListener("pointerleave", () => highlight(selected));
        item.addEventListener("focus", () => highlight(item.dataset.formulaSecondaryIndex));
        item.addEventListener("blur", () => highlight(selected));
      });
      resetSelections.push(() => { selected = null; highlight(null); });
    });
    closers.forEach(button => {
      button.hidden = false;
      button.addEventListener("click", () => {
        showPrimary(null);
        const origin = primaryBars.find(bar => bar.dataset.formulaPrimary === button.dataset.formulaClose);
        if (origin) origin.focus();
      });
    });
    showPrimary(null);
  });
})();
"""
