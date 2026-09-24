"""The composite Cartesian linear-inequality answer surface."""

from __future__ import annotations

import json
import re
from pathlib import Path

import quickjs

from ethnos.hawkes_protocol import GraphContext

GRAPH = Path(__file__).parents[1] / "extension" / "common" / "graph-actions.js"
PLAN = {
    "kind": "linear-inequality",
    "coefficients": {"x": "1", "y": "3", "constant": "-3"},
    "relation": "<",
    "boundary": "dashed",
    "points": [{"x": "3", "y": "0"}, {"x": "0", "y": "1"}],
}


PAGE = r"""
var now = 0, timers = [];
var setTimeout = (fn, ms) => { timers.push({fn, at: now + ms}); return timers.length; };
var Event = class { constructor(type, init={}) { this.type=type; Object.assign(this, init); } };
var InputEvent = Event;
var MouseEvent = Event;
var HTMLInputElement = class {
  constructor(id, type='text', name='', label='') {
    this.id=id; this.type=type; this.name=name; this.label=label; this._value='';
    this.checked=false; this.disabled=false; this.readOnly=false; this.isConnected=true;
  }
  get value() { return this._value; }
  set value(value) { this._value=String(value); }
  getBoundingClientRect() { return {width:60,height:20}; }
  getAttribute(name) { return name === 'aria-label' ? this.label : ''; }
  closest() { return null; }
  focus() {}
  dispatchEvent(event) {
    if (event.type === 'click' && this.type === 'radio') {
      radios.filter(r => r.name === this.name).forEach(r => { r.checked=false; });
      this.checked=true;
    }
    return true;
  }
};
var XMLSerializer = class { serializeToString(node) { return node.id + ':' + node.text; } };
var DOMParser = class { parseFromString() { return {querySelector(selector) {
  const values={'cartesian > xmin':'-10','cartesian > xmax':'10',
    'cartesian > ymin':'-10','cartesian > ymax':'10'};
  return values[selector] === undefined ? null : {textContent:values[selector]};
}}; } };
var fields=Array.from({length:4},(_,i)=>new HTMLInputElement('txtUserAnswer1'+(i+1)+'_num'));
var radios=[
  new HTMLInputElement('solid','radio','boundary','Solid (—)'),
  new HTMLInputElement('dashed','radio','boundary','Dashed (---)'),
  new HTMLInputElement('region-a','radio','region','A'),
  new HTMLInputElement('region-b','radio','region','B'),
];
var regionA={label:'A',children:[{x:0,y:0}]};
var regionB={label:'B',children:[{x:0,y:2}]};
// The live composite model is deliberately not directly draggable. Hawkes
// reports that graph model disabled while leaving its native answer controls
// enabled; that must not make the whole answer surface unwritable.
var model={isGraph:true,getEnableState:()=>false,graphXML:()=>'<graph/>',
  // Hawkes adds regions asynchronously only after all four point fields have
  // redrawn the boundary line.
  allGraphObjects:()=>({system:{Regions:{children:now>=160?[regionA,regionB]:[]},children:[]}})};
var questions=Object.fromEntries(['questionDescription','questionString','partInformation']
  .map(id=>[id,{id,text:'q',isConnected:true}]));
var byId=Object.fromEntries([...fields,...radios].map(one=>[one.id,one]));
var document={
  getElementById:id=>byId[id]??questions[id]??null,
  querySelector:()=>null,
  querySelectorAll:selector=>selector==='svg#svg_numberline'?[]
    : selector==='#QGraph'?[]
    : selector.includes('input.qbaseCSS')?fields
    : selector==='input[type="radio"]'?radios
    : selector==='[id*="customMessageBox"]'?[]:[],
};
var CSS={escape:text=>text};
var window={location:{origin:'https://learn.hawkeslearning.com'},
  quant_wp_UI:{controlsCollection:{graph:model}}};
"""


def page():
    context = quickjs.Context()
    context.eval(PAGE)
    source = re.sub(r"^export ", "", GRAPH.read_text(encoding="utf-8"), flags=re.M)
    context.eval(source)
    return context


def run(context, offered=None):
    context.eval(
        "var done=null; Promise.resolve(graphOperation("
        + json.dumps(offered)
        + ")).then(value=>{done=value}, error=>{done={ok:false,code:String(error)}});"
    )
    for _ in range(200):
        while context.execute_pending_job():
            pass
        if context.eval("done !== null"):
            break
        if not context.eval("timers.length"):
            break
        context.eval(
            "timers.sort((a,b)=>a.at-b.at);var timer=timers.shift();"
            "now=Math.max(now,timer.at);timer.fn();"
        )
    return json.loads(context.eval("JSON.stringify(done)"))


def test_composite_surface_describes_itself_without_a_focused_box():
    described = run(page())

    assert described["ok"] is True
    assert described["context"] == {
        "family": "linear-inequality",
        "bounds": [-10, 10, -10, 10],
        "snap": [1, 1],
        "controls": "boundary-two-points-regions",
    }
    GraphContext.model_validate(described["context"])


def test_region_is_chosen_by_its_page_owned_test_point_not_its_label():
    context = page()
    described = run(context)

    result = run(
        context,
        {
            "plan": PLAN,
            "coefficients": ["1", "3", "-3"],
            "snapshot": described["snapshot"],
        },
    )

    assert result == {
        "ok": True,
        "code": "graph-linear-inequality-verified",
        "boundary": "dashed",
        "points": [[3, 0], [0, 1]],
        "region": "A",
        "testPoint": [0, 0],
    }
    assert context.eval("byId.dashed.checked") is True
    assert context.eval("byId.solid.checked") is False
    assert context.eval("byId['region-a'].checked") is True
    assert context.eval("JSON.stringify(fields.map(field=>field.value))") == (
        '["3","0","0","1"]'
    )


def test_a_matching_partial_boundary_is_resumed_and_the_region_is_completed():
    context = page()
    described = run(context)
    context.eval(
        "fields[0].value='3';fields[1].value='0';fields[2].value='0';"
        "fields[3].value='1';byId.dashed.checked=true;"
    )
    # The offered snapshot belongs to the current partially populated surface.
    described = run(context)

    result = run(
        context,
        {
            "plan": PLAN,
            "coefficients": ["1", "3", "-3"],
            "snapshot": described["snapshot"],
        },
    )

    assert result["code"] == "graph-linear-inequality-verified"
    assert context.eval("byId['region-a'].checked") is True
