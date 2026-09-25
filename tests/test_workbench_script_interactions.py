"""Formula links must preserve source text and stay within one material."""
import importlib.util
import json
import shutil
import subprocess
import unittest

from test_workbench_report_html import Document


def sample(text="原句甲，原句乙；原句甲。"):
    return {"deliveryStatus": "available", "textAvailable": True, "text": text,
            "fieldAvailability": {"text": True, "formula": True},
            "formula": {"labels": [{"level_1_label": 1, "level_2_labels": [11, 12]}]}}


def groups():
    return [{"id": 1, "label": "商品卖点", "children": [
        {"id": 11, "label": "原料", "quotes": ["原句甲"]},
        {"id": 12, "label": "工艺", "quotes": ["原句乙"]}]}]


class ScriptInteractionTests(unittest.TestCase):
    def render(self, script=None, formula_groups=None, index=0):
        self.assertIsNotNone(importlib.util.find_spec("workbench_script_interactions"), "linked script renderer is missing")
        from workbench_script_interactions import render_linked_script
        return render_linked_script(sample() if script is None else script,
                                    groups() if formula_groups is None else formula_groups, material_index=index)

    def test_exact_text_survives_overlapping_and_repeated_quotes(self):
        script = sample("  甲乙丙\r\n甲乙\t<&>🙂尾字 ")
        formula_groups = groups()
        formula_groups[0]["children"][0]["quotes"] = ["甲乙", "甲乙"]
        formula_groups[0]["children"][1]["quotes"] = ["乙丙"]
        doc = Document(self.render(script, formula_groups))
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], script["text"])
        marks = doc.find("mark")
        self.assertEqual([mark["text"] for mark in marks], ["甲", "乙", "丙", "甲乙"])
        self.assertIn("c0-0", marks[1]["attrs"]["data-linked-keys"].split())
        self.assertIn("c0-1", marks[1]["attrs"]["data-linked-keys"].split())
        self.assertEqual(sum("c0-0" in mark["attrs"]["data-linked-keys"].split() for mark in marks), 3)

    def test_formula_sequence_preserves_repeated_primary_and_explicit_child_order(self):
        formula_groups = [
            {"id": 1, "label": "卖点", "children": [{"id": 11, "label": "原料", "quotes": []}]},
            {"id": 2, "label": "价格", "children": [{"id": 21, "label": "优惠", "quotes": []}]},
            {"id": 1, "label": "卖点", "children": [{"id": 12, "label": "工艺", "quotes": []}, {"id": 13, "label": "口感", "quotes": []}]},
        ]
        script = sample()
        script["formula"]["labels"] = [{"level_1_label": 1, "level_2_labels": [13, 12]},
                                       {"level_1_label": 2, "level_2_labels": [21]},
                                       {"level_1_label": 1, "level_2_labels": [11]},
                                       {"level_1_label": 999, "level_2_labels": [999]}]
        doc = Document(self.render(script, formula_groups))
        labels = [node["attrs"]["data-linked-label"] for node in doc.find("button") if "data-linked-node" in node["attrs"]]
        self.assertEqual(labels, ["卖点", "口感", "工艺", "价格", "优惠", "卖点", "原料"])
        self.assertEqual(len(doc.find("span", **{"class": "linked-flow-arrow"})), 2)
        self.assertNotIn("999", "".join(node["text"] for node in doc.find("section")))

    def test_unknown_or_near_matching_quotes_do_not_create_highlights(self):
        formula_groups = groups()
        formula_groups[0]["children"][0]["quotes"] = ["原 句甲", {"text": "原句甲"}, "", None]
        formula_groups[0]["children"][1]["quotes"] = ["原句乙！"]
        doc = Document(self.render(formula_groups=formula_groups))
        self.assertEqual(doc.find("mark"), [])
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], sample()["text"])

    def test_missing_body_and_rejected_identity_never_invent_or_leak_text(self):
        script = sample("不可信原句甲")
        script.update(deliveryStatus="identityMismatch", statusLabel="身份不一致，未采信")
        rejected = self.render(script)
        self.assertNotIn("不可信", rejected)
        self.assertNotIn("商品卖点", rejected)
        self.assertEqual(Document(rejected).find("mark"), [])
        script.update(deliveryStatus="missing", textAvailable=False)
        doc = Document(self.render(script))
        self.assertFalse(doc.find("button", **{"data-linked-copy": "script"}))
        self.assertFalse(doc.find("div", **{"class": "script-text"}))
        self.assertTrue(doc.find("button", **{"data-linked-copy": "formula"}))

    def test_labels_and_quotes_are_escaped_without_executable_markup(self):
        injection = '<img src=x onerror="alert(1)"></script>'
        formula_groups = groups()
        formula_groups[0]["label"] = injection
        formula_groups[0]["children"][0].update(label=injection, quotes=[injection])
        doc = Document(self.render(sample(injection), formula_groups))
        self.assertEqual(doc.find("img"), [])
        self.assertEqual(doc.find("script"), [])
        self.assertEqual(doc.find("div", **{"class": "script-text"})[0]["text"], injection)
        self.assertFalse(any(key.startswith("on") for el in doc.elements for key in el["attrs"]))

    def test_click_keyboard_and_copy_work_without_changing_other_material_or_navigation(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable for interaction execution")
        doc = Document(self.render(index=0) + self.render(index=1))
        from workbench_script_interactions import SCRIPT
        index = {id(el): i for i, el in enumerate(doc.elements)}
        payload = [{"tag": el["tag"], "attrs": el["attrs"], "text": el["text"],
                    "parent": index.get(id(el["parent"]))} for el in doc.elements]
        runner = r'''
const payload = PAYLOAD;
let scrolled = null, focused = null, copied = [];
const elements = payload.map(item => {
  const classes = new Set((item.attrs.class || '').split(' '));
  const result = {tagName:item.tag.toUpperCase(), attrs:{...item.attrs}, textContent:item.text, dataset:{}, listeners:{},
    classList:{toggle(name,on){on?classes.add(name):classes.delete(name);},contains(name){return classes.has(name);}},
    setAttribute(name,value){this.attrs[name]=String(value);},getAttribute(name){return this.attrs[name];},
    addEventListener(name,callback){this.listeners[name]=callback;},
    scrollIntoView(){scrolled=this;},focus(){focused=this;},
    querySelectorAll(selector){return elements.filter(candidate=>candidate!==this && descendant(candidate,this) && matches(candidate,selector));},
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}};
  for(const [key,value] of Object.entries(item.attrs)) if(key.startsWith('data-')) result.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;
  return result;
});
elements.forEach((el,i)=>el.parentElement=payload[i].parent===null?null:elements[payload[i].parent]);
function descendant(el,parent){for(let p=el.parentElement;p;p=p.parentElement)if(p===parent)return true;return false;}
function matches(el,selector){if(selector.startsWith('.'))return el.classList.contains(selector.slice(1));const match=selector.match(/^\[([^=\]]+)(?:=["']([^"']*)["'])?\]$/);return match && match[1] in el.attrs && (match[2]===undefined || el.attrs[match[1]]===match[2]);}
global.document={querySelectorAll:selector=>elements.filter(el=>matches(el,selector)),activeElement:null};
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async text=>{copied.push(text);}}},configurable:true});
SCRIPT
const check=(condition,message)=>{if(!condition)throw Error(message);};
const roots=elements.filter(el=>'linkedScript' in el.dataset);
const buttons=roots[0].querySelectorAll('[data-linked-node]');
const marks=roots[0].querySelectorAll('[data-linked-keys]');
buttons[0].listeners.click();
check(marks.every(el=>el.classList.contains('linked-active')),'Primary must select every child quote');
buttons[0].listeners.click();
check(marks.every(el=>!el.classList.contains('linked-active')),'Second click must cancel selection');
buttons[1].listeners.click();
check(marks.filter(el=>el.classList.contains('linked-active')).length===2,'Formula must select both repeated exact quotes');
check(scrolled===marks[0],'Formula click must locate first matching quote');
check(roots[1].querySelectorAll('[data-linked-keys]').every(el=>!el.classList.contains('linked-active')),'Selection leaked to another material');
marks[1].listeners.keydown({key:'Enter',preventDefault(){}});
check(buttons[2].attrs['aria-pressed']==='true','Text keyboard activation must select corresponding child');
check(buttons[1].attrs['aria-pressed']==='false','Previous unrelated child remained selected');
check(marks.filter(el=>el.classList.contains('linked-active')).length===1,'Text selection must not expand to unrelated children under the same primary');
check(scrolled===buttons[0] || scrolled===buttons[2],'Text activation must locate formula');
check(!elements.some(el=>'href' in el.attrs),'Interactions must not change navigation anchors');
(async()=>{
  await roots[0].querySelector('[data-linked-copy="formula"]').listeners.click();
  await roots[0].querySelector('[data-linked-copy="script"]').listeners.click();
  check(copied[0]==='商品卖点\n  - 原料\n  - 工艺','Formula copy must preserve hierarchy');
  check(copied[1]==='原句甲，原句乙；原句甲。','Script copy must preserve complete source text');
  navigator.clipboard.writeText=async()=>{throw Error('clipboard denied');};
  await roots[0].querySelector('[data-linked-copy="script"]').listeners.click();
  check(roots[0].querySelector('[data-linked-status]').textContent.includes('复制未成功'),'Clipboard failure must be reported');
  check(roots[0].querySelector('[data-linked-copy="script"]').textContent==='复制文案','Failure must not retain a previous success label');
  navigator.clipboard=null;
  let input=null,removed=false;
  document.createElement=()=>({style:{},select(){},remove(){removed=true;}});
  document.body={appendChild(el){input=el;}};
  document.execCommand=command=>{check(command==='copy','Unexpected browser command');copied.push(input.value);return true;};
  await roots[0].querySelector('[data-linked-copy="script"]').listeners.click();
  check(copied[2]==='原句甲，原句乙；原句甲。' && removed,'Offline clipboard fallback must copy exact text and clean up');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace("PAYLOAD", json.dumps(payload, ensure_ascii=False)).replace("SCRIPT", SCRIPT)
        result = subprocess.run([node, "-e", runner], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
