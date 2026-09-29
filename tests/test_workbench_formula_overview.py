"""Contract tests for the offline two-level platform formula chart."""
import importlib.util
import json
import math
import shutil
import subprocess
import unittest

from tests.test_workbench_report_html import Document


def fixture():
    primary = {'label': '价格优惠', 'children': [{'label': '降价'}, {'label': '赠品'}]}
    return [
        {'materialId': 'a', 'script': {'deliveryStatus': 'available', 'groups': [primary, primary]}},
        {'materialId': 'b', 'script': {'deliveryStatus': 'missing', 'groups': [primary]}},
        {'materialId': 'c', 'script': {'deliveryStatus': 'available', 'groups': [{'label': '商品卖点', 'children': []}]}},
        {'materialId': 'a', 'script': {'deliveryStatus': 'available', 'groups': [primary]}},
        {'materialId': 'bad', 'script': {'deliveryStatus': 'identityMismatch', 'groups': [{'label': '未采信标签', 'children': [{'label': '泄漏'}]}]}},
    ]


class FormulaOverviewTests(unittest.TestCase):
    def renderer(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_formula_overview'), 'formula chart module is missing')
        import workbench_formula_overview
        return workbench_formula_overview

    def render(self, materials=None):
        return self.renderer().render_formula_overview(fixture() if materials is None else materials, lambda script: script.get('groups') or [])

    def test_primary_bars_deduplicate_verified_material_ids(self):
        doc = Document(self.render())
        bars = doc.find('rect', **{'class': 'script-formula-bar'})
        self.assertEqual(len(bars), 2)
        self.assertEqual([item['attrs']['data-formula-count'] for item in bars], ['2', '1'])
        self.assertEqual([item['attrs']['data-formula-total'] for item in bars], ['3', '3'])
        self.assertNotIn('未采信标签', self.render())
        self.assertNotIn('泄漏', self.render())

    def test_primary_percentage_excludes_verified_materials_without_labels(self):
        materials = fixture() + [{'materialId': 'no-label', 'script': {'deliveryStatus': 'available', 'groups': []}}]
        doc = Document(self.render(materials))
        bars = doc.find('rect', **{'class': 'script-formula-bar'})
        self.assertEqual(bars[0]['attrs']['data-formula-total'], '3')
        self.assertIn('66.67%', bars[0]['attrs']['aria-label'])

    def test_secondary_coverage_and_ring_area_have_distinct_denominators(self):
        doc = Document(self.render())
        cards = doc.find('section', **{'data-formula-secondary': '0'})
        self.assertEqual(len(cards), 1)
        self.assertIn('当前一级覆盖素材数', cards[0]['text'])
        legends = [e for e in doc.find('button') if 'data-formula-secondary-index' in e['attrs']]
        self.assertEqual(len(legends), 2)
        for legend in legends:
            self.assertIn('2 个素材', legend['text'])
            self.assertIn('100%', legend['text'])
        segments = doc.find('path', **{'class': 'script-formula-segment'})
        self.assertEqual(len(segments), 2)
        for segment in segments:
            self.assertAlmostEqual(float(segment['attrs']['data-formula-angle-size']), math.pi, places=5)
        self.assertNotIn('环图面积', cards[0]['text'])

    def test_no_javascript_keeps_every_secondary_statistic_readable(self):
        doc = Document(self.render())
        cards = [e for e in doc.find('section') if 'data-formula-secondary' in e['attrs']]
        self.assertEqual(len(cards), 2)
        self.assertFalse(any('hidden' in e['attrs'] for e in cards))
        self.assertIn('暂无该一级内容公式的二级公式数据', cards[1]['text'])

    def test_one_secondary_label_draws_a_complete_ring(self):
        materials = [{'materialId': 'a', 'script': {'deliveryStatus': 'available', 'groups': [{'label': '开场', 'children': [{'label': '痛点'}]}]}}]
        doc = Document(self.render(materials))
        segment = doc.find('path', **{'class': 'script-formula-segment'})[0]
        self.assertAlmostEqual(float(segment['attrs']['data-formula-angle-size']), math.tau, places=5)
        self.assertEqual(segment['attrs']['d'].count(' A '), 4)

    def test_injected_labels_never_become_executable_markup(self):
        attack = '</script><img src=x onerror=alert(1)><svg onload=alert(2)>'
        materials = [{'materialId': 'a', 'script': {'deliveryStatus': 'available', 'groups': [{'label': attack, 'children': [{'label': attack}]}]}}]
        doc = Document(self.render(materials))
        self.assertFalse(doc.find('img'))
        self.assertFalse(doc.find('script'))
        self.assertFalse(any(key.startswith('on') for e in doc.elements for key in e['attrs']))
        self.assertIn(attack, ''.join(e['text'] for e in doc.find('button')))

    def test_empty_or_untrusted_input_does_not_create_zero_value_formulas(self):
        doc = Document(self.render([]))
        self.assertFalse(doc.find('rect'))
        self.assertIn('暂无可展示的内容公式标签', ''.join(e['text'] for e in doc.find('div')))
        self.assertNotIn('nan', self.render([]).lower())

    def test_chart_drilldown_keyboard_highlight_toggle_and_collapse(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js unavailable for offline interactive behavior test')
        doc = Document(self.render())
        index = {id(element): position for position, element in enumerate(doc.elements)}
        nodes = [{'tag': element['tag'], 'attrs': element['attrs'], 'parent': index.get(id(element.get('parent')))} for element in doc.elements]
        runner = r"""
const source = NODES;
let focused = null;
const nodes = source.map((entry,index) => {
  const classes = new Set((entry.attrs.class || "").split(" "));
  const item = {tagName:entry.tag.toUpperCase(), attrs:{...entry.attrs}, parent:entry.parent,index,hidden:"hidden" in entry.attrs,dataset:{},style:{},events:{},
    classList:{toggle(key,on){on?classes.add(key):classes.delete(key);},contains(key){return classes.has(key);}},
    setAttribute(key,value){this.attrs[key]=value;},addEventListener(key,fn){(this.events[key] ||= []).push(fn);},
    focus(){focused=this.index;},emit(type,key){const event={type,key,preventDefault(){}};for(const fn of this.events[type] || []) fn(event);},
    querySelectorAll(selector){const attr=selector.slice(1,-1);return nodes.filter(candidate=>{
      if(!(attr in candidate.attrs))return false;
      for(let p=candidate.parent;p!=null;p=nodes[p].parent)if(p===this.index)return true;
      return false;
    });}};
  for(const [key,value] of Object.entries(entry.attrs))if(key.startsWith("data-"))item.dataset[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value;
  return item;
});
global.document={querySelectorAll(selector){return nodes.filter(item=>selector.slice(1,-1) in item.attrs);}};
SCRIPT
const root=nodes.find(item=>"data-workbench-formula" in item.attrs);
const bars=root.querySelectorAll("[data-formula-primary]");
const cards=root.querySelectorAll("[data-formula-secondary]");
const closers=root.querySelectorAll("[data-formula-close]");
const check=(value,message)=>{if(!value)throw Error(message);};
check(cards.every(card=>card.hidden),"Secondary starts collapsed");
bars[0].emit("keydown"," ");
check(!cards[0].hidden && cards[1].hidden,"Space opens selected primary");
const items=cards[0].querySelectorAll("[data-formula-secondary-index]");
const path0=items.find(item=>item.tagName==="PATH" && item.dataset.formulaSecondaryIndex==="0");
const path1=items.find(item=>item.tagName==="PATH" && item.dataset.formulaSecondaryIndex==="1");
const legend0=items.find(item=>item.tagName==="BUTTON" && item.dataset.formulaSecondaryIndex==="0");
const legend1=items.find(item=>item.tagName==="BUTTON" && item.dataset.formulaSecondaryIndex==="1");
legend0.emit("click");
check(path0.classList.contains("active") && legend0.classList.contains("active") && path0.attrs["aria-pressed"]==="true","Legend activates matching sector");
legend0.emit("click");
check(!path0.classList.contains("active") && !legend0.classList.contains("active"),"Repeated click clears selection");
path1.emit("keydown","Enter");
check(legend1.classList.contains("active") && path1.classList.contains("active"),"Keyboard sector activates legend");
legend0.emit("pointerenter");
check(path0.classList.contains("active") && !path1.classList.contains("active"),"Hover links sector and legend");
legend0.emit("pointerleave");
check(path1.classList.contains("active") && legend1.classList.contains("active"),"Hover departure restores selection");
closers[0].emit("click");
check(cards.every(card=>card.hidden) && focused===bars[0].index,"Collapse returns focus to primary");
bars[1].emit("click");
check(cards[0].hidden && !cards[1].hidden,"Other primary opens correct panel");
bars[0].emit("click");
check(items.every(item=>!item.classList.contains("active")),"New drilldown clears previous secondary selection");
""".replace('NODES', json.dumps(nodes, ensure_ascii=False)).replace('SCRIPT', self.renderer().SCRIPT)
        result = subprocess.run([node, '-e', runner], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == '__main__':
    unittest.main()
