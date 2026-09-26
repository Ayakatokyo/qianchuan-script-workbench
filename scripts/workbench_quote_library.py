"""Browse exact, source-bound quotations from verified platform script details."""
from __future__ import annotations

from html import escape
from typing import Any, Callable, Iterable, Mapping


_COLORS = {'商品卖点': '#db5e65', '价格优惠': '#8053ce', '行动号召': '#536d91',
           '商品信息': '#2563c5', '用户痛点': '#bf791c', '品牌信息': '#168465', '服务卖点': '#00858b'}


def _e(value: Any) -> str:
    return escape(str(value), quote=True).replace('\r', '&#13;')


def _label(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _collect(materials: Iterable[Mapping[str, Any]], groups_for_script: Callable) -> list[dict]:
    entries: dict[tuple[str, str], dict] = {}
    for index, material in enumerate(materials):
        script = material.get('script') or {}
        text = script.get('text')
        if script.get('deliveryStatus') != 'available' or not script.get('textAvailable') or not isinstance(text, str) or not text.strip():
            continue
        if not (script.get('fieldAvailability') or {}).get('detail'):
            continue
        detail = script.get('detail')
        material_id = material.get('materialId')
        if not isinstance(detail, Mapping) or material_id is None or not str(material_id).strip():
            continue
        material_id = str(material_id).strip()
        labels_by_id: dict[str, list[tuple[str | None, str | None]]] = {}
        for group in groups_for_script(script):
            primary = _label(group.get('label'))
            if primary is None:
                continue
            for child in group.get('children') or []:
                secondary = _label(child.get('label'))
                if child.get('id') is not None and secondary is not None:
                    pair = (primary, secondary)
                    values = labels_by_id.setdefault(str(child['id']), [])
                    if pair not in values:
                        values.append(pair)
        for detail_id, value in detail.items():
            if not isinstance(value, Mapping) or not isinstance(value.get('list'), list):
                continue
            tags = labels_by_id.get(str(detail_id)) or [(None, _label(value.get('label')))]
            for quote in value['list']:
                if not isinstance(quote, str) or not quote.strip() or quote not in text:
                    continue
                key = (material_id, quote)
                entry = entries.setdefault(key, {'index': index, 'materialId': material_id,
                    'name': material.get('materialName') or '素材名称未提供', 'rank': material.get('rank'),
                    'quote': quote, 'tags': []})
                for tag in tags:
                    if tag not in entry['tags']:
                        entry['tags'].append(tag)
    return list(entries.values())



def _chip(level: str, key: str, label: str, count: int, color: str) -> str:
    return (f'<button type="button" class="quote-library-chip" data-library-{level}-filter="{key}" '
            f'data-library-chip-label="{_e(label)}" data-library-chip-color="{color}" '
            f'style="--chip-color:{color}" aria-pressed="{"true" if not key else "false"}" aria-label="{_e(label)}，{count} 条片段">'
            f'<i class="quote-library-chip-dot" aria-hidden="true"></i><span>{_e(label)}</span>'
            f'<span class="quote-library-chip-count" data-library-chip-count>{count}</span></button>')


def render_quote_library(materials: Iterable[Mapping[str, Any]], groups_for_script: Callable) -> str:
    """Render a static library; SCRIPT adds filters, paging, and clipboard support.

    The host handles links with data-library-open; their href remains a working
    material anchor when JavaScript is disabled. Nothing is read from disk.
    """
    entries = _collect(materials, groups_for_script)
    primary_keys: dict[str | None, str] = {}
    secondary_keys: dict[str, str] = {}
    secondary_colors: dict[str, str] = {}
    for entry in entries:
        for primary, secondary in entry['tags']:
            primary_keys.setdefault(primary, f'p{len(primary_keys)}')
            if secondary is not None:
                secondary_keys.setdefault(secondary, f's{len(secondary_keys)}')
                secondary_colors.setdefault(secondary, _COLORS.get(primary, '#64748b'))
    parts = ['<div class="workbench-quote-library" data-quote-library>',
             '<div class="quote-library-heading"><div><p class="quote-library-eyebrow">从内容公式找到原句</p><h2>脚本片段库</h2><p class="quote-library-description">按标签浏览脚本摘录，找到原句后可复制，或回到素材查看完整上下文。</p></div>',
             f'<span class="quote-library-total">{len(entries)} <small>条片段</small></span></div>',
             '<div class="quote-library-controls" data-library-controls>',
             '<label class="quote-library-search-label">搜索原句或素材名称<input type="search" data-library-search placeholder="例如：开场、福利或素材名称"></label>',
             '<div class="quote-library-filter-group" role="group" aria-label="一级内容公式"><span class="quote-library-filter-title">一级内容公式</span><div class="quote-library-chips">',
             _chip('primary', '', '全部', len(entries), '#2563eb')]
    for label, key in primary_keys.items():
        count = sum(any(primary == label for primary, _ in entry['tags']) for entry in entries)
        parts.append(_chip('primary', key, label if label is not None else '未分类', count, _COLORS.get(label, '#64748b')))
    parts.append('</div></div><div class="quote-library-filter-group" role="group" aria-label="二级内容公式"><span class="quote-library-filter-title">二级内容公式</span><div class="quote-library-chips">')
    parts.append(_chip('secondary', '', '全部', len(entries), '#2563eb'))
    for label, key in secondary_keys.items():
        count = sum(any(secondary == label for _, secondary in entry['tags']) for entry in entries)
        parts.append(_chip('secondary', key, label, count, secondary_colors[label]))
    parts.append('</div></div><p class="quote-library-count-note">标签数字为片段数，不随搜索改变。</p></div><p class="quote-library-result" data-library-result aria-live="polite">全部片段</p><div class="quote-library-grid">')
    for entry in entries:
        color = _COLORS.get(entry['tags'][0][0], '#64748b')
        parts.append(f'<div class="quote-library-card" style="--quote-accent:{color}" data-library-card><div class="quote-library-tags">')
        for primary, secondary in entry['tags']:
            color = _COLORS.get(primary, '#64748b')
            primary_key = primary_keys[primary]
            secondary_key = secondary_keys.get(secondary, '')
            parts.append(f'<span class="quote-library-tag" style="--quote-accent:{color}" data-library-primary="{primary_key}" data-library-secondary="{secondary_key}"><span>{_e(primary if primary is not None else "未分类")}</span>')
            if secondary is not None:
                parts.append(f'<span class="quote-library-tag-separator" aria-hidden="true">/</span><strong>{_e(secondary)}</strong>')
            parts.append('</span>')
        parts.append('</div><blockquote data-library-quote>' + _e(entry['quote']) + '</blockquote>')
        parts.append('<div class="quote-library-card-footer"><div class="quote-library-source">')
        parts.append(f'<span class="quote-library-rank">素材排名 {_e(entry["rank"] if entry["rank"] is not None else "未提供")}</span><a class="quote-library-name" data-library-name data-library-open="{entry["index"]}" href="#material-{entry["index"]}" title="{_e(entry["name"])}">{_e(entry["name"])}</a>')
        parts.append('</div><button type="button" class="quote-library-copy" data-library-copy hidden>复制原句</button></div><p class="quote-library-copy-status" data-library-copy-status aria-live="polite"></p></div>')
    parts.append('</div>')
    if not entries:
        parts.append('<div class="quote-library-empty">暂无可展示的脚本片段。</div>')
    parts.append('<div class="quote-library-empty" data-library-empty hidden>没有匹配的片段，请调整标签或搜索词。</div><div class="quote-library-pager" data-library-pager hidden><span>每页 12 条片段</span><div><button type="button" data-library-page="previous">上一页</button><span data-library-page-label></span><button type="button" data-library-page="next">下一页</button></div></div></div>')
    return ''.join(parts)


CSS = """
.workbench-quote-library{min-width:0}.quote-library-heading{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:23px 26px;margin-bottom:18px;border:1px solid #dce6f5;border-radius:16px;background:linear-gradient(115deg,#eef5ff 0%,#fff 76%)}.quote-library-eyebrow{font-size:11px;color:#4878b7;margin:0 0 9px;letter-spacing:.08em}.quote-library-heading h2{font-size:24px;margin:0 0 8px;color:#172b4b}.quote-library-description{font-size:13px;line-height:1.75;color:#63708a;margin:0;max-width:650px}.quote-library-total{flex:none;color:#2563eb;font-size:34px;font-variant-numeric:tabular-nums;font-weight:650;text-align:center}.quote-library-total small{display:block;font-size:11px;color:#7185a1;font-weight:400;margin-top:3px}.quote-library-controls{display:grid;grid-template-columns:1fr;gap:17px;padding:16px 18px;border:1px solid #dfe6f0;border-radius:14px;background:#fff}.quote-library-controls label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:#63708a}.quote-library-controls input{width:100%;min-width:0;height:43px;padding:9px 12px;border:1px solid #c9d5e5;border-radius:8px;background:#fff;color:#172033;font-size:13px}.quote-library-filter-group{display:grid;grid-template-columns:84px minmax(0,1fr);gap:12px;align-items:start}.quote-library-filter-title{font-size:12px;color:#63708a;padding-top:9px;line-height:1.6}.quote-library-chips{display:flex;flex-wrap:wrap;gap:8px}.quote-library-chip{display:inline-flex;align-items:center;gap:7px;min-height:36px;padding:7px 10px;border:1px solid #dce5f0;border-radius:8px;background:#fff;color:#46566d;font-size:12px;line-height:1.5;cursor:pointer}.quote-library-chip:hover{border-color:var(--chip-color);background:color-mix(in srgb,var(--chip-color) 5%,white)}.quote-library-chip[aria-pressed="true"]{border-color:var(--chip-color);background:color-mix(in srgb,var(--chip-color) 10%,white);color:var(--chip-color);box-shadow:inset 0 0 0 1px var(--chip-color);font-weight:600}.quote-library-chip-dot{width:7px;height:7px;flex:none;border-radius:50%;background:var(--chip-color)}.quote-library-chip-count{min-width:19px;text-align:center;padding:0 5px;border-radius:5px;background:#f0f4f9;color:#6a7a92;font-size:11px;font-variant-numeric:tabular-nums}.quote-library-chip[aria-pressed="true"] .quote-library-chip-count{background:color-mix(in srgb,var(--chip-color) 14%,white);color:var(--chip-color)}.quote-library-count-note{font-size:11px;color:#8290a5;margin:0;text-align:right}.quote-library-result{font-size:12px;color:#63708a;margin:16px 3px}.quote-library-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:stretch}.quote-library-card{min-width:0;display:flex;flex-direction:column;border:1px solid #dce5f0;border-top:3px solid var(--quote-accent);border-radius:13px;background:#fff;box-shadow:0 7px 20px rgba(34,64,112,.04);padding:20px 20px 15px}.quote-library-tags{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:16px}.quote-library-tag{display:inline-flex;align-items:center;flex-wrap:wrap;gap:5px;font-size:11px;line-height:1.6;padding:4px 8px;border-radius:6px;color:var(--quote-accent);background:color-mix(in srgb,var(--quote-accent) 8%,white);border:1px solid color-mix(in srgb,var(--quote-accent) 17%,white);overflow-wrap:anywhere}.quote-library-tag strong{font-weight:600}.quote-library-tag-separator{opacity:.45}.quote-library-card blockquote{flex:1;margin:0 0 20px;padding:0;border:0;color:#273a52;font-size:14px;line-height:1.95;white-space:pre-wrap;overflow-wrap:anywhere}.quote-library-card-footer{display:flex;align-items:center;justify-content:space-between;gap:14px;border-top:1px solid #edf1f7;padding-top:13px}.quote-library-source{min-width:0}.quote-library-rank{display:block;color:#8290a5;font-size:10px;letter-spacing:.035em;margin-bottom:5px}.quote-library-name{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:12px;line-height:1.65;color:#356194;text-decoration:none}.quote-library-name:hover{text-decoration:underline}.quote-library-copy{white-space:nowrap;flex:none;min-height:34px!important;padding:7px 10px!important;border:1px solid #d0def0!important;border-radius:7px!important;background:#f5f9ff!important;color:#37669e!important;font-size:11px!important}.quote-library-copy:hover{background:#eaf2ff!important}.quote-library-copy-status{margin:7px 0 0;color:#63708a;font-size:11px;line-height:1.5;min-height:0}.quote-library-copy-status:empty{display:none}.quote-library-pager{display:flex;justify-content:space-between;align-items:center;gap:16px;color:#63708a;font-size:12px;margin:20px 0}.quote-library-pager>div{display:flex;align-items:center;gap:12px}.quote-library-pager button{border:1px solid #c9d5e5;border-radius:8px;background:white;color:#172033;padding:8px 13px;min-height:36px;font-size:12px;cursor:pointer}.quote-library-pager button:disabled{opacity:.4;cursor:default}.quote-library-empty{padding:44px 20px;border:1px dashed #d4deed;border-radius:14px;background:#fafcff;text-align:center;color:#63708a;font-size:14px}.workbench-quote-library input:focus-visible,.workbench-quote-library button:focus-visible,.workbench-quote-library a:focus-visible{outline:3px solid #93b4ef;outline-offset:2px}.workbench-quote-library [hidden]{display:none!important}@media(max-width:760px){.quote-library-heading{padding:20px;align-items:flex-start;gap:14px}.quote-library-heading h2{font-size:21px}.quote-library-total{font-size:27px}.quote-library-filter-group{grid-template-columns:1fr;gap:7px}.quote-library-filter-title{padding-top:0}.quote-library-count-note{text-align:left}.quote-library-grid{grid-template-columns:1fr}.quote-library-card{padding:18px 17px 13px}}@media(max-width:430px){.quote-library-controls{grid-template-columns:1fr}.quote-library-heading{padding:17px}.quote-library-description{font-size:12px}.quote-library-pager{align-items:flex-start}}
"""


SCRIPT = """
(() => {
  document.querySelectorAll("[data-quote-library]").forEach(root => {
    const query = selector => root.querySelector(selector);
    const cards = Array.from(root.querySelectorAll("[data-library-card]"));
    const primaryButtons = Array.from(root.querySelectorAll("[data-library-primary-filter]"));
    const secondaryButtons = Array.from(root.querySelectorAll("[data-library-secondary-filter]"));
    const search = query("[data-library-search]");
    const normalize = value => String(value || "").normalize("NFKC").toLocaleLowerCase().trim();
    const entries = cards.map(card => ({card,
      search: normalize(card.querySelector("[data-library-quote]").textContent + " " + card.querySelector("[data-library-name]").textContent),
      tags: Array.from(card.querySelectorAll("[data-library-primary]")).map(tag => ({primary:tag.dataset.libraryPrimary, secondary:tag.dataset.librarySecondary}))
    }));
    const pageSize = 12;
    let page = 1, selectedPrimary = "", selectedSecondary = "";
    function updateChips() {
      primaryButtons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.libraryPrimaryFilter === selectedPrimary)));
      const primaryColor = primaryButtons.find(button => button.dataset.libraryPrimaryFilter === selectedPrimary)?.dataset.libraryChipColor;
      secondaryButtons.forEach(button => {
        const key = button.dataset.librarySecondaryFilter;
        const count = entries.filter(entry => entry.tags.some(tag => (!selectedPrimary || tag.primary === selectedPrimary) && (!key || tag.secondary === key))).length;
        button.hidden = Boolean(key) && count === 0;
        button.disabled = button.hidden;
        button.querySelector("[data-library-chip-count]").textContent = String(count);
        button.setAttribute("aria-pressed", String(key === selectedSecondary));
        button.setAttribute("aria-label", `${button.dataset.libraryChipLabel}，${count} 条片段`);
        button.style.setProperty("--chip-color", selectedPrimary ? primaryColor : button.dataset.libraryChipColor);
      });
    }
    function update() {
      const term = normalize(search.value);
      const matching = entries.filter(entry => (!term || entry.search.includes(term)) && entry.tags.some(tag => (!selectedPrimary || tag.primary === selectedPrimary) && (!selectedSecondary || tag.secondary === selectedSecondary)));
      const pageCount = Math.max(1, Math.ceil(matching.length / pageSize));
      page = Math.max(1, Math.min(page, pageCount));
      cards.forEach(card => {card.hidden = true;});
      matching.slice((page - 1) * pageSize, page * pageSize).forEach(entry => {entry.card.hidden = false;});
      query("[data-library-result]").textContent = `共 ${matching.length} 条片段 · 当前显示 ${matching.length ? (page - 1) * pageSize + 1 : 0}–${Math.min(page * pageSize, matching.length)} 条`;
      query("[data-library-page-label]").textContent = `${page} / ${pageCount}`;
      query('[data-library-page="previous"]').disabled = page <= 1;
      query('[data-library-page="next"]').disabled = page >= pageCount;
      query("[data-library-empty]").hidden = matching.length > 0 || cards.length === 0;
    }
    primaryButtons.forEach(button => button.addEventListener("click", () => {
      selectedPrimary = button.dataset.libraryPrimaryFilter;
      selectedSecondary = "";
      page = 1; updateChips(); update();
    }));
    secondaryButtons.forEach(button => button.addEventListener("click", () => {
      if (button.disabled) return;
      selectedSecondary = button.dataset.librarySecondaryFilter;
      page = 1; updateChips(); update();
    }));
    search.addEventListener("input", () => {page = 1; update();});
    query('[data-library-page="previous"]').addEventListener("click", () => {page -= 1; update();});
    query('[data-library-page="next"]').addEventListener("click", () => {page += 1; update();});
    cards.forEach(card => {
      const button = card.querySelector("[data-library-copy]");
      const status = card.querySelector("[data-library-copy-status]");
      button.hidden = false;
      button.addEventListener("click", async () => {
        const text = card.querySelector("[data-library-quote]").textContent;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text);
          else {
            const previous = document.activeElement;
            const input = document.createElement("textarea");
            input.value = text; input.style.position = "fixed"; input.style.opacity = "0";
            document.body.appendChild(input);
            let copied = false;
            try {input.select(); copied = document.execCommand("copy");}
            finally {input.remove(); if (previous) previous.focus({preventScroll:true});}
            if (!copied) throw new Error("copy unavailable");
          }
          button.textContent = "已复制";
          status.textContent = "已复制原句。";
        } catch (error) {
          button.textContent = "复制原句";
          status.textContent = "复制未成功，请手动选择原句复制。";
        }
      });
    });
    query("[data-library-controls]").hidden = false;
    query("[data-library-pager]").hidden = false;
    updateChips();
    update();
  });
})();
"""
