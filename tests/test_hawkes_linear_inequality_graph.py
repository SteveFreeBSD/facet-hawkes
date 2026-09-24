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
SYSTEM_PLAN = {
    "kind": "linear-inequality-system",
    "connector": "or",
    "operation": "union",
    "inequalities": [
        {
            "coefficients": {"x": "1", "y": "0", "constant": "-6"},
            "relation": ">",
            "boundary": "dashed",
        },
        {
            "coefficients": {"x": "0", "y": "1", "constant": "-5"},
            "relation": ">=",
            "boundary": "solid",
        },
    ],
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
var testPoint={title:'Test Point',description:'A Test Point at the origin.'};
var regionA={label:'A',curvePlotOnSelect:()=>{},children:[testPoint]};
var regionB={label:'B',curvePlotOnSelect:()=>{},children:[]};
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


def system_page():
    context = quickjs.Context()
    context.eval(
        r"""
var now=0,timers=[];
var setTimeout=(fn,ms)=>{timers.push({fn,at:now+ms});return timers.length;};
var Event=class{constructor(type,init={}){this.type=type;Object.assign(this,init);}};
var MouseEvent=Event;
var HTMLInputElement=class{
  constructor(id,label,operation){this.id=id;this.label=label;this.operation=operation;
    this.type='radio';this.name='set-operation';this.checked=false;this.disabled=false;
    this.isConnected=true;}
  getBoundingClientRect(){return {width:80,height:20};}
  getAttribute(name){return name==='aria-label'?this.label:'';}
  closest(){return null;}
  dispatchEvent(event){if(event.type==='click'){
    radios.forEach(r=>{r.checked=false;});this.checked=true;
    regions.forEach((region,index)=>{region.select=this.operation==='union'?index<3:index===3;});
  }return true;}
};
var radios=[
  new HTMLInputElement('choice-one','the union of the individual solution sets','union'),
  new HTMLInputElement('choice-two','the intersection of the individual solution sets','intersection')
];
var lineOne={ID:'prior-a',Equation:[1,0,-6],objectXML:()=>
  '<line id="prior-a"><stroke>dashed</stroke><definedby>vertical</definedby><xcoordinate>6</xcoordinate></line>'};
var lineTwo={ID:'prior-b',Equation:[0,1,-5],objectXML:()=>
  '<line id="prior-b"><stroke>solid</stroke><definedby>horizontal</definedby><ycoordinate>5</ycoordinate></line>'};
var regions=Array.from({length:4},(_,index)=>({Index:index,index,interactiveRole:'checkbox',select:false,
  objectXML(){return '<region><isselected>'+this.select+'</isselected><shade>'+this.select+'</shade></region>';}}));
var regionSet={children:regions,interactiveRole:'norole'};
var system={type:'inequalities',Regions:regionSet,children:[regionSet,lineOne,lineTwo],
  objectXML:()=>'<system>'+lineOne.objectXML()+lineTwo.objectXML()+regions.map(r=>r.objectXML()).join('')+'</system>',
  userAnswer:()=>{const selected=regions.map(r=>r.select?String(r.index):'').join('');
    return '<selectedregions>'+selected+'</selectedregions><emptycheck>'+(selected===''?'true':'false')+'</emptycheck>';}};
var model={isGraph:true,getEnableState:()=>false,graphXML:()=>'<graph><grid><type>cartesian</type></grid></graph>',
  allGraphObjects:()=>({mounted:system})};
var questions=Object.fromEntries(['questionDescription','questionString','partInformation']
  .map(id=>[id,{id,text:'q',isConnected:true}]));
var byId=Object.fromEntries(radios.map(one=>[one.id,one]));
var root={isConnected:true,getBoundingClientRect:()=>({width:400,height:400}),
  querySelector:()=>null,querySelectorAll:()=>[]};
var document={
  getElementById:id=>byId[id]??questions[id]??null,
  querySelector:()=>null,
  querySelectorAll:selector=>selector==='#QGraph'?[root]
    :selector==='svg#svg_numberline'?[]
    :selector==='input[type="radio"]'?radios
    :selector.includes('input.qbaseCSS')?[]
    :selector==='[id*="customMessageBox"]'?[]:[],
};
var XMLSerializer=class{serializeToString(node){return node.id+':'+node.text;}};
var DOMParser=class{parseFromString(xml){return {querySelector(selector){
  const tag=selector.split('>').pop().trim();const match=xml.match(new RegExp('<'+tag+'>([^<]*)</'+tag+'>'));
  return match?{textContent:match[1]}:null;},querySelectorAll(){return [];}};}};
var CSS={escape:text=>text};
var window={location:{origin:'https://learn.hawkeslearning.com'},quant_wp_UI:{controlsCollection:{
  first:{0:radios[0],length:1},second:{0:radios[1],length:1},graph:model}}};
"""
    )
    source = re.sub(r"^export ", "", GRAPH.read_text(encoding="utf-8"), flags=re.M)
    context.eval(source)
    return context


def graph_choice_page():
    """The live four-model/two-boundary graph-choice ownership shape."""
    context = quickjs.Context()
    context.eval(
        r"""
var DOMParser=class{parseFromString(xml){return {querySelector(selector){
  const tag=selector.split('>').pop().trim();
  const match=xml.match(new RegExp('<'+tag+'>([^<]*)</'+tag+'>'));
  return match?{textContent:match[1]}:null;}};}};
function line(id,x,stroke='dashed') { return {ID:id,Equation:[1,0,-x],group:null,
  objectXML:()=>'<line><type>inequality</type><name>'+id+'</name><stroke>'+stroke+'</stroke>'+
    '<definedby>xintercept</definedby><xcoordinate>'+x+'</xcoordinate></line>'}; }
function region(shade,min='',max='') { return {group:null,objectXML:()=>'<region><shade>'+shade+
  '</shade>'+(min?'<xminimum>'+min+'</xminimum>':'')+
  (max?'<xmaximum>'+max+'</xmaximum>':'')+'</region>'}; }
function option(left,right,shading,index) {
  const owner={role:'radio',id:'owner-'+index,getBoundingClientRect:()=>({width:290,height:290}),
    getAttribute:name=>name==='role'?'radio':'',contains:node=>node===root};
  const root={getBoundingClientRect:()=>({width:290,height:290}),
    contains:node=>node===group,closest:selector=>selector==='[role="radio"]'?owner:null};
  const group={};
  const one=line('BoundaryLine1',left),two=line('BoundaryLine2',right);
  const regions=shading==='between' ? [
    region('true','BoundaryLine1','BoundaryLine2'),
    region('false','BoundaryLine1,BoundaryLine2',''),
    region('false','','BoundaryLine1,BoundaryLine2')
  ] : [
    region('true','BoundaryLine2','BoundaryLine1'),
    region('true','','BoundaryLine1,BoundaryLine2'),
    region('true','BoundaryLine1,BoundaryLine2','')
  ];
  const system={type:'inequalities',group,children:[one,two],Regions:{children:regions}};
  const model={isGraph:true,getEnableState:()=>true,allGraphObjects:()=>({system})};
  return {root,model};
}
var options=[option(-4,3,'between',1),option(-4,3,'outside',2),
  option(-3,4,'between',3),option(-3,4,'outside',4)];
var document={querySelectorAll:selector=>selector==='svg[role="presentation"]'
  ?options.map(one=>one.root):[],getElementById:()=>null,querySelector:()=>null};
var window={location:{origin:'https://learn.hawkeslearning.com'},quant_wp_UI:{controlsCollection:
  Object.fromEntries(options.map((one,index)=>['graph'+index,one.model]))}};
"""
    )
    source = re.sub(r"^export ", "", GRAPH.read_text(encoding="utf-8"), flags=re.M)
    context.eval(source)
    return context


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


def test_graph_choices_are_owned_and_described_by_model_semantics():
    described = run(graph_choice_page())

    assert described == {
        "ok": True,
        "kind": "option",
        "surface": "graph-choice",
        "code": "graph-choice-described",
        "enabled": True,
        "choices": [
            "Graph: x=-4 dashed; x=3 dashed; shade=between",
            "Graph: x=-4 dashed; x=3 dashed; shade=outside",
            "Graph: x=-3 dashed; x=4 dashed; shade=between",
            "Graph: x=-3 dashed; x=4 dashed; shade=outside",
        ],
        "probe": {
            "engine": "cartesian-graph-choice",
            "choices": 4,
            "boundaries": 2,
            "regions": 3,
            "ownership": "model-group-inside-selectable-svg",
        },
    }


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


def test_opposite_region_is_chosen_when_the_page_test_point_fails_the_inequality():
    context = page()
    described = run(context)
    plan = {**PLAN, "relation": ">", "boundary": "dashed"}

    result = run(
        context,
        {
            "plan": plan,
            "coefficients": ["1", "3", "-3"],
            "snapshot": described["snapshot"],
        },
    )

    assert result["code"] == "graph-linear-inequality-verified"
    assert result["region"] == "B"
    assert result["testPoint"] == [0, 0]
    assert context.eval("byId['region-a'].checked") is False
    assert context.eval("byId['region-b'].checked") is True


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


def test_mounted_system_surface_discovers_its_page_owned_model():
    described = run(system_page())

    assert described["ok"] is True
    assert described["context"] == {
        "family": "linear-inequality-system",
        "controls": "mounted-boundaries-combined-regions",
    }
    assert described["probe"] == {
        "engine": "cartesian-system",
        "boundaries": 2,
        "regions": 4,
        "operations": ["intersection", "union"],
    }


def test_or_selects_the_page_owned_union_without_replacing_mounted_boundaries():
    context = system_page()
    described = run(context)
    before = context.eval("JSON.stringify([lineOne.objectXML(),lineTwo.objectXML()])")

    result = run(context, {"plan": SYSTEM_PLAN, "snapshot": described["snapshot"]})

    assert result == {
        "ok": True,
        "code": "graph-linear-inequality-system-verified",
        "operation": "union",
        "boundaries": 2,
        "selectedRegions": 3,
        "events": 1,
    }
    assert context.eval("radios[0].checked") is True
    assert context.eval("system.userAnswer()") == (
        "<selectedregions>012</selectedregions><emptycheck>false</emptycheck>"
    )
    assert (
        context.eval("JSON.stringify([lineOne.objectXML(),lineTwo.objectXML()])")
        == before
    )


def test_and_selects_the_page_owned_intersection():
    context = system_page()
    described = run(context)
    plan = {**SYSTEM_PLAN, "connector": "and", "operation": "intersection"}

    result = run(context, {"plan": plan, "snapshot": described["snapshot"]})

    assert result["code"] == "graph-linear-inequality-system-verified"
    assert result["selectedRegions"] == 1
    assert context.eval("radios[1].checked") is True
    assert context.eval("system.userAnswer()") == (
        "<selectedregions>3</selectedregions><emptycheck>false</emptycheck>"
    )
