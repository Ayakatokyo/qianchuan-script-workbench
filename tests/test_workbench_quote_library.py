"""Verified excerpt-library projection and offline interactions."""
import importlib.util
import json
import shutil
import subprocess
import unittest

from tests.test_workbench_report_html import Document


def material(material_id='m1', name='素材一', rank=1):
    return {'materialId': material_id, 'materialName': name, 'rank': rank,
            'script': {'deliveryStatus': 'available', 'textAvailable': True,
                       'fieldAvailability': {'detail': True}, 'text': '开场原句。\n折扣原句。\r\n尾句。',
                       'detail': {'21': {'label': '降价/折扣', 'list': ['折扣原句。', '折扣原句。', '不存在的原句。']},
                                  '22': {'label': '价格说明', 'list': ['折扣原句。']},
                                  '99': {'label': '特点描述', 'list': ['开场原句。']}},
                       'groups': [{'label': '价格优惠', 'children': [{'id': 21, 'label': '降价/折扣'}]},
                                  {'label': '商品卖点', 'children': [{'id': 22, 'label': '价格说明'}]}]}}


class QuoteLibraryTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_quote_library'), 'quote library module is missing')
        import workbench_quote_library
        return workbench_quote_library

    def render(self, items=None):
        return self.module().render_quote_library([material()] if items is None else items, lambda script: script.get('groups') or [])

    def test_exact_quotes_are_deduplicated_per_material_but_keep_all_tags(self):
        doc = Document(self.render())
        cards = doc.find('div', **{'class': 'quote-library-card'})
        self.assertEqual(len(cards), 2)
        first = cards[0]['text']
        self.assertIn('价格优惠', first)
        self.assertIn('商品卖点', first)
        self.assertIn('降价/折扣', first)
        self.assertIn('价格说明', first)
        self.assertNotIn('不存在的原句', self.render())
        self.assertEqual(len(doc.find('blockquote', **{'data-library-quote': None})), 2)
        self.assertFalse(doc.find('article'))

    def test_unclassified_detail_keeps_known_label_without_invented_formula(self):
        doc = Document(self.render())
        last = doc.find('div', **{'class': 'quote-library-card'})[-1]['text']
        self.assertIn('未分类', last)
        self.assertIn('特点描述', last)
        self.assertNotIn('价格优惠', last)

    def test_rejected_missing_or_disabled_detail_never_contribute_quotes(self):
        items = []
        for state in ['identityMismatch', 'identityUnverified', 'failed', 'missing']:
            item = material(state)
            item['script']['deliveryStatus'] = state
            items.append(item)
        unavailable = material('disabled')
        unavailable['script']['fieldAvailability']['detail'] = False
        items.append(unavailable)
        doc = Document(self.render(items))
        self.assertFalse(doc.find('blockquote'))
        self.assertIn('暂无可展示的脚本片段', self.render(items))

    def test_undeclared_detail_availability_is_not_trusted(self):
        for availability in ({}, {'detail': None}, {'detail': False}):
            with self.subTest(availability=availability):
                item = material()
                item['script']['fieldAvailability'] = availability
                self.assertFalse(Document(self.render([item])).find('blockquote'))

    def test_identical_quotes_on_distinct_materials_keep_separate_provenance(self):
        doc = Document(self.render([material(), material('m2', '素材二', 2)]))
        self.assertEqual(len(doc.find('div', **{'class': 'quote-library-card'})), 4)
        links = [e for e in doc.find('a') if 'data-library-open' in e['attrs']]
        self.assertEqual({(e['attrs']['href'], e['attrs']['data-library-open']) for e in links}, {('#material-0', '0'), ('#material-1', '1')})

    def test_no_javascript_keeps_every_full_quote_and_carriage_return(self):
        item = material()
        quote = '  折扣原句。\r\n尾句。'
        item['script']['text'] = '前文\n' + quote
        item['script']['detail'] = {'21': {'label': '降价/折扣', 'list': [quote]}}
        doc = Document(self.render([item]))
        self.assertEqual(doc.find('blockquote')[0]['text'], quote)
        cards = doc.find('div', **{'class': 'quote-library-card'})
        self.assertFalse(any('hidden' in card['attrs'] for card in cards))

    def test_untrusted_labels_quotes_and_names_are_escaped(self):
        item = material()
        attack = '</script><img src=x onerror="alert(1)">'
        item['materialName'] = attack
        item['script'].update(text=attack, groups=[], detail={'x': {'label': attack, 'list': [attack]}})
        doc = Document(self.render([item]))
        self.assertFalse(doc.find('img'))
        self.assertFalse(doc.find('script'))
        self.assertFalse(any(key.startswith('on') for e in doc.elements for key in e['attrs']))
        self.assertEqual(doc.find('blockquote')[0]['text'], attack)

    def test_filter_chips_are_buttons_with_deduplicated_counts(self):
        doc = Document(self.render())
        self.assertFalse(doc.find('select'))
        self.assertNotIn('hidden', doc.find('div', **{'data-library-controls': None})[0]['attrs'])
        primary = [e for e in doc.find('button') if 'data-library-primary-filter' in e['attrs']]
        secondary = [e for e in doc.find('button') if 'data-library-secondary-filter' in e['attrs']]
        self.assertEqual(len(primary), 4)
        self.assertEqual(len(secondary), 4)
        self.assertEqual([e['attrs'].get('aria-label') for e in primary],
                         ['全部，2 条片段', '价格优惠，1 条片段', '商品卖点，1 条片段', '未分类，1 条片段'])
        self.assertEqual([e['attrs'].get('aria-pressed') for e in primary], ['true', 'false', 'false', 'false'])
        self.assertTrue(all(e['attrs'].get('type') == 'button' for e in primary + secondary))

    def test_filters_search_paging_and_copy_feedback_execute_offline(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js unavailable for offline interaction execution')
        item = material(name='全角Ａ Café')
        quotes = [f'片段{index}。' for index in range(14)]
        item['script']['text'] = '\n'.join(quotes)
        item['script']['detail'] = {'21': {'label': '降价/折扣', 'list': quotes[:13]},
                                    '22': {'label': '价格说明', 'list': [quotes[0]]},
                                    '33': {'label': '价格说明', 'list': [quotes[13]]}}
        item['script']['groups'][0]['children'].append({'id': 33, 'label': '价格说明'})
        doc = Document(self.render([item]))
        index = {id(element): position for position, element in enumerate(doc.elements)}
        nodes = [{'tag': element['tag'], 'attrs': element['attrs'], 'text': element['text'],
                  'parent': index.get(id(element.get('parent')))} for element in doc.elements]
        runner = r"""
(async () => {
const source = NODES;
function matches(item, selector) {
  const matched = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
  return matched && matched[1] in item.attrs && (matched[2] === undefined || item.attrs[matched[1]] === matched[2]);
}
const nodes = source.map((entry,index) => {
  const item = {tagName:entry.tag.toUpperCase(), attrs:{...entry.attrs}, parent:entry.parent,index,hidden:"hidden" in entry.attrs,value:entry.attrs.value || "",dataset:{},style:{setProperty(key,value){this[key]=value;}},events:{},textContent:entry.text,
    setAttribute(key,value){this.attrs[key]=value;},
    addEventListener(key,fn){(this.events[key] ||= []).push(fn);},
    async emit(type){for(const fn of this.events[type] || []) await fn({preventDefault(){}});},
    querySelector(selector){return this.querySelectorAll(selector)[0];},
    querySelectorAll(selector){return nodes.filter(candidate=>{
      if(!matches(candidate,selector))return false;
      for(let p=candidate.parent;p!=null;p=nodes[p].parent)if(p===this.index)return true;
      return false;
    });}};
  for(const [key,value] of Object.entries(entry.attrs))if(key.startsWith("data-"))item.dataset[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value || "";
  return item;
});
global.document={querySelectorAll:selector=>nodes.filter(item=>matches(item,selector))};
let copied=null;
Object.defineProperty(globalThis,"navigator",{configurable:true,value:{clipboard:{writeText:async text=>{copied=text;}}}});
SCRIPT
const root=nodes.find(item=>"data-quote-library" in item.attrs);
const get=selector=>root.querySelector(selector);
const cards=root.querySelectorAll("[data-library-card]");
const visible=()=>cards.filter(card=>!card.hidden);
const check=(value,message)=>{if(!value)throw Error(message);};
check(visible().length===12,"First page has 12");
await get('[data-library-page="next"]').emit("click");
check(visible().length===2,"Second page has two");
const primaries=root.querySelectorAll("[data-library-primary-filter]"),secondaries=root.querySelectorAll("[data-library-secondary-filter]"),search=get("[data-library-search]");
const primary=key=>primaries.find(button=>button.dataset.libraryPrimaryFilter===key);
const secondary=key=>secondaries.find(button=>button.dataset.librarySecondaryFilter===key);
const chipCount=button=>Number(button.querySelector("[data-library-chip-count]").textContent);
search.value="ｃａｆé";await search.emit("input");
check(visible().length===12 && get("[data-library-page-label]").textContent==="1 / 2","Unicode search resets page");
search.value="";await search.emit("input");
await primary("p0").emit("click");
check(primary("p0").attrs["aria-pressed"]==="true" && primary("").attrs["aria-pressed"]==="false","Primary has a clear single selection");
check(chipCount(secondary("s1"))===1,"Secondary counts use primary context and unique excerpts");
await secondary("s1").emit("click");
check(visible().length===1 && visible()[0].querySelector("[data-library-quote]").textContent==="片段13。","Secondary pair does not cross-match another primary on same quote");
await primary("p1").emit("click");
check(visible().length===1 && secondary("").attrs["aria-pressed"]==="true","Primary switch resets secondary selection");
check(secondary("s0").hidden && secondary("s0").disabled,"Only available secondary labels are shown");
await secondary("s0").emit("click");
check(visible().length===1 && secondary("").attrs["aria-pressed"]==="true","Unavailable hidden button cannot activate");
await primary("").emit("click");
check(chipCount(secondary("s1"))===2 && !secondary("s0").hidden,"All primary restores secondary totals");
search.value="片段13";await search.emit("input");
check(visible().length===1 && chipCount(secondary("s1"))===2,"Search keeps counts stable and filters results");
const card=visible()[0],button=card.querySelector("[data-library-copy]"),status=card.querySelector("[data-library-copy-status]");
await button.emit("click");
check(copied==="片段13。" && status.textContent.includes("已复制"),"Copy preserves exact quote");
navigator.clipboard.writeText=async()=>{throw Error("denied");};
await button.emit("click");
check(status.textContent.includes("复制未成功") && button.textContent==="复制原句","Copy rejection is explicit");
search.value="不存在";await search.emit("input");
check(visible().length===0 && !get("[data-library-empty]").hidden,"Empty filter state");
})().catch(error=>{console.error(error);process.exit(1);});
""".replace('NODES', json.dumps(nodes, ensure_ascii=False)).replace('SCRIPT', self.module().SCRIPT)
        result = subprocess.run([node, '-e', runner], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == '__main__':
    unittest.main()
